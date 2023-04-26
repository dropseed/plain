# forge-db

Use Postgres for local Django development via Docker.


## Installation

First, install `forge-db` from [PyPI](https://pypi.org/project/forge-db/):

```sh
pip install forge-db
```

Now you will have access to the `db` command:

```sh
forge db
```

You will need to have a `DATABASE_URL` environment variable,
which is where the database name, username, password, and port are parsed from:

```sh
# .env
DATABASE_URL=postgres://postgres:postgres@localhost:54321/postgres
```

You can use a `POSTGRES_VERSION` environment variable to override the default Postgres version (13):

```sh
# .env
POSTGRES_VERSION=12
```

In most cases you will want to use [`dj_database_url`](https://github.com/kennethreitz/dj-database-url) in your `settings.py` to easily set the same settings (works in most deployment environments too):

```python
# settings.py
import dj_databse_url

DATABASES = {
    "default": dj_database_url.parse(
        environ["DATABASE_URL"], conn_max_age=environ.get("DATABASE_CONN_MAX_AGE", 600)
    )
}
```

You will also notice a new `.forge` directory in your project root.
This contains your local database files and should be added to `.gitignore`.

## Usage

If you use [`forge-work`](https://github.com/forgepackages/forge-work),
then most of the time you won't need to interact with `forge-db` directly.
But it has a few commands that come in handy.

- `forge db start` - starts a new database container and runs it in the background (use `--logs` to foreground it or connect to the logs)
- `forge db stop` - stop the database container
- `forge db reset` - drops and creates a new database
- `forge db pull` - pulls the latest database backup from Heroku and imports it into the local database

In the end, the database container is like any other Docker container.
You can use the standard Docker commands and tools to interact with it when needed.

## Snapshots

The `forge db snapshot` command manages local copies of your development database.
This is useful for testing migrations or switching between git branches that have different db states.

Snapshots are simply additional Postgres databases that are created and dropped as needed (`createdb {snapshot_name} -T postgres`).
