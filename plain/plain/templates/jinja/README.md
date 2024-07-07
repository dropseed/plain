# Jinja

Templates can be stored inside `INSTALLED_PACKAGES` (ex. `app/<pkg>/templates`) or in the `templates` directory at the root of your project (ex. `app/templates`).

### App templates

You `app/templates` will typically have things like `base.html`,
which the whole app depends on.

### Package templates

Since all template directories are effectively "merged" together,
packages will typically namespace their own templates such as `app/users/templates/users/delete.html`.

## Jinja

There is a default set of globals, filters, and extensions.

## Default globals

- `static` - a function that returns the URL for a static file
- `url` - a function that returns the URL for a view
- `Paginator` - the Plain Paginator class

## Default filters

- `strftime` - `datetime.datetime.strftime`
- `strptime` - `datetime.datetime.strptime`
- `localtime` - convert a datetime to the activated time zone (or a given time zone)
- `timeuntil` - human readable time until a date
- `timesince` - human readable time since a date
- `json_script` - serialize a value as JSON and wrap it in a `<script>` tag
- `islice` - `itertools.islice` which is a slice for `dict.items()`

## Default extensions

- `jinja2.ext.debug`
- `jinja2.ext.loopcontrols`

## Default request context

Each request is rendered with a `context`.
This will include the [default globals](#default-globals),
any app or project globals,
as well as the `get_template_context()` from your view.

When a view is rendered,
the default context includes the `request` itself,
as well as a `csrf_input` (and `csrf_token`) to be used in forms.

## Extending with a root `jinja.py`

You can customize the Jinja environment by adding a `jinja.py` module to your app root.
This works just like [extending with packages](#extending-with-packages),
where you can define `filters`, `globals`, and `extensions`.

## Extending with Packages

Any of your `INSTALLED_PACKAGES` can customize Jinja by adding a `jinja.py` module.

To put it simply, the three things you can "export" from this module are:
- `filters` - functions that can be used in templates
- `globals` - variables that can be used in templates
- `extensions` - a list of custom Jinja extensions to install

All you need to do is define a variable with the correct name:

```python
# <appname>/jinja.py
from jinja2 import Extension


def add_exclamation(obj):
    return obj + "!"


class MyExtension(Extension):
    # ...
    pass

# Filters are used on a variable with a pipe,
# like {{ variable|add_exclamation }}.
# You can use these to add new features to all variables.
filters = {
    "add_exclamation": add_exclamation,
}

# Globals are essentially variables that are available in all templates.
# But you can also include functions here, which can be called in the template like {{ a_callable_global() }}.
globals = {
    "my_global": "my global value",
}

# Extensions are classes that can add new features to the Jinja environment.
extensions = [
    MyExtension,
]
```

TODO - when to use a global function vs a filter

## Time zone aware output

TODO - example middleware, `|localtime` filter

## Settings

Most Jinja customization happens in `jinja.py` at the root of your app or in `INSTALLED_PACKAGES`.
But if you need to further customize the environment,
you can define your own callable which will be used to create the Jinja environment.

```python
# app/settings.py
JINJA_ENVIRONMENT = "myjinja.create_environment"
```

```python
# app/myjinja.py
from jinja2 import Environment


def create_environment():
    return Environment(
        # ...
    )
```

## HTML Components

- `{% include %}` shorthand
- strictly html, no python classes to back them
- react-inspired syntax
- react components in the future? live-wire style? script tags?

## Background

Django has two options for template languages: the [Django template language (DTL)](https://docs.djangoproject.com/en/4.2/topics/templates/) and [Jinja templates](https://jinja.palletsprojects.com/en/3.1.x/).

I'm not an expert on the history here,
but my understanding is that the DTL inspired Jinja,
and my guess is that Jinja then became so popular that they added support for it back to Django.
And now there are two options.

The two are pretty similar,
but one of the biggest differences that I care about is the fact that in Django templates,
you don't use `()` to call functions.
Which means that you can't call any functions that take arguments.

Sometimes, this can lead you to create better, simpler templates.
But other times,
it just forces you to find silly workarounds like creating custom template tags/filters or additional model methods,
just because you can't pass an argument in your template.

```python
class MyModel(models.Model):
    def foo(self, bar=None):
        return f"foo {bar}"
```

```html
<!-- django-template.html -->
{{ my_model.foo }}
```

This is not a problem in Jinja.

```html
<!-- jinja-template.html -->
{{ my_model.foo(bar) }}
```

It's also weird to explain to new users of Django/Python that you "use the same `foo()` method, but leave off the `()`, which would not do what you want in a Python shell or anywhere else..."

And even as someone who has understood how this works for a long time,
it's still really annoying when you want to search across your entire project for usage of a specific method,
but you can't simply search for `.foo(` because it won't pick it up in the template code.

Plain simply removes the Django Template Language (DTL) and only supports Jinja templates.
Nobody uses Django templates outside of Django, but people encounter Jinja in lots of other tools.
I think focusing on Jinja is a better move as an independent templating ecosystem.
This is also a change that I doubt Django would ever be able to make,
even if they wanted to.

https://github.com/mitsuhiko/minijinja

- request.user, not user
- jinja error if you try to render a callable?
- manager method example?

### `request.user` vs `user`

Django auth does this neat thing where it automatically [puts a `"user"` in your template context](https://github.com/django/django/blob/42b4f81e6efd5c4587e1207a2ae3dd0facb1436f/django/contrib/auth/context_processors.py#L65),
in addition to `request.user`.

I've seen this cause confusion/conflicts for templates that are trying to render a specific user...
Plain doesn't do this -- if you want the current logged in user, use `request.user`.

```html
{% if request.user.is_authenticated %}

{% endif %}
```

### StrictUndefined

Another feature of Django templates is that,
by default,
you don't get any kind of error if you try to render a variable that doesn't exist.

This can be handy for simple kinds of template logic,
but it can also be the source of some pretty big rendering bugs.

Plain runs Jinja with `strict_undefined=True` by default,
so you get a big, loud error if you try to render a variable that doesn't exist.

You can use the `|default()` filter to provide a default value if you want to allow a variable to be undefined,
or check `{% if variable is defined %}` if you want to conditionally render something.

```html
{{ variable|default('default value') }}
```

```html
{% if variable is defined %}
    {{ variable }}
{% endif %}
```
