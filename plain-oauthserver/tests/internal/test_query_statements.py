"""Statement pins for the token endpoint's two grants.

Change detector: if a grant starts issuing different SQL — an extra round
trip, a dropped `FOR UPDATE`, a lock that no longer covers the row being
spent — these fail and you decide whether it should have.

The `db` fixture already holds the test inside a transaction, so each view's
`transaction.atomic()` opens a SAVEPOINT rather than a BEGIN. In production
those atomic blocks are the outermost ones.
"""

import threading
from datetime import timedelta

from oauth_helpers import generate_pkce_pair, issue_token_pair
from plain.oauthserver.models import AuthorizationCode
from plain.postgres.db import get_connection
from plain.test import Client
from plain.utils import timezone

REDIRECT_URI = "http://localhost:3000/callback"


class StatementRecorder:
    """Records every statement executed on a connection, in order."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def __call__(self, execute, sql, params, many, context):
        self.statements.append(" ".join(str(sql).split()))
        return execute(sql, params, many, context)


def make_auth_code(application, user, code_challenge):
    return AuthorizationCode.query.create(
        application=application,
        user=user,
        redirect_uri=REDIRECT_URI,
        scope="read",
        code_challenge=code_challenge,
        expires_at=timezone.now() + timedelta(minutes=10),
    )


def post_token(payload):
    """POST the token endpoint, returning (response, statements executed)."""
    recorder = StatementRecorder()
    with get_connection().execute_wrapper(recorder):
        response = Client().post("/oauth/token", data=payload)
    return response, recorder.statements


# -- Authorization code grant --


def test_authorization_code_grant_statements(db, user, public_app) -> None:
    verifier, challenge = generate_pkce_pair()
    auth_code = make_auth_code(public_app, user, challenge)
    payload = {
        "grant_type": "authorization_code",
        "code": auth_code.code,
        "redirect_uri": REDIRECT_URI,
        "client_id": public_app.client_id,
        "code_verifier": verifier,
    }

    response, statements = post_token(payload)

    assert response.status_code == 200
    assert len(statements) == 7

    assert statements[0].startswith("SELECT ")
    assert 'FROM "plainoauthserver_oauthapplication"' in statements[0]

    assert statements[1].startswith("SAVEPOINT ")

    assert statements[2].startswith("SELECT ")
    assert 'FROM "plainoauthserver_authorizationcode"' in statements[2]
    assert statements[2].endswith("FOR UPDATE")
    # One table selected, so no `OF` clause is needed to aim the lock.
    assert " OF " not in statements[2]

    assert statements[3].startswith('UPDATE "plainoauthserver_authorizationcode"')
    assert '"used"' in statements[3]
    assert statements[4].startswith('INSERT INTO "plainoauthserver_accesstoken"')
    assert statements[5].startswith('INSERT INTO "plainoauthserver_refreshtoken"')
    assert statements[6].startswith("RELEASE SAVEPOINT ")


def test_replayed_authorization_code_statements(db, user, public_app) -> None:
    verifier, challenge = generate_pkce_pair()
    auth_code = make_auth_code(public_app, user, challenge)
    payload = {
        "grant_type": "authorization_code",
        "code": auth_code.code,
        "redirect_uri": REDIRECT_URI,
        "client_id": public_app.client_id,
        "code_verifier": verifier,
    }

    first, _ = post_token(payload)
    assert first.status_code == 200

    replay, statements = post_token(payload)

    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"
    # The replay stops at the locked read — nothing is written.
    assert len(statements) == 4
    assert statements[0].startswith("SELECT ")
    assert 'FROM "plainoauthserver_oauthapplication"' in statements[0]
    assert statements[1].startswith("SAVEPOINT ")
    assert statements[2].startswith("SELECT ")
    assert 'FROM "plainoauthserver_authorizationcode"' in statements[2]
    assert statements[2].endswith("FOR UPDATE")
    assert statements[3].startswith("RELEASE SAVEPOINT ")


# -- Refresh token grant --


def test_refresh_token_grant_statements(db, user, public_app) -> None:
    issue_token_pair(public_app, user)
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": "refresh-value",
        "client_id": public_app.client_id,
    }

    response, statements = post_token(payload)

    assert response.status_code == 200
    assert len(statements) == 8

    assert statements[0].startswith("SELECT ")
    assert 'FROM "plainoauthserver_oauthapplication"' in statements[0]

    assert statements[1].startswith("SAVEPOINT ")

    assert statements[2].startswith("SELECT ")
    assert 'FROM "plainoauthserver_refreshtoken"' in statements[2]
    # join() pulls the access token into the same locked read, and
    # with no `OF` clause the lock covers both joined rows — both of which
    # this grant revokes.
    assert 'INNER JOIN "plainoauthserver_accesstoken"' in statements[2]
    assert statements[2].endswith("FOR UPDATE")
    assert " OF " not in statements[2]

    assert statements[3].startswith('UPDATE "plainoauthserver_refreshtoken"')
    assert '"revoked"' in statements[3]
    assert statements[4].startswith('UPDATE "plainoauthserver_accesstoken"')
    assert '"revoked"' in statements[4]
    assert statements[5].startswith('INSERT INTO "plainoauthserver_accesstoken"')
    assert statements[6].startswith('INSERT INTO "plainoauthserver_refreshtoken"')
    assert statements[7].startswith("RELEASE SAVEPOINT ")


def test_replayed_refresh_token_statements(db, user, public_app) -> None:
    issue_token_pair(public_app, user)
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": "refresh-value",
        "client_id": public_app.client_id,
    }

    first, _ = post_token(payload)
    assert first.status_code == 200

    replay, statements = post_token(payload)

    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"
    # The replay stops at the locked read — nothing is written.
    assert len(statements) == 4
    assert statements[0].startswith("SELECT ")
    assert 'FROM "plainoauthserver_oauthapplication"' in statements[0]
    assert statements[1].startswith("SAVEPOINT ")
    assert statements[2].startswith("SELECT ")
    assert 'FROM "plainoauthserver_refreshtoken"' in statements[2]
    assert statements[2].endswith("FOR UPDATE")
    assert statements[3].startswith("RELEASE SAVEPOINT ")


# -- Concurrent reuse --


def race_token_requests(payload):
    """POST the same payload from two threads at once, return both statuses.

    Each thread opens its own connection against the test database — a new
    thread starts with an empty context, so it would otherwise reach for the
    runtime database instead.
    """
    config = get_connection().settings_dict
    barrier = threading.Barrier(2)
    statuses: dict[int, int] = {}

    def post(n: int) -> None:
        from plain.postgres.connection import DatabaseConnection
        from plain.postgres.db import _db_conn
        from plain.postgres.sources import DirectSource

        connection = DatabaseConnection(DirectSource(config))
        _db_conn.set(connection)
        try:
            barrier.wait(timeout=10)
            statuses[n] = Client().post("/oauth/token", data=payload).status_code
        finally:
            connection.close()

    threads = [threading.Thread(target=post, args=(n,)) for n in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive(), "a token request never finished"

    return sorted(statuses.values())


def test_concurrent_authorization_code_exchange(isolated_db) -> None:
    """`FOR UPDATE` makes the second exchange wait, then see a spent code."""
    from app.users.models import User
    from plain.oauthserver.models import OAuthApplication

    user = User.query.create(email="race-code@example.com")
    application = OAuthApplication.query.create(
        name="Race App", redirect_uris=REDIRECT_URI
    )
    verifier, challenge = generate_pkce_pair()
    auth_code = make_auth_code(application, user, challenge)

    statuses = race_token_requests(
        {
            "grant_type": "authorization_code",
            "code": auth_code.code,
            "redirect_uri": REDIRECT_URI,
            "client_id": application.client_id,
            "code_verifier": verifier,
        }
    )

    assert statuses == [200, 400]


def test_concurrent_refresh_token_use(isolated_db) -> None:
    """`FOR UPDATE` makes the second refresh wait, then see a revoked token."""
    from app.users.models import User
    from plain.oauthserver.models import OAuthApplication

    user = User.query.create(email="race-refresh@example.com")
    application = OAuthApplication.query.create(
        name="Race App", redirect_uris=REDIRECT_URI
    )
    issue_token_pair(application, user)

    statuses = race_token_requests(
        {
            "grant_type": "refresh_token",
            "refresh_token": "refresh-value",
            "client_id": application.client_id,
        }
    )

    assert statuses == [200, 400]
