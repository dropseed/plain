from plain.cli.html_validation import validate_html


def messages(html: str) -> list[str]:
    return [e.message for e in validate_html(html)]


def test_clean_html_has_no_errors():
    html = """
    <!DOCTYPE html>
    <html>
      <head><title>Hi</title></head>
      <body>
        <p>Hello</p>
        <ul><li>a</li><li>b</li></ul>
        <img src="x.png" alt="x">
      </body>
    </html>
    """
    assert validate_html(html) == []


def test_unclosed_tag():
    errors = messages("<div><span>oops</div>")
    assert any("Unclosed <span>" in m for m in errors)


def test_mismatched_closing_tag():
    errors = messages("<div>x</section>")
    assert any("Unexpected </section>" in m for m in errors)


def test_void_element_with_closing_tag():
    errors = messages("<p><br></br></p>")
    assert any("</br>" in m and "void element" in m for m in errors)


def test_duplicate_ids():
    errors = messages('<div id="a"></div><span id="a"></span>')
    assert any("Duplicate id='a'" in m for m in errors)


def test_label_for_with_no_match():
    errors = messages('<label for="missing">X</label><input id="other">')
    assert any("<label for='missing'>" in m and "no matching id" in m for m in errors)


def test_label_for_with_match_is_clean():
    assert validate_html('<label for="email">X</label><input id="email">') == []


def test_label_for_can_match_id_appearing_later():
    # IDs are document-wide so a label may precede the input it refers to.
    assert validate_html('<label for="email">X</label><input id="email">') == []


def test_nested_anchor():
    errors = messages('<a href="/x"><a href="/y">click</a></a>')
    assert any("Nested <a>" in m for m in errors)


def test_button_inside_anchor():
    errors = messages('<a href="/x"><button>Go</button></a>')
    assert any("<button> inside <a>" in m for m in errors)


def test_implicit_li_close_is_not_an_error():
    # <li> auto-closes the previous <li>; this is valid HTML5.
    assert validate_html("<ul><li>a<li>b</ul>") == []


def test_implicit_p_close_is_not_an_error():
    assert validate_html("<div><p>a<p>b</div>") == []


def test_implicit_table_close_is_not_an_error():
    html = "<table><tr><td>a<td>b<tr><td>c<td>d</table>"
    assert validate_html(html) == []


def test_self_closing_void_is_clean():
    assert validate_html("<p>hi<br/>there</p>") == []


def test_script_content_is_not_parsed_as_html():
    # The HTML parser treats <script> as raw text — JS containing < should
    # not produce phantom validation errors.
    html = "<script>if (1 < 2) { console.log('<div>'); }</script>"
    assert validate_html(html) == []


def test_implicit_html_head_body_unclosed_is_clean():
    # Documents commonly omit closing </html>/</body>; don't flag them.
    assert validate_html("<html><body><p>hi</p>") == []
