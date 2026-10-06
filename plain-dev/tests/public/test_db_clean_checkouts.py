"""
The checkouts `plain db clean` knows of, and the database each is
configured to use. A database one of them uses is never dropped.

Each test builds a git repository of its own in a temporary directory.
"""

import os
import shutil
import subprocess
from pathlib import Path

from dev_test_helpers import sandbox
from plain.dev.postgres.cleaning import (
    CleanFacts,
    look_at_owner_path,
    plan_clean,
    project_checkouts,
)
from plain.dev.postgres.identity import write_pointer
from plain.dev.state import checkout_id


def git(*arguments: str, cwd: Path) -> None:
    # Git sets GIT_DIR for hooks, and this suite may run from one.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "-c",
            "commit.gpgsign=false",
            *arguments,
        ],
        cwd=cwd,
        check=True,
        env=env,
        capture_output=True,
    )


def a_repository(root: Path) -> Path:
    """A repository whose project is in `example/`, as Plain's own is. The
    project root of its main checkout."""
    main = root / "shop"
    (main / "example").mkdir(parents=True)
    (main / "example" / "pyproject.toml").write_text('[project]\nname = "example"\n')
    git("init", "-q", str(main), cwd=root)
    git("add", ".", cwd=main)
    git("commit", "-qm", "x", cwd=main)
    return (main / "example").resolve()


def add_worktree(main_project: Path, name: str) -> Path:
    worktree = main_project.parent.parent / name
    git("worktree", "add", "-q", str(worktree), "-b", name, cwd=main_project)
    return (worktree / "example").resolve()


def by_path(checkouts: list) -> dict:
    return {checkout.path: checkout for checkout in checkouts}


def test_every_worktree_is_a_checkout_with_the_database_it_derives():
    with sandbox() as box:
        main = a_repository(box.tmp_path)
        feature = add_worktree(main, "feature")

        checkouts, in_git = project_checkouts(feature)

        assert in_git
        found = by_path(checkouts)
        assert set(found) == {str(main), str(feature)}
        assert found[str(main)].database == "example"
        assert found[str(feature)].database == "example_feature"
        assert all(checkout.exists for checkout in checkouts)


def test_a_checkout_pointed_at_another_database_is_found_to_use_that_one():
    with sandbox() as box:
        main = a_repository(box.tmp_path)
        feature = add_worktree(main, "feature")
        write_pointer(feature, db_name="example_shared")

        checkouts, _ = project_checkouts(main)

        assert by_path(checkouts)[str(feature)].database == "example_shared"


def test_a_worktree_removed_by_hand_is_still_listed_and_is_missing():
    with sandbox() as box:
        main = a_repository(box.tmp_path)
        feature = add_worktree(main, "feature")
        shutil.rmtree(feature.parent)

        checkouts, _ = project_checkouts(main)

        missing = by_path(checkouts)[str(feature)]
        assert not missing.exists
        assert missing.database is None
        assert missing.worktree == str(feature.parent)


def test_a_worktree_git_was_told_is_gone_is_not_listed():
    with sandbox() as box:
        main = a_repository(box.tmp_path)
        feature = add_worktree(main, "feature")
        git("worktree", "remove", "--force", str(feature.parent), cwd=main)

        checkouts, _ = project_checkouts(main)

        assert set(by_path(checkouts)) == {str(main)}


def test_outside_git_the_only_checkout_is_the_one_asked_about():
    with sandbox() as box:
        project = box.tmp_path / "shop"
        project.mkdir()
        (project / "pyproject.toml").write_text('[project]\nname = "shop"\n')

        checkouts, in_git = project_checkouts(project)

        assert not in_git
        assert [checkout.path for checkout in checkouts] == [str(project.resolve())]
        assert checkouts[0].database == "shop"


def a_database_made_by(name: str, checkout: Path) -> CleanFacts:
    recorded = checkout_id(checkout)
    return CleanFacts(
        name=name,
        size_bytes=1,
        recorded_checkout=recorded,
        owner_path=look_at_owner_path(recorded),
        connections=0,
        is_test=False,
    )


def test_the_plan_from_a_real_repository():
    """One worktree there, one removed with git, one removed by hand, and
    one that was moved and uses the database it made where it used to be."""
    with sandbox() as box:
        main = a_repository(box.tmp_path)
        there = add_worktree(main, "there")
        removed = add_worktree(main, "removed")
        by_hand = add_worktree(main, "by-hand")
        moved_from = add_worktree(main, "moved")

        databases = [
            a_database_made_by("example", main),
            a_database_made_by("example_there", there),
            a_database_made_by("example_removed", removed),
            a_database_made_by("example_by_hand", by_hand),
            a_database_made_by("example_moved", moved_from),
        ]

        git("worktree", "remove", "--force", str(removed.parent), cwd=main)
        shutil.rmtree(by_hand.parent)
        moved_to = main.parent.parent / "somewhere-else"
        git("worktree", "move", str(moved_from.parent), str(moved_to), cwd=main)
        write_pointer((moved_to / "example").resolve(), db_name="example_moved")

        # Read again: the disk has changed under the recorded paths.
        databases = [
            a_database_made_by(facts.name, Path(facts.recorded_checkout or ""))
            for facts in databases
        ]
        checkouts, in_git = project_checkouts(main)
        plan = plan_clean(
            databases,
            project_main="example",
            current="example",
            checkouts=checkouts,
            in_git=in_git,
        )

        assert [item.name for item in plan.drop] == ["example_removed"]
        reasons = {item.name: item.reason for item in plan.leave}
        assert reasons["example_there"].endswith("is configured to use it")
        assert "git lists a worktree" in reasons["example_by_hand"]
        assert reasons["example_moved"] == (
            f"the checkout at {(moved_to / 'example').resolve()}"
            " is configured to use it"
        )
