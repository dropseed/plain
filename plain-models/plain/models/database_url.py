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
import logging
import os
import urllib.parse as urlparse
from typing import Any, TypedDict

DEFAULT_ENV = "DATABASE_URL"

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


# From https://docs.djangoproject.com/en/4.0/ref/settings/#databases
class DBConfig(TypedDict, total=False):
    AUTOCOMMIT: bool
    CONN_MAX_AGE: int | None
    CONN_HEALTH_CHECKS: bool
    DISABLE_SERVER_SIDE_CURSORS: bool
    ENGINE: str
    HOST: str
    NAME: str
    OPTIONS: dict[str, Any] | None
    PASSWORD: str
    PORT: str | int
    TEST: dict[str, Any]
    TIME_ZONE: str
    USER: str


def config(
    env: str = DEFAULT_ENV,
    default: str | None = None,
    engine: str | None = None,
    conn_max_age: int | None = 0,
    conn_health_checks: bool = False,
    ssl_require: bool = False,
    test_options: dict | None = None,
) -> DBConfig:
    """Returns configured DATABASE dictionary from DATABASE_URL."""
    s = os.environ.get(env, default)

    if s is None:
        logging.warning(
            "No %s environment variable set, and so no databases setup" % env
        )

    if s:
        return parse(
            s, engine, conn_max_age, conn_health_checks, ssl_require, test_options
        )

    return {}


def parse(
    url: str,
    engine: str | None = None,
    conn_max_age: int | None = 0,
    conn_health_checks: bool = False,
    ssl_require: bool = False,
    test_options: dict | None = None,
) -> DBConfig:
    """Parses a database URL."""
    if url == "sqlite://:memory:":
        # this is a special case, because if we pass this URL into
        # urlparse, urlparse will choke trying to interpret "memory"
        # as a port number
        return {"ENGINE": SCHEMES["sqlite"], "NAME": ":memory:"}
        # note: no other settings are required for sqlite

    # otherwise parse the url as normal
    parsed_config: DBConfig = {}

    if test_options is None:
        test_options = {}

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
    if test_options:
        parsed_config.update(
            {
                "TEST": test_options,
            }
        )

    # Pass the query string into OPTIONS.
    options: dict[str, Any] = {}
    for key, values in query.items():
        if spliturl.scheme == "mysql" and key == "ssl-ca":
            options["ssl"] = {"ca": values[-1]}
            continue

        options[key] = values[-1]

    if ssl_require:
        options["sslmode"] = "require"

    # Support for Postgres Schema URLs
    if "currentSchema" in options and engine in (
        "plain.models.backends.postgresql_psycopg2",
        "plain.models.backends.postgresql",
    ):
        options["options"] = "-c search_path={}".format(options.pop("currentSchema"))

    if options:
        parsed_config["OPTIONS"] = options

    return parsed_config
