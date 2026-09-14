"""Client ID Metadata Documents (CIMD).

A `client_id` may be an HTTPS URL pointing at a small JSON document the client
hosts on its own domain (draft-ietf-oauth-client-id-metadata-document, adopted
by MCP as SEP-991). Instead of registering, the client presents the URL; we
fetch the document, check that it claims that exact URL as its `client_id`,
and use its `redirect_uris` as the registration. Claude's connector does this
by default — its document lives at https://claude.ai/oauth/mcp-oauth-client-metadata.

The whole risk of this feature is that it makes the server fetch an
attacker-supplied URL, so the fetch is deliberately narrow: HTTPS only, the
host must resolve to public addresses, the connection is pinned to the address
we checked (DNS rebinding can't swap it), redirects are never followed, the
body is capped at 5 KB, and the whole thing has a short deadline.

Fetched documents are stored on the `OAuthApplication` row keyed by the URL —
one row per client product, not per install — with a TTL from the document's
`Cache-Control` and a grace period during which a failed refetch serves the
last good copy (Claude's metadata endpoints have had outages).
"""

from __future__ import annotations

import ipaddress
import json
import logging
import socket
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx
from plain.runtime import settings
from plain.utils import timezone

from .models import (
    _LOOPBACK_HOSTS,
    OAuthApplication,
    _is_allowed_redirect_uri,
)

logger = logging.getLogger(__name__)

# Draft -02 recommends a 5 KB read cap. Claude's document is ~350 bytes.
MAX_DOCUMENT_BYTES = 5 * 1024

# Total deadline for the fetch, including reading the body.
FETCH_TIMEOUT_SECONDS = 5.0

# The document's Cache-Control is honored within these bounds. No directive
# (or no-store / no-cache) gets the default.
MIN_CACHE_SECONDS = 5 * 60
MAX_CACHE_SECONDS = 24 * 60 * 60
DEFAULT_CACHE_SECONDS = 60 * 60

# After the cached document expires, a failed refetch keeps serving the
# stored copy for this long — then the failure is the client's problem.
STALE_GRACE_PERIOD = timedelta(days=7)

MAX_CLIENT_ID_LENGTH = 2048

# Hosts under these TLDs are never public (RFC 2606, RFC 6761), so a URL naming
# one is rejected before any DNS lookup.
_NON_PUBLIC_TLDS = {"localhost", "local", "test", "invalid", "example", "internal"}

_USER_AGENT = "plain.oauthserver (+https://plainframework.com)"

# NAT64 (RFC 6052) embeds an IPv4 address that `is_global` doesn't see through.
_NAT64_PREFIX = ipaddress.IPv6Network("64:ff9b::/96")


class ClientMetadataError(Exception):
    """A client_id URL or its metadata document can't be used.

    The message is safe to show to the end user on the consent screen — it
    names what was wrong, never the fetched content.
    """


@dataclass(frozen=True)
class ClientMetadata:
    """What we keep from a validated document."""

    name: str
    redirect_uris: list[str]


def is_client_id_url(client_id: str) -> bool:
    """Whether a client_id is a metadata-document URL rather than a registered id."""
    return client_id.startswith("https://")


def validate_client_id_url(client_id: str) -> str:
    """Enforce the draft's Client Identifier URL rules before we go anywhere near it.

    Returns the URL unchanged — it's compared and stored by simple string
    comparison, never normalized.
    """
    if len(client_id) > MAX_CLIENT_ID_LENGTH:
        raise ClientMetadataError("client_id URL is too long")
    if not client_id.startswith("https://"):
        raise ClientMetadataError("client_id URL must use https")
    if any(ord(c) <= 0x20 or 0x7F <= ord(c) <= 0x9F or c == "\\" for c in client_id):
        raise ClientMetadataError(
            "client_id URL must not contain whitespace, control characters, or backslashes"
        )
    if "#" in client_id:
        raise ClientMetadataError("client_id URL must not contain a fragment")
    if "?" in client_id:
        raise ClientMetadataError("client_id URL must not contain a query string")

    split = urlsplit(client_id)
    if split.username is not None or split.password is not None:
        raise ClientMetadataError("client_id URL must not contain credentials")
    try:
        port = split.port
    except ValueError:
        raise ClientMetadataError("client_id URL has an invalid port") from None
    if port is not None and not 1 <= port <= 65535:
        raise ClientMetadataError("client_id URL has an invalid port")

    host = split.hostname
    if not host:
        raise ClientMetadataError("client_id URL must have a host")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ClientMetadataError(
            "client_id URL must use a hostname, not an IP address"
        )
    labels = host.rstrip(".").split(".")
    if len(labels) < 2 or labels[-1] in _NON_PUBLIC_TLDS:
        raise ClientMetadataError("client_id URL must use a public hostname")

    # Check the raw path: a parser that normalizes "." / ".." would hide them.
    if not split.path or split.path == "/":
        raise ClientMetadataError("client_id URL must have a path")
    for segment in split.path.split("/"):
        if unquote(segment) in (".", ".."):
            raise ClientMetadataError("client_id URL must not contain dot segments")

    return client_id


def is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Whether an address is globally routable — the only kind we'll connect to."""
    if isinstance(address, ipaddress.IPv6Address):
        # See through the encodings that carry an IPv4 address inside IPv6.
        if address.ipv4_mapped is not None:
            return is_public_address(address.ipv4_mapped)
        if address.sixtofour is not None:
            return is_public_address(address.sixtofour)
        if address in _NAT64_PREFIX:
            return is_public_address(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF))
    return address.is_global and not address.is_multicast


def resolve_public_address(*, host: str, port: int) -> str:
    """Resolve a hostname and return one address, refusing if any answer isn't public.

    Every answer has to pass, not just the first: a host that mixes a public
    address with an internal one is exactly what a rebinding attack looks like.
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise ClientMetadataError(f"Could not resolve {host}") from None
    if not infos:
        raise ClientMetadataError(f"Could not resolve {host}")

    addresses = []
    for info in infos:
        # Link-local IPv6 answers carry a "%scope" suffix ip_address won't parse.
        raw = str(info[4][0]).split("%", 1)[0]
        addresses.append(ipaddress.ip_address(raw))
    for address in addresses:
        if not is_public_address(address):
            raise ClientMetadataError(f"{host} does not resolve to a public address")
    return str(addresses[0])


def cache_ttl_seconds(cache_control: str) -> int:
    """How long to trust a document, from its Cache-Control header, within our bounds."""
    directives: dict[str, str] = {}
    for part in cache_control.split(","):
        name, _, value = part.strip().partition("=")
        directives[name.strip().lower()] = value.strip().strip('"')

    if "no-store" in directives or "no-cache" in directives:
        return DEFAULT_CACHE_SECONDS

    for name in ("s-maxage", "max-age"):
        value = directives.get(name)
        if value is not None and value.isdigit():
            return max(MIN_CACHE_SECONDS, min(int(value), MAX_CACHE_SECONDS))

    return DEFAULT_CACHE_SECONDS


def fetch_metadata_document(
    url: str, *, transport: httpx.BaseTransport | None = None
) -> tuple[dict[str, Any], int]:
    """GET a metadata document with the SSRF guard on. Returns (document, ttl seconds).

    `transport` exists so tests can hand in an `httpx.MockTransport` — the
    request is otherwise built exactly as it would be in production.
    """
    split = urlsplit(url)
    host = split.hostname or ""
    port = split.port or 443

    address = resolve_public_address(host=host, port=port)
    # Connect to the address we just checked, not to the hostname again — a DNS
    # answer that changes between check and connect can't redirect us. The
    # hostname still goes out as the Host header and the TLS server name, so
    # the certificate is verified against the real host.
    pinned_host = f"[{address}]" if ":" in address else address
    pinned_url = split._replace(netloc=f"{pinned_host}:{port}").geturl()
    headers = {
        "Host": split.netloc,
        "Accept": "application/json",
        "User-Agent": _USER_AGENT,
    }

    started = time.monotonic()
    try:
        with (
            httpx.Client(
                transport=transport,
                follow_redirects=False,
                timeout=httpx.Timeout(FETCH_TIMEOUT_SECONDS),
            ) as client,
            client.stream(
                "GET",
                pinned_url,
                headers=headers,
                extensions={"sni_hostname": host},
            ) as response,
        ):
            if response.status_code != 200:
                raise ClientMetadataError(
                    f"Metadata document responded with status {response.status_code}"
                )
            content_type = (
                response.headers.get("content-type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )
            if content_type != "application/json" and not content_type.endswith(
                "+json"
            ):
                raise ClientMetadataError("Metadata document is not JSON")
            declared_length = response.headers.get("content-length", "")
            if declared_length.isdigit() and int(declared_length) > MAX_DOCUMENT_BYTES:
                raise ClientMetadataError("Metadata document is too large")

            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_DOCUMENT_BYTES:
                    raise ClientMetadataError("Metadata document is too large")
                if time.monotonic() - started > FETCH_TIMEOUT_SECONDS:
                    raise ClientMetadataError("Metadata document fetch timed out")
            cache_control = response.headers.get("cache-control", "")
    except httpx.TimeoutException:
        raise ClientMetadataError("Metadata document fetch timed out") from None
    except httpx.HTTPError as exc:
        raise ClientMetadataError(
            f"Could not fetch metadata document ({type(exc).__name__})"
        ) from None

    try:
        document = json.loads(bytes(body))
    except ValueError:
        raise ClientMetadataError("Metadata document is not valid JSON") from None
    if not isinstance(document, dict):
        raise ClientMetadataError("Metadata document must be a JSON object")

    return document, cache_ttl_seconds(cache_control)


def validate_metadata_document(*, url: str, document: dict[str, Any]) -> ClientMetadata:
    """Check a fetched document and pull out what we register.

    The rules are the draft's plus MCP's: the document must claim this exact
    URL, name itself, list HTTPS-or-loopback redirect URIs, and be a public
    client. Anything a private-key or shared-secret client would carry is
    rejected — those aren't supported (yet).
    """
    if document.get("client_id") != url:
        raise ClientMetadataError(
            "Metadata document's client_id does not match its URL"
        )

    if any(key.startswith("client_secret") for key in document):
        raise ClientMetadataError("Metadata document must not contain a client secret")

    name = document.get("client_name")
    if not isinstance(name, str) or not name.strip():
        raise ClientMetadataError("Metadata document must have a client_name")

    redirect_uris = document.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not redirect_uris:
        raise ClientMetadataError("Metadata document must list redirect_uris")
    if not all(
        isinstance(u, str) and _is_allowed_redirect_uri(u) for u in redirect_uris
    ):
        raise ClientMetadataError("redirect_uris must be HTTPS or loopback")
    if len(" ".join(redirect_uris)) > 2000:
        raise ClientMetadataError("redirect_uris are too long")

    auth_method = document.get("token_endpoint_auth_method", "none")
    if auth_method != "none":
        raise ClientMetadataError(
            f"token_endpoint_auth_method {auth_method!r} is not supported (only 'none')"
        )

    grant_types = document.get("grant_types")
    if grant_types is not None and (
        not isinstance(grant_types, list) or "authorization_code" not in grant_types
    ):
        raise ClientMetadataError("grant_types must include authorization_code")

    response_types = document.get("response_types")
    if response_types is not None and (
        not isinstance(response_types, list) or "code" not in response_types
    ):
        raise ClientMetadataError("response_types must include code")

    return ClientMetadata(name=name.strip()[:255], redirect_uris=redirect_uris)


def resolve_client_metadata(client_id: str) -> OAuthApplication:
    """The one entry point: a URL client_id in, a current `OAuthApplication` out.

    Uses the stored row while it's fresh, refetches when it has expired, and
    serves the stored row through a failed refetch for a grace period. Raises
    `ClientMetadataError` when there's nothing usable.
    """
    url = validate_client_id_url(client_id)
    host = urlsplit(url).hostname or ""
    allowed_hosts = settings.OAUTH_SERVER_CLIENT_ID_METADATA_ALLOWED_HOSTS
    if allowed_hosts is not None and host not in allowed_hosts:
        raise ClientMetadataError(f"{host} is not an allowed client metadata host")

    try:
        application = OAuthApplication.query.get(client_id=url)
    except OAuthApplication.DoesNotExist:
        application = None

    now = timezone.now()
    if (
        application is not None
        and application.metadata_expires_at is not None
        and application.metadata_expires_at > now
    ):
        return application

    try:
        document, ttl = fetch_metadata_document(url)
        metadata = validate_metadata_document(url=url, document=document)
    except ClientMetadataError as exc:
        if (
            application is not None
            and application.metadata_fetched_at is not None
            and now - application.metadata_fetched_at < STALE_GRACE_PERIOD
        ):
            logger.warning(
                "Client metadata refetch failed, serving the cached document",
                extra={"client_id": url, "reason": str(exc)},
            )
            return application
        logger.warning(
            "Client metadata rejected",
            extra={"client_id": url, "reason": str(exc)},
        )
        raise

    fields = {
        "name": metadata.name,
        "redirect_uris": " ".join(metadata.redirect_uris),
        "metadata_fetched_at": now,
        "metadata_expires_at": now + timedelta(seconds=ttl),
    }

    if application is None:
        # Two first-time authorizations for the same URL can race here; the
        # unique constraint on client_id makes the loser get the winner's row.
        application, created = OAuthApplication.query.get_or_create(
            client_id=url, defaults=fields
        )
        if created:
            logger.info("Client metadata registered", extra={"client_id": url})
            return application

    if application.redirect_uris != fields["redirect_uris"]:
        logger.info(
            "Client metadata redirect_uris changed",
            extra={"client_id": url, "redirect_uris": fields["redirect_uris"]},
        )
    for field, value in fields.items():
        setattr(application, field, value)
    application.update(fields=list(fields))
    return application


def is_loopback_only(application: OAuthApplication) -> bool:
    """Whether every redirect URI points at the user's own machine.

    MCP asks the consent screen to warn in that case: nothing about a metadata
    document (or a dynamic registration) proves *which* local program is asking.
    """
    return all(
        urlsplit(uri).hostname in _LOOPBACK_HOSTS
        for uri in application.get_redirect_uris()
    )
