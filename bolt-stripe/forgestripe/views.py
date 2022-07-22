import stripe
from django.http import HttpResponse, HttpResponseRedirect
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from . import settings


class StripePortalView(View):
    def post(self, request, *args, **kwargs):
        return self.get_redirect_response(request)

    def get_redirect_response(self, request):
        session = self.create_portal_session(request)
        return HttpResponseRedirect(session.url, status=303)

    def create_portal_session(self, request):
        return stripe.billing_portal.Session.create(
            **self.get_portal_session_kwargs(request)
        )

    def get_portal_session_kwargs(self, request):
        # https://stripe.com/docs/api/customer_portal/sessions/create
        raise NotImplementedError


class StripeCheckoutView(View):
    def post(self, request, *args, **kwargs):
        return self.get_redirect_response(request)

    def get_redirect_response(self, request):
        session = self.create_checkout_session(request)
        return HttpResponseRedirect(session.url, status=303)

    def create_checkout_session(self, request):
        return stripe.checkout.Session.create(
            **self.get_checkout_session_kwargs(request)
        )

    def get_checkout_session_kwargs(self, request):
        # https://stripe.com/docs/api/checkout/sessions/create
        raise NotImplementedError


@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(View):
    def post(self, request, *args, **kwargs):
        try:
            event = stripe.Webhook.construct_event(
                request.body,
                request.META["HTTP_STRIPE_SIGNATURE"],
                settings.STRIPE_WEBHOOK_SECRET(),
            )
        except ValueError as e:
            # Invalid payload
            raise e
        except stripe.error.SignatureVerificationError as e:
            # Invalid signature
            raise e

        self.handle_stripe_event(event)

        return HttpResponse(status=200)

    def handle_stripe_event(self, event):
        # if event.type == "payment_intent.succeeded":
        #     payment_intent = event.data.object  # contains a stripe.PaymentIntent
        #     # Then define and call a method to handle the successful payment intent.
        #     # handle_payment_intent_succeeded(payment_intent)
        # elif event.type == "payment_method.attached":
        #     payment_method = event.data.object  # contains a stripe.PaymentMethod
        #     # Then define and call a method to handle the successful attachment of a PaymentMethod.
        #     # handle_payment_method_attached(payment_method)
        # # ... handle other event types
        # else:
        #     print("Unhandled event type {}".format(event.type))
        raise NotImplementedError
