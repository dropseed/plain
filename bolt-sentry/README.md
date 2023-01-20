# forge-sentry

[Sentry](https://sentry.io/) is an error monitoring service that we think has a great Django integration.
It allows you to debug production errors and also has some performance monitoring features that can be enabled.

![image](https://user-images.githubusercontent.com/649496/213781768-182322e6-edf0-4d98-8b37-ab564ef23c3b.png)

## Installation

```python
# settings.py
INSTALLED_APPS = INSTALLED_APPS + [
  "forgesentry",
]

# Enable the error page feedback widget
MIDDLEWARE = MIDDLEWARE + [
  "forgesentry.SentryFeedbackMiddleware",
]
```

In your `base.html`, load `sentry` and include the `sentry_js` tag:

```html
<!-- base.html -->
{% load sentry %}
<!doctype html>
<html lang="en">
  <head>
      ...
      {% sentry_js %}
  </head>
  <body>
      ...
  </body>
</html>
```

To enable Sentry in production, add the `SENTRY_DSN` to your Heroku app:

```sh
heroku config:set SENTRY_DSN=<your-DSN>
```

## Configuration

By default, you'll get both Python (backend) and JavaScript (frontend) error reporting that includes PII (user ID, username, and email).
You can further tweak the Sentry settings with these environment variables:

- `SENTRY_RELEASE` - the commit sha by default
- `SENTRY_ENVIRONMENT` - "production" by default
- `SENTRY_PII_ENABLED` - `true` by default, set to `false` to disable sending PII
- `SENTRY_JS_ENABLED` - `true` by default, set to `false` to disable JS error reporting

| Name | Default | Environment | Description |
| ---- | ------- | ----------- | ----------- |
| `SENTRY_DSN` | | Any | [Sentry DSN](https://docs.sentry.io/product/sentry-basics/dsn-explainer/) |
| `SENTRY_RELEASE` | `HEROKU_SLUG_COMMIT` | Any | [Sentry release tag](https://docs.sentry.io/product/releases/) |
| `SENTRY_ENVIRONMENT` | production | Any | [Sentry environment tag](https://docs.sentry.io/product/sentry-basics/environments/) |
| `SENTRY_PII_ENABLED` | true | Any | Send username/email with Sentry errors |
| `SENTRY_JS_ENABLED` | true | Any | Enables JS error monitoring (requiers `{% sentry_js %}` tag too) |

## Error page feedback widget

By adding the `SentryFeedbackMiddleware` to your `MIDDLEWARE`,
your `500.html` server error page will include the Sentry feedback widget:

![image](https://user-images.githubusercontent.com/649496/213781811-418500fa-b7f8-43f1-8d28-4fde1bfe2b4b.png)
