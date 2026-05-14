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


def test_check_reports_invalid_attr_declaration(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "bad.html",
        "---\nattrs:\n  bad-name: str\n---\n<p>hi</p>\n",
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(tmp_path)])

    assert result.exit_code == 1
    assert f"{path}:1:1:" in result.output
    assert "bad-name" in result.output


def test_check_reports_invalid_import_statement(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "bad.html",
        "---\nimports:\n  - x = 1\n---\n<p>hi</p>\n",
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(tmp_path)])

    assert result.exit_code == 1
    assert f"{path}:1:1:" in result.output
    assert "import" in result.output.lower()


def test_check_reports_invalid_slot_form(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "bad.html",
        "---\nslots:\n  header: whatever\n---\n<p>hi</p>\n",
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(tmp_path)])

    assert result.exit_code == 1
    assert f"{path}:1:1:" in result.output
    assert "header" in result.output


def test_check_accepts_single_file(tmp_path: Path) -> None:
    path = _write(tmp_path, "ok.html", "<p>hi</p>\n")

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(path)])

    assert result.exit_code == 0


def test_collect_files_default_excludes_installed_packages(
    monkeypatch, tmp_path: Path
) -> None:
    """The default walk only touches the project's own `app/templates/`."""
    from plain.html import cli as cli_mod

    app_dir = tmp_path / "app" / "templates"
    pkg_dir = tmp_path / "site-packages" / "plain" / "admin" / "templates"
    (app_dir / "ok.html").parent.mkdir(parents=True)
    (app_dir / "ok.html").write_text("<p>hi</p>\n")
    (pkg_dir / "x.html").parent.mkdir(parents=True)
    (pkg_dir / "x.html").write_text("<p>hi</p>\n")

    monkeypatch.setattr(cli_mod, "get_template_dirs", lambda: (app_dir, pkg_dir))

    default = cli_mod._collect_files(())
    assert default == [app_dir / "ok.html"]

    opted_in = cli_mod._collect_files((), include_installed_packages=True)
    assert opted_in == sorted([app_dir / "ok.html", pkg_dir / "x.html"])


def test_check_include_installed_packages_warning(monkeypatch, tmp_path: Path) -> None:
    """Opting in prints a warning explaining the implication."""
    from plain.html import cli as cli_mod

    app_dir = tmp_path / "app" / "templates"
    pkg_dir = tmp_path / "site-packages" / "plain" / "admin" / "templates"
    (app_dir).mkdir(parents=True)
    (pkg_dir).mkdir(parents=True)
    (app_dir / "ok.html").write_text("<p>hi</p>\n")

    monkeypatch.setattr(cli_mod, "get_template_dirs", lambda: (app_dir, pkg_dir))

    runner = CliRunner()
    result = runner.invoke(cli, ["check", "--include-installed-packages"])

    assert result.exit_code == 0
    assert "owned by their packages" in result.output


def test_check_flag_hidden_from_help() -> None:
    """The opt-in flag must not appear in --help."""
    runner = CliRunner()
    result = runner.invoke(cli, ["check", "--help"])
    assert result.exit_code == 0
    assert "--include-installed-packages" not in result.output


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


def test_format_writes_changes(tmp_path: Path) -> None:
    path = _write(tmp_path, "f.html", "<div><p>hi</p></div>")

    runner = CliRunner()
    result = runner.invoke(cli, ["format", str(tmp_path)])

    assert result.exit_code == 0
    assert "1 reformatted" in result.output
    assert path.read_text() == "<div>\n    <p>hi</p>\n</div>\n"


def test_format_leaves_already_formatted_files_untouched(tmp_path: Path) -> None:
    formatted = "<div>\n    <p>hi</p>\n</div>\n"
    path = _write(tmp_path, "f.html", formatted)

    runner = CliRunner()
    result = runner.invoke(cli, ["format", str(tmp_path)])

    assert result.exit_code == 0
    assert "0 reformatted" in result.output
    assert path.read_text() == formatted


def test_format_check_exits_nonzero_when_changes_pending(tmp_path: Path) -> None:
    path = _write(tmp_path, "f.html", "<div><p>hi</p></div>")

    runner = CliRunner()
    result = runner.invoke(cli, ["format", "--check", str(tmp_path)])

    assert result.exit_code == 1
    assert "would reformat" in result.output
    # --check must not write to disk
    assert path.read_text() == "<div><p>hi</p></div>"


def test_format_check_exits_zero_when_already_formatted(tmp_path: Path) -> None:
    _write(tmp_path, "f.html", "<div>\n    <p>hi</p>\n</div>\n")

    runner = CliRunner()
    result = runner.invoke(cli, ["format", "--check", str(tmp_path)])

    assert result.exit_code == 0
    assert "All templates already formatted" in result.output


def test_format_skips_unparseable_files(tmp_path: Path) -> None:
    bad = _write(tmp_path, "bad.html", "<div><p>hello\n</div>\n")
    ok = _write(tmp_path, "ok.html", "<div><p>hi</p></div>")

    runner = CliRunner()
    result = runner.invoke(cli, ["format", str(tmp_path)])

    assert result.exit_code == 1
    assert "skipped" in result.output
    assert str(bad) in result.output
    # The valid file should still be reformatted.
    assert ok.read_text() == "<div>\n    <p>hi</p>\n</div>\n"


def test_format_stdin_writes_to_stdout() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["format", "-"], input="<div><p>hi</p></div>")

    assert result.exit_code == 0
    assert result.output == "<div>\n    <p>hi</p>\n</div>\n"


def test_format_check_stdin_exits_nonzero_when_changes() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["format", "--check", "-"], input="<div><p>hi</p></div>"
    )

    assert result.exit_code == 1
    # --check mode is silent on stdout; no formatted output written.
    assert result.output == ""


def test_format_check_stdin_exits_zero_when_already_formatted() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["format", "--check", "-"], input="<div>\n    <p>hi</p>\n</div>\n"
    )

    assert result.exit_code == 0


def test_format_stdin_error_to_stderr() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["format", "-"], input="<div><p>oops")

    assert result.exit_code == 1
    assert "<stdin>:" in result.output or "<stdin>" in result.stderr


def test_format_dash_with_other_paths_errors(tmp_path: Path) -> None:
    _write(tmp_path, "x.html", "<p>hi</p>")

    runner = CliRunner()
    result = runner.invoke(cli, ["format", "-", str(tmp_path)], input="<p>x</p>")

    assert result.exit_code != 0
    assert "Cannot mix" in result.output


def test_check_stdin_reports_error() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["check", "-"], input="<div><unclosed")

    assert result.exit_code == 1
    assert "<stdin>:" in result.output or "<stdin>" in result.stderr


def test_check_stdin_clean_template_exits_zero() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["check", "-"], input="<p>hi</p>")

    assert result.exit_code == 0
