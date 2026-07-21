"""How a checkout decides which database is its own.

All of this is derived rather than stored, so it's pure and testable without a
server anywhere in sight — which is also why it's worth pinning down: the
derivation *is* the contract that keeps two worktrees off each other's data.
"""

from __future__ import annotations

from plain.dev.postgres.identity import (
    MAX_NAME_LENGTH,
    PostgresConfig,
    clear_pointer,
    database_name_for_checkout,
    read_pointer,
    resolve_database_name,
    sanitize,
    truncate_identifier,
    write_pointer,
)


def test_sanitize_makes_legal_identifiers():
    assert sanitize("My-App") == "my_app"
    assert sanitize("app.name") == "app_name"
    assert sanitize("--leading--") == "leading"


def test_truncate_identifier_leaves_short_names_alone():
    assert truncate_identifier("short") == "short"


def test_truncate_identifier_hashes_long_names():
    name = "a" * 100
    result = truncate_identifier(name)

    assert len(result) <= MAX_NAME_LENGTH
    assert result.startswith("a")
    # Different long names must not collide after truncation.
    assert result != truncate_identifier("a" * 99 + "b")


def test_main_checkout_uses_the_project_name(tmp_path):
    checkout = tmp_path / "myapp"
    checkout.mkdir()

    assert database_name_for_checkout("myapp", checkout) == "myapp"


def test_worktree_is_namespaced_under_the_project(tmp_path):
    checkout = tmp_path / "feature-x"
    checkout.mkdir()

    assert database_name_for_checkout("myapp", checkout) == "myapp_feature_x"


def test_worktree_named_after_the_project_does_not_stutter(tmp_path):
    """`git worktree add ../myapp-feature` shouldn't yield myapp_myapp_feature."""
    checkout = tmp_path / "myapp-feature"
    checkout.mkdir()

    assert database_name_for_checkout("myapp", checkout) == "myapp_feature"


def test_two_worktrees_get_different_databases(tmp_path):
    """The property the whole feature rests on."""
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()

    assert database_name_for_checkout("myapp", first) != database_name_for_checkout(
        "myapp", second
    )


def test_pointer_round_trip(tmp_path):
    assert read_pointer(tmp_path) is None

    write_pointer(tmp_path, "some_other_db")
    assert read_pointer(tmp_path) == "some_other_db"

    clear_pointer(tmp_path)
    assert read_pointer(tmp_path) is None


def test_clear_pointer_is_idempotent(tmp_path):
    clear_pointer(tmp_path)


def test_pointer_overrides_the_derived_name(tmp_path):
    project = tmp_path / "myapp"
    project.mkdir()
    (project / "pyproject.toml").write_text('[project]\nname = "myapp"\n')

    assert resolve_database_name(project) == "myapp"

    write_pointer(project, "borrowed")
    assert resolve_database_name(project) == "borrowed"


def test_empty_pointer_file_is_ignored(tmp_path):
    """A blank file shouldn't resolve to a database named ''."""
    project = tmp_path / "myapp"
    project.mkdir()
    (project / "pyproject.toml").write_text('[project]\nname = "myapp"\n')
    write_pointer(project, "   ")

    assert resolve_database_name(project) == "myapp"


def test_config_defaults_when_unconfigured(tmp_path):
    config = PostgresConfig.load(tmp_path)

    assert config.backend == "auto"
    assert config.image == "postgres:16"


def test_config_reads_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.plain.dev.postgres]\nbackend = "local"\nimage = "postgres:18"\n'
    )

    config = PostgresConfig.load(tmp_path)

    assert config.backend == "local"
    assert config.image == "postgres:18"


def test_config_image_can_be_any_image(tmp_path):
    """Extensions ship as their own images, so this can't be just a version."""
    (tmp_path / "pyproject.toml").write_text(
        '[tool.plain.dev.postgres]\nimage = "pgvector/pgvector:pg16"\n'
    )

    assert PostgresConfig.load(tmp_path).image == "pgvector/pgvector:pg16"


def test_nested_app_directories_do_not_collide_across_worktrees(tmp_path):
    """An app often isn't the checkout root — `example/`, `src/`, `backend/`.

    Those directories are named identically in every worktree, so deriving the
    database from the app directory would hand two checkouts the same database.
    The checkout identity has to come from the worktree, not the app folder.
    """
    import os
    import subprocess

    # Git sets GIT_DIR for hooks, and this suite may run from one. Scrub it so
    # the repository we build here is the one git operates on.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}

    main = tmp_path / "myrepo"
    (main / "backend").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(main)], check=True, env=env)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-qm",
            "x",
            "--allow-empty",
        ],
        cwd=main,
        check=True,
        env=env,
    )

    worktree = tmp_path / "myrepo-feature"
    subprocess.run(
        ["git", "worktree", "add", "-q", str(worktree), "-b", "feature"],
        cwd=main,
        check=True,
        env=env,
    )
    (worktree / "backend").mkdir(exist_ok=True)

    main_db = database_name_for_checkout("backend", main / "backend")
    worktree_db = database_name_for_checkout("backend", worktree / "backend")

    assert main_db == "backend"
    assert main_db != worktree_db
