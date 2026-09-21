"""The providers chart card counts connections per provider.

The card's query is written with `sql()`; this pins that it returns what the
grouped aggregate it replaced returned.
"""

from __future__ import annotations

from app.users.models import User
from plain.oauth.admin import ProvidersChartCard
from plain.oauth.models import OAuthConnection
from plain.postgres.aggregates import Count


def _connect(email: str, provider_key: str) -> None:
    user = User.query.create(email=email, username=email.split("@")[0])
    OAuthConnection.query.create(
        user=user,
        provider_key=provider_key,
        provider_user_id=email,
        access_token="tok",
    )


def test_provider_chart_matches_the_grouped_aggregate(db):
    _connect("a@example.com", "github")
    _connect("b@example.com", "github")
    _connect("c@example.com", "bitbucket")

    expected = {
        row["provider_key"]: row["count"]
        for row in OAuthConnection.query.all()
        .values("provider_key")
        .annotate(count=Count("id"))
    }

    data = ProvidersChartCard().get_chart_data()

    labels = data["data"]["labels"]
    counts = data["data"]["datasets"][0]["data"]
    assert dict(zip(labels, counts)) == expected
    assert expected == {"bitbucket": 1, "github": 2}
