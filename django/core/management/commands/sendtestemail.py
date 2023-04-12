import socket

from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Sends a test email to the email addresses specified as arguments."
    missing_args_message = (
        "You must specify some email recipients, or pass the --managers or --admin "
        "options."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "email",
            nargs="*",
            help="One or more email addresses to send a test email to.",
        )

    def handle(self, *args, **kwargs):
        subject = "Test email from %s on %s" % (socket.gethostname(), timezone.now())

        send_mail(
            subject=subject,
            message="If you're reading this, it was successful.",
            from_email=None,
            recipient_list=kwargs["email"],
        )
