import stripe
from django.db import models
from django.utils.functional import cached_property


class StripeModel(models.Model):
    stripe_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)

    class Meta:
        abstract = True

    @cached_property
    def stripe_object(self):
        """A cached property that is useful when rendering templates"""
        return self.get_stripe_object()

    def get_stripe_object(self):
        """Automatically get the Stripe object based on the stripe_id prefix"""
        if not self.stripe_id:
            return None

        if self.stripe_id.startswith("cus_"):
            return stripe.Customer.retrieve(self.stripe_id)

        if self.stripe_id.startswith("sub_"):
            return stripe.Subscription.retrieve(self.stripe_id)

        raise Exception("Unknown stripe_id prefix")
