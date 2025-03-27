from plain import models
from plain.utils import timezone


class SessionManager(models.Manager):
    def clear_expired(self):
        """
        Clear expired sessions from the database.
        """
        self.filter(expires_at__lt=timezone.now()).delete()


@models.register_model
class Session(models.Model):
    """
    Plain provides full support for anonymous sessions. The session
    framework lets you store and retrieve arbitrary data on a
    per-site-visitor basis. It stores data on the server side and
    abstracts the sending and receiving of cookies. Cookies contain a
    session ID -- not the data itself.

    The Plain sessions framework is entirely cookie-based. It does
    not fall back to putting session IDs in URLs. This is an intentional
    design decision. Not only does that behavior make URLs ugly, it makes
    your site vulnerable to session-ID theft via the "Referer" header.

    For complete documentation on using Sessions in your code, consult
    the sessions documentation that is shipped with Plain (also available
    on the Plain web site).
    """

    session_key = models.CharField(max_length=40, primary_key=True)
    session_data = models.TextField()
    expires_at = models.DateTimeField()

    objects = SessionManager()

    class Meta:
        indexes = [
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        return self.session_key

    def decoded_data(self):
        from .core import SessionStore

        # A little weird to init an empty one just to use the decode
        return SessionStore()._decode(self.session_data)
