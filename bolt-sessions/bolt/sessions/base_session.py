"""
This module allows importing AbstractBaseSession even
when bolt.sessions is not in INSTALLED_APPS.
"""
from django.db import models


class BaseSessionManager(models.Manager):
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


class AbstractBaseSession(models.Model):
    session_key = models.CharField("session key", max_length=40, primary_key=True)
    session_data = models.TextField("session data")
    expire_date = models.DateTimeField("expire date", db_index=True)

    objects = BaseSessionManager()

    class Meta:
        abstract = True
        verbose_name = "session"
        verbose_name_plural = "sessions"

    def __str__(self):
        return self.session_key

    @classmethod
    def get_session_store_class(cls):
        raise NotImplementedError

    def get_decoded(self):
        session_store_class = self.get_session_store_class()
        return session_store_class().decode(self.session_data)
