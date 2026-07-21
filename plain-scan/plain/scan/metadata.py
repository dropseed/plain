from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx


@dataclass
class CookieMetadata:
    """Metadata for a single cookie."""

    name: str
    value: str | None
    domain: str | None
    path: str
    secure: bool
    httponly: bool
    samesite: str | None
    expires: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> CookieMetadata:
        """Reconstruct CookieMetadata from dictionary."""
        return cls(
            name=data["name"],
            value=data["value"],
            domain=data["domain"],
            path=data["path"],
            secure=data["secure"],
            httponly=data["httponly"],
            samesite=data["samesite"],
            expires=data.get("expires"),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, str | None | bool | int] = {
            "name": self.name,
            "value": self.value,
            "domain": self.domain,
            "path": self.path,
            "secure": self.secure,
            "httponly": self.httponly,
            "samesite": self.samesite,
        }
        if self.expires is not None:
            result["expires"] = self.expires
        return result


@dataclass
class ResponseMetadata:
    """Metadata for a single HTTP response."""

    url: str
    status_code: int
    headers: dict[str, str]
    cookies: list[CookieMetadata] = field(default_factory=list)

    @classmethod
    def from_response(cls, response: httpx.Response) -> ResponseMetadata:
        """Build ResponseMetadata from an httpx.Response object."""

        cookies = []

        # httpx exposes parsed cookies as an httpx.Cookies wrapper; the underlying
        # `.jar` yields http.cookiejar.Cookie objects with the attributes we need.
        for cookie in response.cookies.jar:
            # Non-standard attributes (SameSite, HttpOnly) live in the private
            # `_rest` dict; SameSite casing varies by server, so match case-insensitively.
            rest: dict[str, str | None] = getattr(cookie, "_rest", {})
            samesite = None
            for key in rest:
                if key.lower() == "samesite":
                    samesite = rest[key]
                    break

            cookies.append(
                CookieMetadata(
                    name=cookie.name,
                    value=cookie.value,
                    domain=cookie.domain,
                    path=cookie.path,
                    secure=cookie.secure,
                    httponly="HttpOnly" in rest,
                    samesite=samesite,
                    expires=cookie.expires if cookie.expires else None,
                )
            )

        return cls(
            url=str(response.url),
            status_code=response.status_code,
            headers=dict(response.headers),
            cookies=cookies,
        )

    @classmethod
    def from_dict(cls, data: dict) -> ResponseMetadata:
        """Reconstruct ResponseMetadata from dictionary."""
        cookies = [CookieMetadata.from_dict(c) for c in data.get("cookies", [])]
        return cls(
            url=data["url"],
            status_code=data["status_code"],
            headers=data["headers"],
            cookies=cookies,
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, str | int | dict[str, str] | list[dict]] = {
            "url": self.url,
            "status_code": self.status_code,
            "headers": self.headers,
        }
        if self.cookies:
            result["cookies"] = [cookie.to_dict() for cookie in self.cookies]
        return result


@dataclass
class ScanMetadata:
    """Metadata for the complete scan, including all responses in the chain."""

    timestamp: str  # ISO 8601 format timestamp of when scan was run
    responses: list[ResponseMetadata] = field(default_factory=list)

    @classmethod
    def from_response(cls, response: httpx.Response | None) -> ScanMetadata:
        """Build ScanMetadata from an httpx.Response object (including redirects)."""

        timestamp = datetime.now(UTC).isoformat()

        if response is None:
            return cls(responses=[], timestamp=timestamp)

        # Build responses array with all responses in the chain
        responses = []

        # Add all redirect responses from history
        for redirect_response in response.history:
            responses.append(ResponseMetadata.from_response(redirect_response))

        # Add the final response
        responses.append(ResponseMetadata.from_response(response))

        return cls(timestamp=timestamp, responses=responses)

    @classmethod
    def from_dict(cls, data: dict) -> ScanMetadata:
        """Reconstruct ScanMetadata from dictionary."""
        responses = [ResponseMetadata.from_dict(r) for r in data.get("responses", [])]
        return cls(
            timestamp=data["timestamp"],
            responses=responses,
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp,
            "responses": [response.to_dict() for response in self.responses],
        }
