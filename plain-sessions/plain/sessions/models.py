from plain import models


class SessionManager(models.Manager):
    use_in_migrations = True

    def encode(self, session_dict):
        """
        Return the given session dictionary serialized and encoded as a string.
        """
        session_store_class = self.model.get_session_store_class()
        return session_store_class().encode(session_dict)

    def save(self, session_key, session_dict, expire_date):
        s = self.model(session_key, self.encode(session_dict), expire_date)
        if session_dict:
            s.save()
        else:
            s.delete()  # Clear sessions with no data.
        return s


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
    expire_date = models.DateTimeField()

    objects = SessionManager()

    class Meta:
        indexes = [
            models.Index(fields=["expire_date"]),
        ]

    def __str__(self):
        return self.session_key

    @classmethod
    def get_session_store_class(cls):
        from plain.sessions.backends.db import SessionStore

        return SessionStore

    def get_decoded(self):
        session_store_class = self.get_session_store_class()
        return session_store_class().decode(self.session_data)
