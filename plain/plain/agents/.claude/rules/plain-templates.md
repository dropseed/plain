---
paths:
  - "**/*.html"
---

# Templates

## Long Lines

When an HTML tag has many attributes or a long class list, break it into multiple lines with each attribute indented. The closing `>` goes on its own line.

**Good:**

```html
<div
    class="flex items-center justify-between gap-4 rounded-lg border bg-white p-4 shadow-sm"
    data-active="{{ is_active }}"
>
    ...
</div>
```

**Avoid:**

```html
<div class="flex items-center justify-between gap-4 rounded-lg border bg-white p-4 shadow-sm" data-active="{{ is_active }}">...</div>
```

## Forms

Forms are headless. Render each field by name:

```html
<form method="post">
    <div>
        <label for="{{ form.email.html_id }}">Email</label>
        <input
            type="email"
            name="{{ form.email.html_name }}"
            id="{{ form.email.html_id }}"
            value="{{ form.email.value }}"
        >
        {% for error in form.email.errors %}
        <p>{{ error }}</p>
        {% endfor %}
    </div>
    <button type="submit">Submit</button>
</form>
```

Each bound field provides: `html_name`, `html_id`, `value`, `errors`, `field`, `initial`.

## CSRF

Plain uses automatic header-based CSRF protection (Sec-Fetch-Site). No tokens are needed in templates.

## Template Query Safety

### Never call `.query` in templates

All data should come from the view context. If you see `.query.all()` or `.query.filter()` in a template, move it to the view.

```html
{# Bad — triggers queries in the template #}
{% for post in user.posts.query.all() %}
    {{ post.title }}
{% endfor %}

{# Good — data prepared in the view #}
{% for post in user_posts %}
    {{ post.title }}
{% endfor %}
```
