# Copyright (c) Kenneth Reitz & individual contributors
# All rights reserved.

# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:

#     1. Redistributions of source code must retain the above copyright notice,
#        this list of conditions and the following disclaimer.

#     2. Redistributions in binary form must reproduce the above copyright
#        notice, this list of conditions and the following disclaimer in the
#        documentation and/or other materials provided with the distribution.

#     3. Neither the name of Plain nor the names of its contributors may be used
#        to endorse or promote products derived from this software without
#        specific prior written permission.

# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
# ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
import urllib.parse as urlparse
from typing import Any

from .connections import DatabaseConfig

SCHEMES = {
    "postgres": "plain.models.backends.postgresql",
    "postgresql": "plain.models.backends.postgresql",
    "pgsql": "plain.models.backends.postgresql",
    "mysql": "plain.models.backends.mysql",
    "mysql2": "plain.models.backends.mysql",
    "sqlite": "plain.models.backends.sqlite3",
}

# Register database schemes in URLs.
for key in SCHEMES.keys():
    urlparse.uses_netloc.append(key)


def parse_database_url(
    url: str,
    engine: str | None = None,
    conn_max_age: int | None = 0,
    conn_health_checks: bool = False,
) -> DatabaseConfig:
    """Parses a database URL."""
    if url == "sqlite://:memory:":
        # this is a special case, because if we pass this URL into
        # urlparse, urlparse will choke trying to interpret "memory"
        # as a port number
        return {"ENGINE": SCHEMES["sqlite"], "NAME": ":memory:"}
        # note: no other settings are required for sqlite

    # otherwise parse the url as normal
    parsed_config: DatabaseConfig = {}

    spliturl = urlparse.urlsplit(url)

    # Split query strings from path.
    path = spliturl.path[1:]
    query = urlparse.parse_qs(spliturl.query)

    # If we are using sqlite and we have no path, then assume we
    # want an in-memory database (this is the behaviour of sqlalchemy)
    if spliturl.scheme == "sqlite" and path == "":
        path = ":memory:"

    # Handle postgres percent-encoded paths.
    hostname = spliturl.hostname or ""
    if "%" in hostname:
        # Switch to url.netloc to avoid lower cased paths
        hostname = spliturl.netloc
        if "@" in hostname:
            hostname = hostname.rsplit("@", 1)[1]
        # Use URL Parse library to decode % encodes
        hostname = urlparse.unquote(hostname)

    # Lookup specified engine.
    if engine is None:
        engine = SCHEMES.get(spliturl.scheme)
        if engine is None:
            raise ValueError(
                "No support for '{}'. We support: {}".format(
                    spliturl.scheme, ", ".join(sorted(SCHEMES.keys()))
                )
            )

    port = spliturl.port

    # Update with environment configuration.
    parsed_config.update(
        {
            "NAME": urlparse.unquote(path or ""),
            "USER": urlparse.unquote(spliturl.username or ""),
            "PASSWORD": urlparse.unquote(spliturl.password or ""),
            "HOST": hostname,
            "PORT": port or "",
            "CONN_MAX_AGE": conn_max_age,
            "CONN_HEALTH_CHECKS": conn_health_checks,
            "ENGINE": engine,
        }
    )

    # Pass the query string into OPTIONS.
    options: dict[str, Any] = {}
    for key, values in query.items():
        if spliturl.scheme == "mysql" and key == "ssl-ca":
            options["ssl"] = {"ca": values[-1]}
            continue

        options[key] = values[-1]

    if options:
        parsed_config["OPTIONS"] = options

    return parsed_config


def build_database_url(config: dict) -> str:
    """Build a database URL from a configuration dictionary."""
    engine = config.get("ENGINE")
    if not engine:
        raise ValueError("ENGINE is required to build a database URL")

    reverse_schemes: dict[str, str] = {}
    for scheme, eng in SCHEMES.items():
        reverse_schemes.setdefault(eng, scheme)

    scheme = reverse_schemes.get(engine)
    if scheme is None:
        raise ValueError(
            f"No scheme known for engine '{engine}'. We support: {', '.join(sorted(SCHEMES.values()))}"
        )

    options = config.get("OPTIONS") or {}
    query_parts: list[tuple[str, Any]] = []
    for key, value in options.items():
        if scheme == "mysql" and key == "ssl" and isinstance(value, dict):
            ca = value.get("ca")
            if ca:
                query_parts.append(("ssl-ca", ca))
            continue

        query_parts.append((key, value))

    query = urlparse.urlencode(query_parts)

    if scheme == "sqlite":
        name = config.get("NAME", "")
        if name == ":memory:":
            url = "sqlite://:memory:"
        else:
            url = f"sqlite:///{urlparse.quote(name, safe='/')}"

        if query:
            url += f"?{query}"

        return url

    user = urlparse.quote(str(config.get("USER", "")))
    password = urlparse.quote(str(config.get("PASSWORD", "")))
    host = config.get("HOST", "")
    port = config.get("PORT", "")
    name = urlparse.quote(str(config.get("NAME", "")))

    netloc = ""
    if user or password:
        netloc += user
        if password:
            netloc += f":{password}"
        netloc += "@"
    netloc += host
    if port:
        netloc += f":{port}"

    path = f"/{name}"
    url = urlparse.urlunsplit((scheme, netloc, path, query, ""))
    return url
