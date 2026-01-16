from plain.models import database_url


def roundtrip(url: str):
    config = database_url.parse_database_url(url)
    rebuilt = database_url.build_database_url(config)
    assert database_url.parse_database_url(rebuilt) == config


def test_postgres_roundtrip():
    roundtrip("postgres://user:pass@localhost:5432/dbname?sslmode=require")


def test_postgresql_roundtrip():
    roundtrip("postgresql://user:pass@localhost:5432/dbname")


def test_pgsql_roundtrip():
    roundtrip("pgsql://user:pass@localhost:5432/dbname")
