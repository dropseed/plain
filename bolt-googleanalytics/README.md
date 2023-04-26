# forge-googleanalytics

The new [Google Analytics](https://marketingplatform.google.com/about/analytics/) is a free,
more privacy-focused version of the same service people have been using for years.
Of course, you don't have to use it!
Integrating a different analytics tool is pretty easy using the standard methods.
But if you don't know where to start and want *some* kind of analytics insights,
we still think Google Analytics is a good starting point.


## Installation

```python
# settings.py
INSTALLED_APPS = INSTALLED_APPS + [
  "forgegoogleanalytics",
]
```

Then get a "web" stream measurement ID and save it to the environment variables:

```sh
# (Terminal)
# For development
echo "GOOGLE_ANALYTICS_MEASUREMENT_ID=<your-tracking-id>" >> .env

# For production
heroku config:set GOOGLEANALYTICS_MEASUREMENT_ID=<your-tracking-id>
```

| Name | Default | Environment | Description |
| ---- | ------- | ----------- | ----------- |
| `GOOGLEANALYTICS_MEASUREMENT_ID` | | production | |

## Client-side events

To capture pageview events and use the Google Analytics client-side library,
insert the JS tag into your base template:

```html
<!-- base.template.html -->
{% load googleanalytics %}
<!doctype html>
<html lang="en">
  <head>
    ...
    {% googleanalytics_js %}
  </head>
```

When users are logged in, the `user.pk` will automatically be added to the tracking code.

If `settings.DEBUG` is `True`, the client-side tracking code will not be included.


## Server-side events

This package also includes support for the GA4 [Measurement Protocol](https://developers.google.com/analytics/devguides/collection/protocol/ga4).
You can use this to send custom events from the backend/Python code.

We suggest using the [event builder](https://ga-dev-tools.web.app/ga4/event-builder/) to decide which event name and parameters to use.
If there is a standard event name that matches your use case, it's recommended that you use it (the builder will suggest params to go with it).
If not, you can always send a custom event with custom params, but you may have to do more work on the reporting side.

First, get an API secret from your data stream settings and add it as an environment variable:

```sh
# (Terminal)
# For development
echo "GOOGLEANALYTICS_API_SECRET=<your-api-secret>" >> .env

# For production
heroku config:set GOOGLEANALYTICS_API_SECRET=<your-api-secret>
```

Then use the `GoogleAnalyticsEvent` class to send events from your Python code:

```python
# models.py
from forgegoogleanalytics.events import GoogleAnalyticsEvent


class ExampleModel(models.Model):
  user = models.ForeignKey(User, on_delete=models.CASCADE)

  def example_method(self):
    # Do something...
    # And send a custom event
    GoogleAnalyticsEvent(
      name="custom_event_name",
      params={
        "custom_param_1": "custom_param_value_1",
        "custom_param_2": "custom_param_value_2",
      }
    ).send(user=self.user)
```

### Associating users

A user can be tied to an event by either passing the `request` parameter to `send`:

```python
# (Python)
from forgegoogleanalytics.events import GoogleAnalyticsEvent


GoogleAnalyticsEvent(
  name="custom_event_name",
  params={
    "custom_param_1": "custom_param_value_1",
    "custom_param_2": "custom_param_value_2",
  }
).send(request=request)
```

Or by passing an explicit `user` during `send`:

```python
# (Python)
from forgegoogleanalytics.events import GoogleAnalyticsEvent


GoogleAnalyticsEvent(
  name="custom_event_name",
  params={
    "custom_param_1": "custom_param_value_1",
    "custom_param_2": "custom_param_value_2",
  }
).send(user=user)
```

### Errors

In production, [GA4 will not raise an error for invalid events](https://developers.google.com/analytics/devguides/collection/protocol/ga4/validating-events?client_type=gtag).
This is why it's important to [validate your events before enabling them in production](#validating-events).

If there is some kind of API communication error,
it will silently fail to send and be logged with `logger.exception`,
which will be captured by tools like [Sentry](/docs/forge-sentry/) without interrupting the user experience.

### Validating events

When sending live events, the GA4 endpoint will not throw an error if the event name or parameters are invalid.
You have to test these ahead of time!
This is another reason to use the [event builder](https://ga-dev-tools.web.app/ga4/event-builder/),
but when you are working locally we will automatically send events to the ["debug" validation endpoint](https://developers.google.com/analytics/devguides/collection/protocol/ga4/validating-events?client_type=gtag) and raise an error if they are invalid.

```python
# (Python)
# Validation will occur automatically with settings.DEBUG,
# but you can also force enable or disable it by passing True/False
#
# Validate the event regardless of settings.DEBUG
GoogleAnalyticsEvent(
  name="custom_event_name",
  params={
    "custom_param_1": "custom_param_value_1",
    "custom_param_2": "custom_param_value_2",
  }
).send(validate=True)

# Send a live event, even if settings.DEBUG is enabled
GoogleAnalyticsEvent(
  name="custom_event_name",
  params={
    "custom_param_1": "custom_param_value_1",
    "custom_param_2": "custom_param_value_2",
  }
).send(validate=False)
```

The list of event naming rules limitations can be found here: [GA4 Event Limitations](https://developers.google.com/analytics/devguides/collection/protocol/ga4/sending-events?client_type=gtag#limitations).

### Batch sending

[Up to 25 events can be sent at once](https://developers.google.com/analytics/devguides/collection/protocol/ga4/sending-events?client_type=gtag#limitations) by putting them into a list and using `send_events`:

```python
# (Python)
from forgegoogleanalytics.events import GoogleAnalyticsEvent, send_events

events = [
  GoogleAnalyticsEvent(...),
  GoogleAnalyticsEvent(...),
  GoogleAnalyticsEvent(...),
]

# With a request
send_events(events, request=request)

# With an explicit user
send_events(events, user=user)
```
