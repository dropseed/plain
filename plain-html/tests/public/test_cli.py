from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from plain.html.cli import cli


def _write(dir: Path, name: str, content: str) -> Path:
    path = dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_check_valid_templates_pass(tmp_path: Path) -> None:
    _write(tmp_path, "ok.html", "<p>hi</p>\n")
    _write(tmp_path, "nested/ok.html", "<div><p>{name}</p></div>\n")

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(tmp_path)])

    assert result.exit_code == 0
    assert "All templates checked" in result.output


def test_check_no_files_reports_and_exits_zero(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(tmp_path)])

    assert result.exit_code == 0
    assert "No .html templates found" in result.output


def test_check_reports_unclosed_tag(tmp_path: Path) -> None:
    path = _write(tmp_path, "bad.html", "<div>\n  <p>hello\n</div>\n")

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(tmp_path)])

    assert result.exit_code == 1
    assert f"{path}:3:1:" in result.output
    assert "Mismatched tag" in result.output


def test_check_reports_unterminated_comment(tmp_path: Path) -> None:
    path = _write(tmp_path, "bad.html", "<p>\n  {# never closes\n</p>\n")

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(tmp_path)])

    assert result.exit_code == 1
    assert f"{path}:2:3:" in result.output
    assert "Unterminated template comment" in result.output


def test_check_maps_offsets_through_frontmatter(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "bad.html",
        "---\nattrs:\n  name: str\n---\n<div>\n  </span>\n",
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(tmp_path)])

    assert result.exit_code == 1
    # `</span>` is on line 6 (after 4 frontmatter lines + `<div>` on line 5).
    assert f"{path}:6:3:" in result.output


def test_check_reports_directive_shape_error(tmp_path: Path) -> None:
    path = _write(tmp_path, "bad.html", "<template :include></template>\n")

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(tmp_path)])

    assert result.exit_code == 1
    assert f"{path}:1:1:" in result.output
    assert ":include" in result.output


def test_check_accepts_single_file(tmp_path: Path) -> None:
    path = _write(tmp_path, "ok.html", "<p>hi</p>\n")

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(path)])

    assert result.exit_code == 0


def test_check_skips_non_html_files(tmp_path: Path) -> None:
    _write(tmp_path, "ok.html", "<p>hi</p>\n")
    _write(tmp_path, "ignore.txt", "<div><unclosed>\n")

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(tmp_path)])

    assert result.exit_code == 0


def test_check_reports_multiple_errors_across_files(tmp_path: Path) -> None:
    a = _write(tmp_path, "a.html", "<div>\n")
    b = _write(tmp_path, "b.html", "<p>{# nope\n")

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(tmp_path)])

    assert result.exit_code == 1
    assert str(a) in result.output
    assert str(b) in result.output
    assert "2 errors found" in result.output
