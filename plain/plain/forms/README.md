# Forms

**HTML form handling and validation.**

The `Form` and `Field` classes help output, parse, and validate form data from an HTTP request. Unlike other frameworks, the HTML inputs are not rendered automatically, though there are some helpers for you to do your own rendering.

With forms, you will typically use one of the built-in view classes to tie everything together.

```python
from plain import forms
from plain.views import FormView


class ContactForm(forms.Form):
    email = forms.EmailField()
    message = forms.CharField()


class ContactView(FormView):
    form_class = ContactForm
    template_name = "contact.html"
```

Then in your template, you can render the form fields.

```html
{% extends "base.html" %}

{% block content %}

<form method="post">
    {{ csrf_input }}

    <!-- Render general form errors -->
    {% for error in form.non_field_errors %}
    <div>{{ error }}</div>
    {% endfor %}

    <div>
        <label for="{{ form.email.html_id }}">Email</label>
        <input
            required
            type="email"
            name="{{ form.email.html_name }}"
            id="{{ form.email.html_id }}"
            value="{{ form.email.value }}">

        {% if form.email.errors %}
        <div>{{ form.email.errors|join(', ') }}</div>
        {% endif %}
    </div>

    <div>
        <label for="{{ form.message.html_id }}">Message</label>
        <textarea
            required
            rows="10"
            name="{{ form.message.html_name }}"
            id="{{ form.message.html_id }}">{{ form.message.value }}</textarea>

        {% if form.message.errors %}
        <div>{{ form.message.errors|join(', ') }}</div>
        {% endif %}
    </div>

    <button type="submit">Submit</button>
</form>

{% endblock %}
```

With manual form rendering, you have full control over the HTML classes, attributes, and JS behavior. But in large applications the form rendering can become repetitive. You will often end up re-using certain patterns in your HTML which can be abstracted away using Jinja [includes](https://jinja.palletsprojects.com/en/stable/templates/#include), [macros](https://jinja.palletsprojects.com/en/stable/templates/#macros), or [plain.elements](/plain-elements/README.md).
