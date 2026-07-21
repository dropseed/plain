from __future__ import annotations

from click.testing import CliRunner

from plain.cli.core import cli
from plain.runtime import settings
from plain.urls.resolvers import _get_cached_resolver


def test_plain_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"], prog_name="plain")
    assert result.exit_code == 0
    assert result.output.startswith("Usage: plain")


def test_plain_urls_list_renders_both_modes():
    """`plain urls list` must render every URLPattern and URLResolver in the
    configured router without crashing. Pins both `--flat` and the default
    tree mode against `boundary_routers.BoundaryRouter`, which exercises
    both kinds (nested includes + endpoint patterns).

    Regression test: this used to AttributeError because the rendering loop
    read `pattern.pattern` after the resolver was rewritten to expose
    `raw_route`. ty couldn't catch the access because the parameter was
    annotated as bare `list`; both call sites are now typed
    `list[URLPattern | URLResolver]` so future renames blow up at
    type-check time.
    """
    original = settings.URLS_ROUTER
    original_ts = settings.URLS_TRAILING_SLASH
    settings.URLS_ROUTER = "boundary_routers.BoundaryRouter"
    settings.URLS_TRAILING_SLASH = True
    _get_cached_resolver.cache_clear()
    try:
        runner = CliRunner()

        tree = runner.invoke(cli, ["urls", "list"], prog_name="plain")
        assert tree.exit_code == 0, tree.output
        assert "admin-canonical" in tree.output
        # Tree mode should append the trailing slash on endpoint labels
        # so the displayed URL matches what `resolve()` accepts.
        assert "home/" in tree.output

        flat = runner.invoke(cli, ["urls", "list", "--flat"], prog_name="plain")
        assert flat.exit_code == 0, flat.output
        assert "admin-canonical" in flat.output
        # Under `URLS_TRAILING_SLASH=True`, canonical URLs end in `/`.
        # Flat rendering must produce `admin-canonical/home/` — not
        # `admin-canonicalhome/` (missing separator) and not
        # `admin-canonical/home` (missing trailing slash). Both were
        # regressions of the global-trailing-slash refactor.
        assert "admin-canonical/home/" in flat.output
        assert "admin-canonicalhome" not in flat.output
    finally:
        settings.URLS_ROUTER = original
        settings.URLS_TRAILING_SLASH = original_ts
        _get_cached_resolver.cache_clear()


def test_plain_request_streaming_response_does_not_crash():
    """`plain request` against a streaming/file response (e.g. an asset) must
    not crash. Streaming responses have no readable `.content` — accessing it
    raises AttributeError — so the command summarizes from headers instead of
    dumping the body.
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["request", "/stream"], prog_name="plain")
    assert result.exit_code == 0, result.output
    assert "Status: 200" in result.output
    # Body is summarized, not dumped or crashed on.
    assert "streaming response" in result.output
    assert "text/plain" in result.output
    assert "streamed-bytes" not in result.output


def test_plain_request_streaming_body_assertion_is_flagged_unverifiable():
    """A body `--contains` assertion can't be checked on a streaming response
    (the body isn't readable), so it must fail loudly rather than silently pass.
    """
    runner = CliRunner()
    result = runner.invoke(
        cli, ["request", "/stream", "--contains", "streamed"], prog_name="plain"
    )
    assert result.exit_code == 1, result.output
    assert "Cannot check body assertions on a streaming response" in result.output


def test_plain_changelog_plain():
    runner = CliRunner()
    result = runner.invoke(cli, ["changelog", "plain"], prog_name="plain")
    assert result.exit_code == 0
    assert "0.50.0" in result.output


def test_plain_changelog_range_warning():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["changelog", "plain", "--from", "0.49.0", "--to", "0.50.0"],
        prog_name="plain",
    )
    assert result.exit_code == 0
    assert "0.50.0" in result.output
    assert "Warning" in result.output
