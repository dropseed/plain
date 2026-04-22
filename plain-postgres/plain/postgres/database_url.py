from __future__ import annotations

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
from typing import Any, TypedDict

SCHEMES = {"postgres", "postgresql", "pgsql"}


class DatabaseConfig(TypedDict, total=False):
    HOST: str
    DATABASE: str  # Required (validated in _configure_settings)
    OPTIONS: dict[str, Any]
    PASSWORD: str
    PORT: int | None
    USER: str


# Register database schemes in URLs.
for scheme in SCHEMES:
    urlparse.uses_netloc.append(scheme)


def parse_database_url(url: str) -> DatabaseConfig:
    """Parse a database URL into a fully-populated `DatabaseConfig`.

    All keys are present; empty values are `""` (strings), `None` (PORT),
    or `{}` (OPTIONS) — callers can index without `.get(...)` defaults.
    """
    spliturl = urlparse.urlsplit(url)

    if spliturl.scheme not in SCHEMES:
        raise ValueError(
            f"No support for '{spliturl.scheme}'. We support: {', '.join(sorted(SCHEMES))}"
        )

    path = spliturl.path[1:]
    query = urlparse.parse_qs(spliturl.query)

    # Handle percent-encoded hostnames (e.g. socket paths).
    hostname = spliturl.hostname or ""
    if "%" in hostname:
        # Use netloc to avoid lowercased paths, strip credentials if present.
        hostname = spliturl.netloc
        if "@" in hostname:
            hostname = hostname.rsplit("@", 1)[1]
        hostname = urlparse.unquote(hostname)

    return {
        "DATABASE": urlparse.unquote(path or ""),
        "USER": urlparse.unquote(spliturl.username or ""),
        "PASSWORD": urlparse.unquote(spliturl.password or ""),
        "HOST": hostname,
        "PORT": spliturl.port,
        "OPTIONS": {key: values[-1] for key, values in query.items()},
    }


_CLI_FLAGS: list[tuple[str, str]] = [("USER", "-U"), ("HOST", "-h"), ("PORT", "-p")]
_CLI_OPTION_ENV_VARS: dict[str, str] = {
    "passfile": "PGPASSFILE",
    "sslmode": "PGSSLMODE",
    "sslrootcert": "PGSSLROOTCERT",
    "sslcert": "PGSSLCERT",
    "sslkey": "PGSSLKEY",
}


def postgres_cli_args(config: DatabaseConfig) -> list[str]:
    """Build connection flags for libpq-based tools (psql, pg_dump, pg_restore)."""
    args: list[str] = []
    for key, flag in _CLI_FLAGS:
        if value := config.get(key):
            args += [flag, str(value)]
    return args


def postgres_cli_env(config: DatabaseConfig) -> dict[str, str]:
    """Build env vars for libpq-based tools (psql, pg_dump, pg_restore)."""
    env: dict[str, str] = {}
    if password := config.get("PASSWORD"):
        env["PGPASSWORD"] = str(password)
    options = config.get("OPTIONS", {})
    for option_key, env_var in _CLI_OPTION_ENV_VARS.items():
        if value := options.get(option_key):
            env[env_var] = str(value)
    return env


def build_database_url(config: DatabaseConfig) -> str:
    """Build a database URL from a configuration dictionary."""
    options = config.get("OPTIONS", {})
    query = urlparse.urlencode(list(options.items()))

    user = urlparse.quote(str(config.get("USER", "")))
    password = urlparse.quote(str(config.get("PASSWORD", "")))
    host = config.get("HOST", "")
    port = config.get("PORT")
    name = urlparse.quote(str(config.get("DATABASE", "")))

    netloc = ""
    if user or password:
        netloc += user
        if password:
            netloc += f":{password}"
        netloc += "@"
    netloc += host
    if port:
        netloc += f":{port}"

    return urlparse.urlunsplit(("postgresql", netloc, f"/{name}", query, ""))


def replace_database_name(url: str, name: str) -> str:
    """Return the URL with the database name (path segment) replaced.

    Preserves scheme, netloc, query string, and fragment exactly — only the
    path changes. Avoids the round-trip through parse/build, which normalizes
    the scheme and collapses duplicate query keys.
    """
    spliturl = urlparse.urlsplit(url)
    return urlparse.urlunsplit(spliturl._replace(path=f"/{urlparse.quote(name)}"))
