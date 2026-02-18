"""Postgres LISTEN/NOTIFY listener for the async event loop.

Maintains a single async psycopg connection per worker process,
listening on all channels that SSE clients are subscribed to.
When a NOTIFY arrives, it dispatches the event to the connection manager.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import psycopg

if TYPE_CHECKING:
    from .handler import AsyncConnectionManager

log = logging.getLogger("plain.channels")


def _get_connection_string() -> str:
    """Build a psycopg connection string from Plain's database settings."""
    from plain.models.database_url import build_database_url
    from plain.runtime import settings

    return build_database_url(settings.DATABASE)


class PostgresListener:
    """Async Postgres LISTEN/NOTIFY listener.

    One instance per worker process, running on the background async event loop.
    Dynamically subscribes/unsubscribes to Postgres channels as SSE clients
    connect and disconnect.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        connection_manager: AsyncConnectionManager,
    ) -> None:
        self._loop = loop
        self._manager = connection_manager
        self._conn: psycopg.AsyncConnection | None = None
        self._listening: set[str] = set()
        self._listener_task: asyncio.Task | None = None
        self._stopped = False

    async def start(self) -> None:
        """Connect to Postgres and start the listener loop."""
        try:
            conninfo = _get_connection_string()
            self._conn = await psycopg.AsyncConnection.connect(
                conninfo, autocommit=True
            )
            self._listener_task = self._loop.create_task(self._listen_loop())
            log.debug("Postgres LISTEN connection established")
        except Exception:
            log.exception("Failed to connect to Postgres for LISTEN")

    async def _listen_loop(self) -> None:
        """Main loop: receive notifications and dispatch them."""
        if self._conn is None:
            return

        try:
            async for notify in self._conn.notifies():
                if self._stopped:
                    break
                await self._manager.dispatch_event(notify.channel, notify.payload or "")
        except psycopg.OperationalError:
            if not self._stopped:
                log.warning("Postgres LISTEN connection lost, reconnecting...")
                await self._reconnect()
        except Exception:
            if not self._stopped:
                log.exception("Error in Postgres LISTEN loop")
                await self._reconnect()

    async def _reconnect(self) -> None:
        """Try to reconnect after a connection loss."""
        await self._close_connection()
        # Exponential backoff: 1s, 2s, 4s, 8s, max 30s
        delay = 1.0
        while not self._stopped:
            try:
                conninfo = _get_connection_string()
                self._conn = await psycopg.AsyncConnection.connect(
                    conninfo, autocommit=True
                )
                # Re-subscribe to all channels we were listening on
                channels_to_restore = set(self._listening)
                self._listening.clear()
                for channel in channels_to_restore:
                    await self._execute_listen(channel)
                self._listener_task = self._loop.create_task(self._listen_loop())
                log.info("Postgres LISTEN connection restored")
                return
            except Exception:
                log.debug("Reconnect failed, retrying in %.1fs", delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)

    async def listen(self, channel: str) -> None:
        """Start listening on a Postgres channel (if not already)."""
        if channel in self._listening:
            return
        await self._execute_listen(channel)

    async def unlisten(self, channel: str) -> None:
        """Stop listening on a Postgres channel."""
        if channel not in self._listening:
            return
        if self._conn is not None and not self._conn.closed:
            try:
                # Channel names are identifiers, use sql.Identifier for safety
                await self._conn.execute(
                    psycopg.sql.SQL("UNLISTEN {}").format(
                        psycopg.sql.Identifier(channel)
                    )
                )
                self._listening.discard(channel)
                log.debug("UNLISTEN %s", channel)
            except Exception:
                log.debug("Failed to UNLISTEN %s", channel)

    async def _execute_listen(self, channel: str) -> None:
        """Execute a LISTEN command for a channel."""
        if self._conn is not None and not self._conn.closed:
            try:
                # Channel names are identifiers, use sql.Identifier for safety
                await self._conn.execute(
                    psycopg.sql.SQL("LISTEN {}").format(psycopg.sql.Identifier(channel))
                )
                self._listening.add(channel)
                log.debug("LISTEN %s", channel)
            except Exception:
                log.exception("Failed to LISTEN on %s", channel)

    async def stop(self) -> None:
        """Stop the listener and close the connection."""
        self._stopped = True
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        await self._close_connection()
        log.debug("Postgres listener stopped")

    async def _close_connection(self) -> None:
        """Close the Postgres connection."""
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception:
                pass
            self._conn = None
