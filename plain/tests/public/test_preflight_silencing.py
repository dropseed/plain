from __future__ import annotations

from click.testing import CliRunner

from plain import preflight
from plain.cli.core import cli
from plain.preflight import PreflightCheck, PreflightResult, unused_silenced_results
from plain.preflight.registry import CheckRegistry
from plain.runtime import settings


def test_silence_by_result_id(monkeypatch):
    monkeypatch.setattr(settings, "PREFLIGHT_SILENCED_RESULTS", ["custom.example"])

    result = PreflightResult(fix="Fix it.", id="custom.example")

    assert result.is_silenced()


def test_unsilenced_result(monkeypatch):
    monkeypatch.setattr(settings, "PREFLIGHT_SILENCED_RESULTS", ["custom.other"])

    result = PreflightResult(fix="Fix it.", id="custom.example")

    assert not result.is_silenced()


def test_silence_by_qualified_obj(monkeypatch):
    monkeypatch.setattr(
        settings, "PREFLIGHT_SILENCED_RESULTS", ["custom.example:app.Model.field"]
    )

    silenced = PreflightResult(
        fix="Fix it.", id="custom.example", obj="app.Model.field"
    )
    other_obj = PreflightResult(
        fix="Fix it.", id="custom.example", obj="app.Model.other"
    )
    no_obj = PreflightResult(fix="Fix it.", id="custom.example")

    assert silenced.is_silenced()
    assert not other_obj.is_silenced()
    assert not no_obj.is_silenced()


def test_unused_silenced_results(monkeypatch):
    monkeypatch.setattr(
        settings,
        "PREFLIGHT_SILENCED_RESULTS",
        [
            "custom.example",  # matches by id
            "custom.example:app.Model.field",  # matches by qualified obj
            "custom.typo",  # matches nothing
        ],
    )

    results = [
        PreflightResult(fix="Fix it.", id="custom.example", obj="app.Model.field"),
        PreflightResult(fix="Fix it.", id="custom.other"),
    ]

    assert unused_silenced_results(results) == ["custom.typo"]


def test_unused_silenced_results_empty_config(monkeypatch):
    monkeypatch.setattr(settings, "PREFLIGHT_SILENCED_RESULTS", [])

    results = [PreflightResult(fix="Fix it.", id="custom.example")]

    assert unused_silenced_results(results) == []


def _registry_with_one_check():
    registry = CheckRegistry()

    class CheckExample(PreflightCheck):
        def run(self) -> list[PreflightResult]:
            return [PreflightResult(fix="Fix it.", id="custom.example")]

    registry.register_check(CheckExample, name="custom.check")
    return registry


def test_run_checks_reports_unused_silences_on_deploy(monkeypatch):
    monkeypatch.setattr(settings, "PREFLIGHT_SILENCED_CHECKS", [])
    monkeypatch.setattr(
        settings, "PREFLIGHT_SILENCED_RESULTS", ["custom.example", "custom.typo"]
    )

    runs = list(_registry_with_one_check().run_checks(include_deploy_checks=True))

    names = [name for _, name, _ in runs]
    assert names == ["custom.check", "preflight.unused_silences"]

    unused_results = runs[-1][2]
    assert len(unused_results) == 1
    assert unused_results[0].id == "preflight.unused_silence"
    assert unused_results[0].obj == "custom.typo"
    assert unused_results[0].warning


def test_run_checks_skips_unused_silences_without_deploy(monkeypatch):
    monkeypatch.setattr(settings, "PREFLIGHT_SILENCED_CHECKS", [])
    monkeypatch.setattr(settings, "PREFLIGHT_SILENCED_RESULTS", ["custom.typo"])

    runs = list(_registry_with_one_check().run_checks(include_deploy_checks=False))

    names = [name for _, name, _ in runs]
    assert names == ["custom.check"]


def test_unused_silences_check_is_silenceable(monkeypatch):
    """The registry-emitted check can be silenced via PREFLIGHT_SILENCED_CHECKS
    like any registered check — no "unknown check name" error, no final yield."""
    monkeypatch.setattr(
        settings, "PREFLIGHT_SILENCED_CHECKS", ["preflight.unused_silences"]
    )
    monkeypatch.setattr(settings, "PREFLIGHT_SILENCED_RESULTS", ["custom.typo"])

    runs = list(_registry_with_one_check().run_checks(include_deploy_checks=True))

    names = [name for _, name, _ in runs]
    assert names == ["custom.check"]


def _patch_single_check(monkeypatch, results):
    """Patch `run_checks` to yield one check ("custom.check") with `results`."""

    def run(*, include_deploy_checks):
        yield object(), "custom.check", results

    monkeypatch.setattr(preflight, "run_checks", run)


def test_preflight_summary_excludes_fully_silenced_check(monkeypatch):
    """A check whose issues are ALL silenced must not be tallied as a warning.
    The summary should read "1 passed" with no ", 1 warnings" — matching the
    ✔ shown on the check line and the JSON path's `"passed": true`."""
    _patch_single_check(
        monkeypatch,
        [PreflightResult(fix="Fix it.", id="custom.silenced", warning=True)],
    )
    monkeypatch.setattr(settings, "PREFLIGHT_SILENCED_RESULTS", ["custom.silenced"])

    result = CliRunner().invoke(cli, ["preflight"], prog_name="plain")

    assert result.exit_code == 0, result.output
    assert "1 passed" in result.output
    assert "warning" not in result.output


def test_preflight_summary_counts_live_warning_alongside_silenced(monkeypatch):
    """A live (non-silenced) warning on the same check as a silenced one still
    counts as a warning — silencing one result doesn't suppress the rest."""
    _patch_single_check(
        monkeypatch,
        [
            PreflightResult(fix="Fix it.", id="custom.silenced", warning=True),
            PreflightResult(fix="Fix it.", id="custom.live", warning=True),
        ],
    )
    monkeypatch.setattr(settings, "PREFLIGHT_SILENCED_RESULTS", ["custom.silenced"])

    result = CliRunner().invoke(cli, ["preflight"], prog_name="plain")

    assert result.exit_code == 0, result.output
    assert "1 warnings" in result.output
    assert "✗" not in result.output


def test_preflight_summary_counts_live_error_and_fails(monkeypatch):
    """A genuine (non-silenced) error counts as an error and exits non-zero."""
    _patch_single_check(
        monkeypatch, [PreflightResult(fix="Fix it.", id="custom.error")]
    )
    monkeypatch.setattr(settings, "PREFLIGHT_SILENCED_RESULTS", [])

    result = CliRunner().invoke(cli, ["preflight"], prog_name="plain")

    assert result.exit_code == 1, result.output
    assert "1 errors" in result.output
