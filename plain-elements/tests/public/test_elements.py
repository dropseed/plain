from jinja2 import DictLoader, Environment

from plain.elements.templates import ElementsExtension  # adjust import


def _make_env(templates: dict[str, str]):
    """Spin up a Jinja env with our extension and in‑memory templates."""
    return Environment(
        loader=DictLoader(templates),
        extensions=[ElementsExtension],
        autoescape=False,  # keep it simple for the test
    )


def test_elements_not_enabled():
    env = _make_env(
        {
            "index.html": '<MyElement foo="bar"></MyElement>',
            "elements/MyElement.html": "Hello {{ foo }}",
        }
    )
    out = env.get_template("index.html").render()
    assert out == '<MyElement foo="bar"></MyElement>'


def test_single_element():
    env = _make_env(
        {
            "index.html": '{% use_elements %}<MyElement foo="bar"></MyElement>',
            "elements/MyElement.html": "Hello {{ foo }}",
        }
    )
    out = env.get_template("index.html").render()
    assert out == "Hello bar"


def test_single_element_loop():
    """Some variables, like loop variables, need to be passed explicitly."""

    env = _make_env(
        {
            "index.html": "{% use_elements %}{% for foo in [1] %}<MyElement></MyElement>{% endfor %}",
            "elements/MyElement.html": "Hello {{ foo }}",
        }
    )
    out = env.get_template("index.html").render()
    assert out == "Hello "

    env = _make_env(
        {
            "index.html": "{% use_elements %}{% for foo in [1] %}<MyElement foo={foo}></MyElement>{% endfor %}",
            "elements/MyElement.html": "Hello {{ foo }}",
        }
    )
    out = env.get_template("index.html").render()
    assert out == "Hello 1"


def test_single_self_closing_element():
    env = _make_env(
        {
            "index.html": '{% use_elements %}<MyElement foo="bar" />',
            "elements/MyElement.html": "Hello {{ foo }}",
        }
    )
    out = env.get_template("index.html").render()
    assert out == "Hello bar"


def test_single_namespaced_element():
    env = _make_env(
        {
            "index.html": '{% use_elements %}<admin.MyElement foo="bar"></admin.MyElement>',
            "elements/admin/MyElement.html": "Hello {{ foo }}",
        }
    )
    out = env.get_template("index.html").render()
    assert out == "Hello bar"


def test_element_with_children_and_expr_attr():
    env = _make_env(
        {
            "index.html": (
                "{% use_elements %}"
                "{% set name = 'Dave' %}"
                "<Greeting who={name}>Nice to meet you.</Greeting>"
            ),
            "elements/Greeting.html": "Hi {{ who }}! {{ children }}",
        }
    )
    out = env.get_template("index.html").render().strip()
    assert out == "Hi Dave! Nice to meet you."


def test_nested_elements():
    """<Parent> contains a nested <Child /> element."""
    env = _make_env(
        {
            "index.html": ('{% use_elements %}<Parent><Child foo="bar" /></Parent>'),
            "elements/Parent.html": "PARENT({{ children }})",
            "elements/Child.html": "child={{ foo }}",
        }
    )
    out = env.get_template("index.html").render().strip()
    assert out == "PARENT(child=bar)"


def test_element_as_attr():
    """
    Pass one element as a braced attribute value of another element:
       <Wrapper content={<Content text=\"Yo\" />} />

    Alternative using Jinja set:
       {% set inner %}<Content text=\"Yo\" />{% endset %}
       <Wrapper content={inner} />
    """
    env = _make_env(
        {
            "index.html": (
                "{% use_elements %}"
                '{% set inner %}<Content text="Yo" />{% endset %}'
                "<Wrapper content={inner} />"
            ),
            "elements/Wrapper.html": "WRAP[{{ content }}]",
            "elements/Content.html": "{{ text }}!",
        }
    )
    out = env.get_template("index.html").render().strip()
    assert out == "WRAP[Yo!]"


def test_element_child_variable():
    env = _make_env(
        {
            "index.html": "{% use_elements %}<MyElement>{{ foo }}</MyElement>",
            "elements/MyElement.html": "Hello {{ children }}",
        }
    )
    out = env.get_template("index.html").render({"foo": "bar"})
    assert out == "Hello bar"


# def test_element_child_braced():
#     env = _make_env(
#         {
#             "index.html": '{% use_elements %}<MyElement foo={<Foo />} />',
#             "elements/Foo.html": "bar",
#             "elements/MyElement.html": "Hello {{ foo }}",
#         }
#     )
#     out = env.get_template("index.html").render()
#     assert out == "Hello bar"


# def test_if_wrapping_element():
#     env = _make_env({
#         "index.html": "{% use_elements %}"
#                       "{% if show is defined and show %}<MyElement foo={foo} />{% endif %}",
#         "elements/MyElement.html": "Hello {{ foo }}",
#     })

#     # when show=True, we get the element
#     out = env.get_template("index.html").render(show=True, foo="bar")
#     assert out == "Hello bar"

#     # when show=False (or unset), nothing at all
#     out = env.get_template("index.html").render(show=False, foo="bar")
#     assert out == ""
