from plain.test import Client


def test_html_page():
    client = Client()
    response = client.get("/about/")
    assert response.status_code == 200
    assert b"About" in response.content


def test_markdown_page_returns_html():
    client = Client()
    response = client.get("/", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert b"<h1" in response.content
    assert b"Welcome" in response.content


def test_markdown_accept_header_returns_rendered_markdown():
    """Requesting markdown via Accept header should return Jinja-rendered source."""
    client = Client()
    response = client.get("/", headers={"Accept": "text/markdown"})
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
    # Should be raw markdown, not HTML
    assert b"<h1" not in response.content
    assert b"# Welcome" in response.content


def test_markdown_url_returns_rendered_markdown():
    """The .md URL should return Jinja-rendered source."""
    client = Client()
    response = client.get("/index.md")
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
    assert b"# Welcome" in response.content


def test_markdown_jinja_rendered_via_accept_header():
    """Markdown served via Accept header should have Jinja tags resolved."""
    client = Client()
    response = client.get("/jinja-test/", headers={"Accept": "text/markdown"})
    assert response.status_code == 200
    content = response.content.decode()
    # Jinja should be rendered — no raw {{ }} tags
    assert "{{ page.title }}" not in content
    assert "Jinja Test" in content
    assert "{{ DEBUG }}" not in content


def test_markdown_jinja_rendered_via_md_url():
    """Markdown served via .md URL should have Jinja tags resolved."""
    client = Client()
    response = client.get("/jinja-test.md")
    assert response.status_code == 200
    content = response.content.decode()
    assert "{{ page.title }}" not in content
    assert "Jinja Test" in content
    assert "{{ DEBUG }}" not in content


def test_wildcard_accept_prefers_markdown():
    """With */* accept (agent-friendly), markdown pages serve markdown over HTML."""
    client = Client()
    response = client.get("/", headers={"Accept": "*/*"})
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
    assert b"# Welcome" in response.content


def test_html_page_ignores_markdown_accept():
    """An HTML page should return HTML even when Accept prefers markdown."""
    client = Client()
    response = client.get("/about/", headers={"Accept": "text/markdown"})
    assert response.status_code == 200
    assert b"About" in response.content
    assert b"<h1>" in response.content


def test_render_plain_skips_jinja():
    """Pages with render_plain: true should not have Jinja tags processed."""
    client = Client()
    response = client.get("/raw.md")
    assert response.status_code == 200
    content = response.content.decode()
    # The raw {{ not_rendered }} should pass through unchanged
    assert "{{ not_rendered }}" in content


def test_markdown_frontmatter_stripped():
    """Frontmatter should not appear in markdown responses."""
    client = Client()
    response = client.get("/index.md")
    content = response.content.decode()
    assert "---" not in content
    assert "title:" not in content


def test_paired_html_page():
    """Paired .html page should serve HTML at its normal URL."""
    client = Client()
    response = client.get("/paired/")
    assert response.status_code == 200
    assert b"Paired HTML" in response.content
    assert b"<h1>" in response.content


def test_paired_markdown_url():
    """Paired .md file should be served at .md URL."""
    client = Client()
    response = client.get("/paired.md")
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
    assert b"# Paired Markdown" in response.content


def test_paired_accept_header():
    """Paired page with Accept: text/markdown should return the companion markdown."""
    client = Client()
    response = client.get("/paired/", headers={"Accept": "text/markdown"})
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
    assert b"# Paired Markdown" in response.content
    assert b"<h1>" not in response.content


def test_paired_accept_header_uses_companion_context():
    """Companion markdown served via Accept header should render with its own page context."""
    client = Client()
    response = client.get("/paired/", headers={"Accept": "text/markdown"})
    content = response.content.decode()
    # Should use the companion .md's frontmatter (title: "Paired Page"),
    # not the HTML page's default title
    assert "Title is Paired Page." in content
    assert "{{ page.title }}" not in content


def test_paired_html_ignores_html_accept():
    """Paired page with Accept: text/html should return the HTML version."""
    client = Client()
    response = client.get("/paired/", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert b"Paired HTML" in response.content
    assert b"<h1>" in response.content


def test_paired_html_has_vary_header():
    """Paired HTML responses should include Vary: Accept for correct caching."""
    client = Client()
    response = client.get("/paired/")
    assert response.status_code == 200
    assert response.headers.get("Vary") == "Accept"


def test_unpaired_html_no_vary_header():
    """Unpaired HTML pages should not include Vary: Accept."""
    client = Client()
    response = client.get("/about/")
    assert response.status_code == 200
    assert "Vary" not in response.headers


def test_paired_serve_markdown_disabled(monkeypatch):
    """Paired page should return HTML when PAGES_SERVE_MARKDOWN is False, even with Accept: text/markdown."""
    from plain.runtime import settings

    monkeypatch.setattr(settings, "PAGES_SERVE_MARKDOWN", False)

    client = Client()
    response = client.get("/paired/", headers={"Accept": "text/markdown"})
    assert response.status_code == 200
    assert b"Paired HTML" in response.content
    assert b"<h1>" in response.content
