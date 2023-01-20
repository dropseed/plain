# forge-stripe

When it's time to implement billing,
Forge comes with a few things to make it even easier to integrate [Stripe](https://stripe.com/).

You can build your own checkout flows if you want,
but these days Stripe provides a nice [hosted checkout page for starting new subscriptions](https://stripe.com/docs/billing/subscriptions/build-subscriptions?ui=checkout),
and a [customer portal for letting people upgrade, cancel, or update payment methods](https://stripe.com/docs/billing/subscriptions/integrating-customer-portal).
You need a couple of server-side views to redirect people to these pages,
but you don't need to build and design these things yourself.

Forge makes this even easier by providing classes you can extend.

## Installation

Add `forgestripe` to the `INSTALLED_APPS`:

```python
# settings.py
INSTALLED_APPS = INSTALLED_APPS + [
    "forgestripe",
]
```

### Environment variables

| Name | Default | Environment | Description |
| ---- | ------- | ----------- | ----------- |
| `STRIPE_SECRET_KEY` | | Any | [Stripe API key](https://stripe.com/docs/keys) |
| `STRIPE_WEBHOOK_SECRET` | | Any | Enables [webhook signature verification](https://stripe.com/docs/webhooks/signatures) |
| `STRIPE_WEBHOOK_PATH` | | Local | Enables `stripe listen` in `forge work` and sets `STRIPE_WEBHOOK_SECRET` |

## Models

The `StripeModel` class is simple,
but useful.
With it you will get a `stripe_id` field,
where you will typically store a Stripe customer ID (like on a Team),
or something more specific like a Stripe subscription or charge ID.

```python
from django.db import models
from forgestripe.models import StripeModel


class Project(StripeModel):
    # stripe_id will be used to tie a Stripe subscription to a project
    name = models.CharField(max_length=255)
```

You will then get a `stripe_object` [cached property](https://docs.djangoproject.com/en/4.1/ref/utils/#django.utils.functional.cached_property) to make it easy to fetch the rest of the data from the Stripe API (the API key will be set for you by Forge).

You can use this in Python code:

```python
print(project.stripe_object)
```

But also in templates:

```html
{% if project.stripe_object %}
    <p>Subscription status: {{ project.stripe_object.status }}</p>
{% else %}
    <p>No subscription</p>
{% endif %}
```

You can store additional Stripe data in your database if you need to,
but in general we recommend fetching from the Stripe API directly unless you frequently need to query or display a specific field.
It's easy to go overboard and store every product, invoice, or charge but in reality you probably don't need to.
Especially if you take advantage of the hosted Stripe checkout and customer portal.

## Views and URLs

There are three Stripe-related views mixins in Forge:

- `StripeCheckoutView` - to create a checkout session and redirect to it (usually to start a new subscription)
- `StripePortalView` - to create a customer portal and redirect to it
- `StripeWebhookView` - to receive webhooks when checkout is completed or subscriptions are updated

### `StripeCheckoutView`

Use `StripeCheckoutView` to create new subscriptions.

```python
from django.urls import path

from . import views

app_name = "projects"

urlpatterns = [
    path(
        "detail/<uuid:uuid>/checkout/",
        views.ProjectCheckoutView.as_view(),
        name="checkout",
    ),
]
```

In your templates,
use a simple form so that it generates a POST request:

```html
<form method="post" action="{% url 'projects:checkout' project.uuid %}">
    {% csrf_token %}
    <button type="submit">Start project subscription</button>
</form>
```

The view is where you will put your custom logic and decide which plans/products to use.
You can use any info from the request itself, your settings, or database:

```python
from forgestripe.views import StripeCheckoutView


class ProjectCheckoutView(ProjectDetailMixin, StripeCheckoutView, generic.DetailView):
    def get_checkout_session_kwargs(self, request):
        project = self.get_object()

        redirect_url = request.build_absolute_uri("/")

        # The "team" will be tied to the actual customer,
        # so we'll get or create that customer now
        team = project.team

        if team.stripe_id:
            customer = team.stripe_id
        else:
            customer = stripe.Customer.create({
                "name": team.name,
                "metadata": {"team_uuid": team.uuid},
            })
            team.stripe_id = customer.id
            team.save()

        return {
            "customer": customer,
            "success_url": redirect_url + "?stripe=success",
            "cancel_url": redirect_url + "?stripe=cancel",
            "mode": "subscription",
            # `client_reference_id` will come back in the webhook,
            # making it easier to look up the associated project
            "client_reference_id": project.uuid,
            "payment_method_types": ["card"],
            "allow_promotion_codes": True,
            "line_items": [
                {
                    "price": settings.STRIPE_PRICE_ID,
                    "quantity": 1,
                }
            ],
        }
```

The `price` field was set in Django settings for this example,
but you could easily pass it in as a `request.POST` field from a template,
or retrieve it from some other source.

When the checkout is completed,
you'll [receive a webhook](#StripeWebhookView) which you can use for "success" processing.

### `StripePortalView`

The `StripePortalView` is used to let users update payment methods, view invoices, modify their subscription, or cancel it.

Usage is very similar to `StripeCheckoutView`,
but you do need to have an existing customer ID to use the `StripePortalView`.


```python
from forgestripe.views import StripePortalView


class TeamPortalView(
    BaseLoggedInViewMixin, StripePortalView, generic.DetailView
):
    def get_portal_session_kwargs(self, request):
        team = self.get_object()

        # Make sure to pass an absolute url to Stripe (https://...)
        return_url = request.build_absolute_uri("/")

        return {
            "customer": team.stripe_id,
            "return_url": return_url,
        }
```

### `StripeWebhookView`

```python
urlpatterns = [
    path("stripe-webhook/", views.StripeWebhook.as_view()),
]
```

In this example we are going to save a specific Stripe subscription ID to a project:

```python
from forgestripe.views import StripeWebhookView


class StripeWebhook(StripeWebhookView):
    def handle_stripe_event(self, event):
        if event.type == "checkout.session.completed":
            # client_reference_id can be set when you use StripeCheckoutView
            project_uuid = event.data.object.client_reference_id
            project = Project.objects.get(uuid=project_uuid)
            project.stripe_id = event.data.object.subscription
            project.save()

        elif event.type == "customer.subscription.deleted":
            subscription_id = event.data.object.id
            project = Project.objects.get(stripe_id=subscription_id)
            project.stripe_id = ""
            project.save()
```

## Templates

We include two template tags that help output Stripe data:

- epoch_to_datetime
- decimal_to_dollars

```html
{% load stripe %}

{{ project.stripe_object.current_period_end|epoch_to_datetime|date:"DATE_FORMAT" }}

${{ project.stripe_object.plan.amount|decimal_to_dollars }}
```

## Testing

The easiest way to test webhooks is to [install the Stripe CLI](https://stripe.com/docs/stripe-cli).
On a Mac, you can install it with Homebrew:

```sh
brew install stripe/stripe-cli/stripe

stripe login
```

Then in your `.env` file, you can add a `STRIPE_WEBHOOK_PATH` (ex. STRIPE_WEBHOOK_PATH=/webhooks/stripe/)
which will be detected by `forge work` and automatically start a `stripe listen` process when you run `forge work`:

Alternatively, you can use [Stripe for VSCode](https://stripe.com/docs/stripe-vscode) or a more generic tunneling tool like [Ngrok](https://ngrok.com/).
