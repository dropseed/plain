# Database & Models

## Creating Migrations

```
uv run plain makemigrations
```

Only write migrations by hand if they are custom data migrations.

## Running Migrations

```
uv run plain migrate --backup
```

The `--backup` flag creates a database backup before applying migrations.

Run `uv run plain docs models --source` for detailed model and migration documentation.
