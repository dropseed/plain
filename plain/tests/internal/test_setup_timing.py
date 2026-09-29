"""
`plain.runtime.setup()` keeps how long each part of it took, for a report on
how long the process took to start.
"""

import plain.runtime


def test_setup_recorded_what_it_took():
    timing = plain.runtime.setup_timing
    assert timing is not None

    # Each installed package's import, in the order installed.
    assert [name for name, _ in timing.package_imports] == list(
        plain.runtime.settings.INSTALLED_PACKAGES
    )
    for _, seconds in timing.package_imports:
        assert seconds >= 0
    for name, seconds in timing.hooks:
        assert name
        assert seconds >= 0
    assert timing.settings >= 0
    assert timing.ready >= 0


def test_the_clock_started_before_setup_did():
    # A process can't know when it started, so what it has is the CPU time
    # it had used when Plain was imported.
    assert plain.runtime.CPU_SECONDS_BEFORE_PLAIN >= 0
    assert plain.runtime.PLAIN_IMPORTED_AT > 0
