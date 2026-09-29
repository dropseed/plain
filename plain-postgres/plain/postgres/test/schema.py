"""
What decides a test database's schema, as one digest.

A run's test database is built from nothing: created, migrated, converged.
Every run of the same code builds the same one, so the first run keeps its
build as a template for the rest to clone (`database.py`), and one template
is told from another by what it was built from: the migration files, and
the models as convergence reads them. A change to either is a different
digest, and a different template.
"""

import hashlib
import sys
from dataclasses import dataclass

from plain.postgres import __version__ as plain_postgres_version
from plain.postgres.migrations.loader import MigrationLoader
from plain.postgres.migrations.migration import Migration
from plain.postgres.migrations.serializer import serializer_factory
from plain.postgres.migrations.state import ModelState
from plain.postgres.options import CONVERGENCE_OPTIONS
from plain.postgres.registry import models_registry


@dataclass(frozen=True)
class SchemaDigest:
    """What a test database's schema is built from, as one hash."""

    hash: str  # sha256, in hex
    migrations: int  # how many migration files go into it


def describe_schema() -> SchemaDigest:
    """
    A digest of everything a test database is built from: the version of
    plain.postgres that builds it, every migration file's contents, and
    every model's fields and options, serialized the way a migration file
    would write them, so that a callable default is named and not printed
    with its address.
    """
    digest = hashlib.sha256()
    digest.update(f"plain.postgres {plain_postgres_version}\n".encode())

    loader = MigrationLoader(None, ignore_no_migrations=True)
    assert loader.disk_migrations is not None
    for (label, name), migration in sorted(loader.disk_migrations.items()):
        digest.update(f"migration {label} {name}\n".encode())
        digest.update(_source_of(migration))

    models = sorted(
        models_registry.get_models(), key=lambda model: model.model_options.label_lower
    )
    for model in models:
        state = ModelState.from_model(model)
        digest.update(f"model {state.package_label} {state.name}\n".encode())
        for field_name, field in state.fields.items():
            digest.update(f"  {field_name} = {_serialized(field)}\n".encode())
        for option, value in sorted(state.options.items()):
            digest.update(f"  {option} = {_serialized(value)}\n".encode())
        # What migrations leave out and convergence reads from the model:
        # indexes, constraints, storage parameters.
        for option in CONVERGENCE_OPTIONS:
            value = getattr(model.model_options, option)
            digest.update(f"  {option} = {_serialized(value)}\n".encode())

    return SchemaDigest(hash=digest.hexdigest(), migrations=len(loader.disk_migrations))


def _source_of(migration: Migration) -> bytes:
    module = sys.modules[type(migration).__module__]
    assert module.__file__ is not None
    with open(module.__file__, "rb") as file:
        return file.read()


def _serialized(value: object) -> str:
    try:
        text, _ = serializer_factory(value).serialize()
    except ValueError:
        # Not something a migration file could hold. Its repr tells one
        # value from another; when it holds an address, the digest is
        # different in every process, and a template is built every run
        # and never wrong.
        text = repr(value)
    return text
