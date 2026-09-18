"""Which checkout am I, and where does its state live?

The answers here decide which database a command talks to and which dev server
a checkout owns, so getting them wrong is the class of bug that runs against
somebody else's data without saying anything.
"""

from __future__ import annotations

from dev_test_helpers import sandbox
from plain.dev.state import checkout_state_path, find_project_root, sanitize


def test_sanitize_makes_legal_identifiers():
    assert sanitize("My-App") == "my_app"
    assert sanitize("app.name") == "app_name"
    assert sanitize("--leading--") == "leading"


# -- finding the project ---------------------------------------------------


def test_project_root_is_found_from_the_app_directory():
    """The app is often a level below the project, and every caller must agree.

    `setup()` walks up from the working directory; `plain db` walks up from the
    app; the dev supervisors walk up from the working directory too. If those
    disagree the CLI manages a different database than the one the app was
    configured with, and the dev server claims a different checkout's slot.
    """
    with sandbox() as box:
        (box.tmp_path / "pyproject.toml").touch()
        app = box.tmp_path / "backend" / "app"
        app.mkdir(parents=True)

        assert find_project_root(app) == box.tmp_path
        assert find_project_root(box.tmp_path) == box.tmp_path


def test_project_root_falls_back_to_where_it_started():
    with sandbox() as box:
        assert find_project_root(box.tmp_path) == box.tmp_path


# -- where a checkout's state lives ----------------------------------------


def test_state_lives_outside_the_checkout():
    """A working tree is what gets copied, mounted, and symlinked, so the facts
    that decide which database and which dev server are ours aren't kept in one."""
    with sandbox() as box:
        checkout = box.tmp_path / "checkout"
        checkout.mkdir()

        state = checkout_state_path(checkout)

        assert checkout not in state.parents
        assert box.cache_path in state.parents


def test_two_checkouts_get_different_state():
    with sandbox() as box:
        main = box.tmp_path / "main"
        main.mkdir()
        worktree = box.tmp_path / "worktree"
        worktree.mkdir()

        assert checkout_state_path(main) != checkout_state_path(worktree)


def test_state_path_is_stable_for_one_checkout():
    """Spelled differently, resolved the same — otherwise a command run through
    a symlinked path would look like a different checkout."""
    with sandbox() as box:
        checkout = box.tmp_path / "checkout"
        checkout.mkdir()
        link = box.tmp_path / "link"
        link.symlink_to(checkout)

        assert checkout_state_path(link) == checkout_state_path(checkout)
