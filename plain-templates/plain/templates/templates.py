"""Expose `plain.forms` helpers as template globals.

Templates rendering a form result use `field_value(form, ContactForm.email)`
and `field_errors(form, ContactForm.email)` to read per-field state. Both
are typed through the `Field[T]` reference, so the cleaned-value type
rides into the template engine where its consumer can use it.
"""

from plain.forms import field_errors, field_value, form_errors

from .jinja import register_template_global

register_template_global(field_value, name="field_value")
register_template_global(field_errors, name="field_errors")
register_template_global(form_errors, name="form_errors")
