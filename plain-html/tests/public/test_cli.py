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
    _write(tmp_path, "nested/ok.html", "<div><p>{{ name }}</p></div>\n")

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


def test_check_reports_unbalanced_block(tmp_path: Path) -> None:
    # A stray `{% endif %}` with no opening `{% if %}` is a structural
    # block error — reported with file:line:col anchored at the tag.
    path = _write(tmp_path, "bad.html", "{% endif %}<div></div>\n")

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(tmp_path)])

    assert result.exit_code == 1
    assert f"{path}:1:1:" in result.output
    assert "endif" in result.output


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


# --- component file existence (Fix A) -----------------------------------


def test_check_reports_missing_component_file(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "page.html",
        "---\ncomponents:\n  - ./Missing\n---\n<p>hi</p>\n",
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(path)])

    assert result.exit_code == 1
    assert f"{path}:1:1:" in result.output
    assert "components: entry './Missing'" in result.output
    assert "template file not found" in result.output


def test_check_resolved_component_file_passes(tmp_path: Path) -> None:
    _write(tmp_path, "Card.html", "<p>card</p>\n")
    _write(
        tmp_path,
        "page.html",
        "---\ncomponents:\n  - ./Card\n---\n<Card />\n",
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(tmp_path)])

    assert result.exit_code == 0
    assert "All templates checked" in result.output


def test_check_stdin_skips_relative_component_paths() -> None:
    """Relative component paths can't be resolved in stdin mode — skipped."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["check", "-"],
        input="---\ncomponents:\n  - ./Card\n---\n<Card />\n",
    )

    assert result.exit_code == 0


# --- component slot validation (Fix B) ----------------------------------


def test_check_reports_unknown_slot(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "Card.html",
        "---\nslots:\n  footer: optional\n---\n<div>{{ footer }}</div>\n",
    )
    path = _write(
        tmp_path,
        "page.html",
        # `<Card>` sits on line 7 — two blank lines below the
        # frontmatter — so the error must anchor there, not at line 1.
        "---\ncomponents:\n  - ./Card\n---\n\n\n"
        '<Card>{% slot "header" %}<p>x</p>{% endslot %}</Card>\n',
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(path)])

    assert result.exit_code == 1
    assert f"{path}:7:1: unknown slot 'header' on component <Card>" in result.output


def test_check_reports_missing_required_slot(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "Card.html",
        "---\nslots:\n  footer: required\n---\n<div>{{ footer }}</div>\n",
    )
    path = _write(
        tmp_path,
        "page.html",
        # `<Card />` on line 7 — the error anchors at the tag.
        "---\ncomponents:\n  - ./Card\n---\n\n\n<Card />\n",
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(path)])

    assert result.exit_code == 1
    assert (
        f"{path}:7:1: component <Card> is missing required slot 'footer'"
        in result.output
    )


def test_check_reports_duplicate_slot(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "Card.html",
        "---\nslots:\n  footer: optional\n---\n<div>{{ footer }}</div>\n",
    )
    path = _write(
        tmp_path,
        "page.html",
        # `<Card>` on line 7 — the error anchors at the tag.
        "---\ncomponents:\n  - ./Card\n---\n\n\n<Card>"
        '{% slot "footer" %}<p>a</p>{% endslot %}'
        '{% slot "footer" %}<p>b</p>{% endslot %}</Card>\n',
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(path)])

    assert result.exit_code == 1
    assert (
        f"{path}:7:1: component <Card> assigns slot 'footer' more than once"
        in result.output
    )


def test_check_required_default_slot_satisfied_by_content(tmp_path: Path) -> None:
    """Unmarked child content satisfies a required `default` slot."""
    _write(
        tmp_path,
        "Card.html",
        "---\nslots:\n  default: required\n---\n<div>{{ children }}</div>\n",
    )
    _write(
        tmp_path,
        "page.html",
        "---\ncomponents:\n  - ./Card\n---\n<Card><p>hello</p></Card>\n",
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(tmp_path)])

    assert result.exit_code == 0


def test_check_skips_slot_validation_for_missing_component(tmp_path: Path) -> None:
    """A missing component file is reported once — slot validation skipped."""
    path = _write(
        tmp_path,
        "page.html",
        '---\ncomponents:\n  - ./Missing\n---\n<Missing><p :slot="x">y</p></Missing>\n',
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(path)])

    assert result.exit_code == 1
    assert "template file not found" in result.output
    assert "unknown slot" not in result.output
    assert "1 error found" in result.output


# --- component attribute-name validation (Fix B) ------------------------


def test_check_reports_unknown_attr(tmp_path: Path) -> None:
    """An attr the component doesn't declare is flagged — plain.html has
    no pass-through, so an undeclared attr is always a mistake."""
    _write(
        tmp_path,
        "Card.html",
        "---\nattrs:\n  title: str\n---\n<p>{{ title }}</p>\n",
    )
    path = _write(
        tmp_path,
        "page.html",
        # `<Card>` on line 7 — the error anchors at the tag.
        '---\ncomponents:\n  - ./Card\n---\n\n\n<Card title="x" subtilte="oops" />\n',
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(path)])

    assert result.exit_code == 1
    assert f"{path}:7:1: unknown attr 'subtilte' on component <Card>" in result.output
    # The correctly-named `title` attr must not be flagged.
    assert "unknown attr 'title'" not in result.output


def test_check_accepts_declared_attrs_including_keyword_named(tmp_path: Path) -> None:
    """A declared attr — including a keyword-named one like `class` — is
    accepted as written."""
    _write(
        tmp_path,
        "Card.html",
        "---\nattrs:\n  class: str\n  title: str\n---\n<div>{{ title }}</div>\n",
    )
    _write(
        tmp_path,
        "page.html",
        '---\ncomponents:\n  - ./Card\n---\n<Card class="box" title="x" />\n',
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(tmp_path)])

    assert result.exit_code == 0
    assert "All templates checked" in result.output


def test_check_skips_attr_validation_for_missing_component(tmp_path: Path) -> None:
    """A missing component file is reported once — attr validation skipped."""
    path = _write(
        tmp_path,
        "page.html",
        '---\ncomponents:\n  - ./Missing\n---\n<Missing bogus="x" />\n',
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(path)])

    assert result.exit_code == 1
    assert "template file not found" in result.output
    assert "unknown attr" not in result.output
    assert "1 error found" in result.output
