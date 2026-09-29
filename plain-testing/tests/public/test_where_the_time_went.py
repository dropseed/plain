"""
A run says where its time went: phase by phase, in the text report when
the time outside the tests is worth a word and with `--verbose`, and in the
`--json` document always.
"""

import json
import time

from plain_test_helpers import run_in_project, section

ONE_TEST = {"tests/test_one.py": "def test_one():\n    pass\n"}

SLOW_TO_SET_UP = {
    "tests/lifecycle.py": (
        "import time\n"
        "\n"
        "from plain.testing import TestLifecycle\n"
        "\n"
        "\n"
        "class AppTestLifecycle(TestLifecycle):\n"
        "    def setup_worker(self):\n"
        "        time.sleep(1.1)\n"
    ),
    **ONE_TEST,
}

PHASE_NAMES = [
    "python_startup",
    "command",
    "runtime_setup",
    "helper_modules",
    "lifecycles_loaded",
    "collection",
    "lifecycle_setup",
    "tests",
    "lifecycle_teardown",
    "report",
    "unaccounted",
]


def test_the_document_has_every_phase_in_the_order_they_happen():
    started = time.perf_counter()
    result = run_in_project(ONE_TEST, "--json")
    wall = time.perf_counter() - started

    phases = json.loads(result.stdout)["phases"]
    assert [phase["name"] for phase in phases] == PHASE_NAMES
    for phase in phases:
        assert phase["seconds"] >= 0
        assert phase["measured"] == (
            "cpu" if phase["name"] == "python_startup" else "wall"
        )
    # They add up to no more than the run took from outside.
    assert sum(phase["seconds"] for phase in phases) <= wall


def test_the_phases_say_what_was_inside_them():
    phases = {
        phase["name"]: phase
        for phase in json.loads(run_in_project(SLOW_TO_SET_UP, "--json").stdout)[
            "phases"
        ]
    }
    # The test file was rewritten, or read back from the cache.
    [collected] = phases["collection"]["parts"]
    assert collected["name"] in ("rewrote 1 file", "read 1 file from the cache")
    # Each lifecycle by name, setting up and taking down.
    [set_up] = phases["lifecycle_setup"]["parts"]
    assert set_up["name"] == "AppTestLifecycle"
    assert set_up["seconds"] >= 1.1
    assert phases["lifecycle_setup"]["seconds"] >= 1.1
    assert [part["name"] for part in phases["lifecycle_teardown"]["parts"]] == [
        "AppTestLifecycle"
    ]


SAYS_WHAT_ITS_SETUP_DID = {
    "tests/lifecycle.py": (
        "from plain.testing import TestLifecycle\n"
        "\n"
        "\n"
        "class AppTestLifecycle(TestLifecycle):\n"
        "    def describe_setup(self):\n"
        '        return (("warmed the cache", 0.25), ("seeded the index", 0.5))\n'
    ),
    **ONE_TEST,
}


def test_a_lifecycle_says_what_its_setup_spent_the_time_on():
    result = run_in_project(SAYS_WHAT_ITS_SETUP_DID, "--json")
    assert result.exit_code == 0

    phases = {phase["name"]: phase for phase in json.loads(result.stdout)["phases"]}
    [set_up] = phases["lifecycle_setup"]["parts"]
    assert set_up["name"] == "AppTestLifecycle"
    assert set_up["parts"] == [
        {"name": "warmed the cache", "seconds": 0.25, "parts": []},
        {"name": "seeded the index", "seconds": 0.5, "parts": []},
    ]

    result = run_in_project(SAYS_WHAT_ITS_SETUP_DID, "--verbose")
    lines = section(result.stdout, "where the ").splitlines()
    # The lifecycle has a line under setup and another under teardown; the
    # first is the setup's.
    lifecycle = next(
        line for line in lines if line.strip().startswith("AppTestLifecycle")
    )
    [warmed] = [line for line in lines if "warmed the cache" in line]
    # Under the lifecycle's line, one level further in.
    assert lines.index(warmed) == lines.index(lifecycle) + 1
    assert (
        len(warmed) - len(warmed.lstrip())
        == len(lifecycle) - len(lifecycle.lstrip()) + 2
    )
    assert warmed.rstrip().endswith("0.25s")


def test_a_run_that_spent_its_time_outside_the_tests_says_where():
    result = run_in_project(SLOW_TO_SET_UP)
    assert result.exit_code == 0
    where = section(result.stdout, "where the ")
    assert where.startswith("where the ")
    assert where.splitlines()[0].endswith("s went")
    lines = [line.strip() for line in where.splitlines()[1:]]
    assert lines[0].startswith("python startup")
    assert lines[0].endswith("cpu time, before Plain was imported")
    assert any(line.startswith("lifecycle setup") for line in lines)
    assert any(line.startswith("AppTestLifecycle") for line in lines)
    assert lines[-1].startswith("unaccounted")


def test_verbose_always_says_where_the_time_went():
    result = run_in_project(ONE_TEST, "--verbose")
    assert result.exit_code == 0
    assert "where the " in result.stdout
    assert "\n  tests " in result.stdout


def test_a_stopped_run_has_the_phases_it_got_through():
    result = run_in_project(ONE_TEST, "--json", "--match", "nothing_is_called_this")
    assert result.exit_code == 4
    phases = json.loads(result.stdout)["phases"]
    assert [phase["name"] for phase in phases] == [
        "python_startup",
        "command",
        "runtime_setup",
        "helper_modules",
        "lifecycles_loaded",
        "collection",
        "unaccounted",
    ]
