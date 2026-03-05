"""Shared Postgres LISTEN connection for realtime notifications.

One connection per worker process, shared across all subscribers.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("plain.realtime")

_shared_listener: SharedListener | None = None


def _get_connection_string() -> str:
    """Build a psycopg connection string from Plain's database settings."""
    from plain.models.database_url import build_database_url
    from plain.runtime import settings

    return build_database_url(settings.DATABASE)


class SharedListener:
    """Per-worker singleton that holds one Postgres connection for LISTEN.

    Fans out notifications to subscriber queues.
    """

    def __init__(self) -> None:
        self._conn = None
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()
        self._reader_task: asyncio.Task | None = None

    @classmethod
    def get(cls) -> SharedListener:
        global _shared_listener
        if _shared_listener is None:
            _shared_listener = cls()
        return _shared_listener

    async def subscribe(self, queue: asyncio.Queue, *channels: str) -> None:
        async with self._lock:
            await self._ensure_connected()

            new_channels = []
            for channel in channels:
                if channel not in self._subscribers:
                    self._subscribers[channel] = set()
                    new_channels.append(channel)
                self._subscribers[channel].add(queue)

            if new_channels and self._conn:
                await self._listen_channels(new_channels)

    async def unsubscribe(self, queue: asyncio.Queue, *channels: str) -> None:
        async with self._lock:
            unlisten_channels = []
            for channel in channels:
                subs = self._subscribers.get(channel)
                if subs is None:
                    continue
                subs.discard(queue)
                if not subs:
                    del self._subscribers[channel]
                    unlisten_channels.append(channel)

            if unlisten_channels and self._conn:
                try:
                    await self._unlisten_channels(unlisten_channels)
                except Exception:
                    pass

    async def _ensure_connected(self) -> None:
        if self._conn is not None:
            return

        import psycopg

        conninfo = _get_connection_string()
        self._conn = await psycopg.AsyncConnection.connect(conninfo, autocommit=True)
        self._reader_task = asyncio.create_task(self._run())

    async def _listen_channels(self, channels: list[str]) -> None:
        import psycopg.sql

        for channel in channels:
            await self._conn.execute(
                psycopg.sql.SQL("LISTEN {}").format(psycopg.sql.Identifier(channel))
            )

    async def _unlisten_channels(self, channels: list[str]) -> None:
        import psycopg.sql

        for channel in channels:
            await self._conn.execute(
                psycopg.sql.SQL("UNLISTEN {}").format(psycopg.sql.Identifier(channel))
            )

    async def _run(self) -> None:
        """Background task: read notifications and fan out to subscriber queues."""
        backoff = 0.5
        max_backoff = 30.0

        while True:
            try:
                async for notify in self._conn.notifies():
                    backoff = 0.5  # Reset on successful notification
                    async with self._lock:
                        queues = self._subscribers.get(notify.channel)
                        if queues:
                            for queue in queues:
                                queue.put_nowait((notify.channel, notify.payload or ""))
            except asyncio.CancelledError:
                return
            except Exception:
                logger.warning(
                    "Shared Postgres listener disconnected, reconnecting in %.1fs",
                    backoff,
                )
                # Connection is dead — reconnect directly (don't use
                # _ensure_connected which would spawn a duplicate reader task)
                self._conn = None
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

                try:
                    await self._reconnect()
                except Exception:
                    logger.warning("Reconnect failed, will retry in %.1fs", backoff)
                    continue

    async def _reconnect(self) -> None:
        """Re-establish the Postgres connection and re-LISTEN all channels."""
        import psycopg

        conninfo = _get_connection_string()
        async with self._lock:
            self._conn = await psycopg.AsyncConnection.connect(
                conninfo, autocommit=True
            )
            if self._subscribers:
                await self._listen_channels(list(self._subscribers.keys()))
