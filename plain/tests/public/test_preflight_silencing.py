from __future__ import annotations

from click.testing import CliRunner

from plain import preflight
from plain.cli.preflight import preflight_cli
from plain.preflight import PreflightCheck, PreflightResult, unused_silenced_results
from plain.preflight.registry import CheckRegistry
from plain.test import override_settings, patch


def test_silence_by_result_id():
    with override_settings(PREFLIGHT_SILENCED_RESULTS=["custom.example"]):
        result = PreflightResult(fix="Fix it.", id="custom.example")

        assert result.is_silenced()


def test_unsilenced_result():
    with override_settings(PREFLIGHT_SILENCED_RESULTS=["custom.other"]):
        result = PreflightResult(fix="Fix it.", id="custom.example")

        assert not result.is_silenced()


def test_silence_by_qualified_obj():
    with override_settings(
        PREFLIGHT_SILENCED_RESULTS=["custom.example:app.Model.field"]
    ):
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


def test_unused_silenced_results():
    with override_settings(
        PREFLIGHT_SILENCED_RESULTS=[
            "custom.example",  # matches by id
            "custom.example:app.Model.field",  # matches by qualified obj
            "custom.typo",  # matches nothing
        ]
    ):
        results = [
            PreflightResult(fix="Fix it.", id="custom.example", obj="app.Model.field"),
            PreflightResult(fix="Fix it.", id="custom.other"),
        ]

        assert unused_silenced_results(results) == ["custom.typo"]


def test_unused_silenced_results_empty_config():
    with override_settings(PREFLIGHT_SILENCED_RESULTS=[]):
        results = [PreflightResult(fix="Fix it.", id="custom.example")]

        assert unused_silenced_results(results) == []


def _registry_with_one_check():
    registry = CheckRegistry()

    class CheckExample(PreflightCheck):
        def run(self) -> list[PreflightResult]:
            return [PreflightResult(fix="Fix it.", id="custom.example")]

    registry.register_check(CheckExample, name="custom.check")
    return registry


def test_run_checks_reports_unused_silences_on_deploy():
    with override_settings(
        PREFLIGHT_SILENCED_CHECKS=[],
        PREFLIGHT_SILENCED_RESULTS=["custom.example", "custom.typo"],
    ):
        runs = list(_registry_with_one_check().run_checks(include_deploy_checks=True))

        names = [name for _, name, _ in runs]
        assert names == ["custom.check", "preflight.unused_silences"]

        unused_results = runs[-1][2]
        assert len(unused_results) == 1
        assert unused_results[0].id == "preflight.unused_silence"
        assert unused_results[0].obj == "custom.typo"
        assert unused_results[0].warning


def test_run_checks_skips_unused_silences_without_deploy():
    with override_settings(
        PREFLIGHT_SILENCED_CHECKS=[],
        PREFLIGHT_SILENCED_RESULTS=["custom.typo"],
    ):
        runs = list(_registry_with_one_check().run_checks(include_deploy_checks=False))

        names = [name for _, name, _ in runs]
        assert names == ["custom.check"]


def test_unused_silences_check_is_silenceable():
    """The registry-emitted check can be silenced via PREFLIGHT_SILENCED_CHECKS
    like any registered check — no "unknown check name" error, no final yield."""
    with override_settings(
        PREFLIGHT_SILENCED_CHECKS=["preflight.unused_silences"],
        PREFLIGHT_SILENCED_RESULTS=["custom.typo"],
    ):
        runs = list(_registry_with_one_check().run_checks(include_deploy_checks=True))

        names = [name for _, name, _ in runs]
        assert names == ["custom.check"]


def _patch_single_check(results):
    """Patch `run_checks` to yield one check ("custom.check") with `results`."""

    def run(*, include_deploy_checks):
        yield object(), "custom.check", results

    return patch(preflight, "run_checks", run)


def test_preflight_summary_excludes_fully_silenced_check():
    """A check whose issues are ALL silenced must not be tallied as a warning.
    The summary should read "1 passed" with no ", 1 warnings" — matching the
    ✔ shown on the check line and the JSON path's `"passed": true`."""
    with (
        _patch_single_check(
            [PreflightResult(fix="Fix it.", id="custom.silenced", warning=True)]
        ),
        override_settings(PREFLIGHT_SILENCED_RESULTS=["custom.silenced"]),
    ):
        result = CliRunner().invoke(preflight_cli, [])

    assert result.exit_code == 0, result.output
    assert "1 passed" in result.output
    assert "warning" not in result.output


def test_preflight_summary_counts_live_warning_alongside_silenced():
    """A live (non-silenced) warning on the same check as a silenced one still
    counts as a warning — silencing one result doesn't suppress the rest."""
    with (
        _patch_single_check(
            [
                PreflightResult(fix="Fix it.", id="custom.silenced", warning=True),
                PreflightResult(fix="Fix it.", id="custom.live", warning=True),
            ]
        ),
        override_settings(PREFLIGHT_SILENCED_RESULTS=["custom.silenced"]),
    ):
        result = CliRunner().invoke(preflight_cli, [])

    assert result.exit_code == 0, result.output
    assert "1 warnings" in result.output
    assert "✗" not in result.output


def test_preflight_summary_counts_live_error_and_fails():
    """A genuine (non-silenced) error counts as an error and exits non-zero."""
    with (
        _patch_single_check([PreflightResult(fix="Fix it.", id="custom.error")]),
        override_settings(PREFLIGHT_SILENCED_RESULTS=[]),
    ):
        result = CliRunner().invoke(preflight_cli, [])

    assert result.exit_code == 1, result.output
    assert "1 errors" in result.output
