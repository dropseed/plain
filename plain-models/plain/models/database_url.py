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

SCHEMES = {"postgres", "postgresql", "pgsql"}

# Register database schemes in URLs.
for scheme in SCHEMES:
    urlparse.uses_netloc.append(scheme)


def parse_database_url(
    url: str,
    conn_max_age: int | None = 0,
    conn_health_checks: bool = False,
) -> DatabaseConfig:
    """Parses a database URL."""
    parsed_config: DatabaseConfig = {}

    spliturl = urlparse.urlsplit(url)

    # Validate scheme is PostgreSQL.
    if spliturl.scheme not in SCHEMES:
        raise ValueError(
            "No support for '{}'. We support: {}".format(
                spliturl.scheme, ", ".join(sorted(SCHEMES))
            )
        )

    # Split query strings from path.
    path = spliturl.path[1:]
    query = urlparse.parse_qs(spliturl.query)

    # Handle postgres percent-encoded paths.
    hostname = spliturl.hostname or ""
    if "%" in hostname:
        # Switch to url.netloc to avoid lower cased paths
        hostname = spliturl.netloc
        if "@" in hostname:
            hostname = hostname.rsplit("@", 1)[1]
        # Use URL Parse library to decode % encodes
        hostname = urlparse.unquote(hostname)

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
        }
    )

    # Pass the query string into OPTIONS.
    options: dict[str, Any] = {}
    for key, values in query.items():
        options[key] = values[-1]

    if options:
        parsed_config["OPTIONS"] = options

    return parsed_config


def build_database_url(config: DatabaseConfig) -> str:
    """Build a database URL from a configuration dictionary."""
    options = config.get("OPTIONS", {})
    query_parts: list[tuple[str, Any]] = []
    for key, value in options.items():
        query_parts.append((key, value))

    query = urlparse.urlencode(query_parts)

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
    url = urlparse.urlunsplit(("postgresql", netloc, path, query, ""))
    return str(url)
