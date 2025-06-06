import plain.models.database_url as database_url


def roundtrip(url: str):
    config = database_url.parse(url)
    rebuilt = database_url.build_database_url(config)
    assert database_url.parse(rebuilt) == config


def test_postgres_roundtrip():
    roundtrip("postgres://user:pass@localhost:5432/dbname?sslmode=require")


def test_mysql_roundtrip():
    roundtrip("mysql://user:pass@localhost/dbname?ssl-ca=/path/ca.pem")


def test_sqlite_memory_roundtrip():
    roundtrip("sqlite://:memory:")


def test_sqlite_file_roundtrip():
    roundtrip("sqlite:///mydb.sqlite3")
