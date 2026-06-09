from __future__ import annotations

from plain.preflight import PreflightResult
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
