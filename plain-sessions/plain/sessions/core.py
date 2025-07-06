import string
from datetime import timedelta

from plain.models import transaction
from plain.runtime import settings
from plain.utils import timezone
from plain.utils.crypto import get_random_string


class SessionStore:
    """
    The actual session object that gets attached to a request,
    backed by the underlying Session model for the storage.
    """

    __not_given = object()

    def __init__(self, session_key=None):
        self.session_key = session_key
        self.accessed = False
        self.modified = False

        # Lazy import
        from .models import Session

        self._model = Session

    def __contains__(self, key):
        return key in self._session

    def __getitem__(self, key):
        return self._session[key]

    def __setitem__(self, key, value):
        self._session[key] = value
        self.modified = True

    def __delitem__(self, key):
        del self._session[key]
        self.modified = True

    def get(self, key, default=None):
        return self._session.get(key, default)

    def pop(self, key, default=__not_given):
        self.modified = self.modified or key in self._session
        args = () if default is self.__not_given else (default,)
        return self._session.pop(key, *args)

    def setdefault(self, key, value):
        if key in self._session:
            return self._session[key]
        else:
            self.modified = True
            self._session[key] = value
            return value

    def update(self, dict_):
        self._session.update(dict_)
        self.modified = True

    def has_key(self, key):
        return key in self._session

    def keys(self):
        return self._session.keys()

    def values(self):
        return self._session.values()

    def items(self):
        return self._session.items()

    def clear(self):
        # To avoid unnecessary persistent storage accesses, we set up the
        # internals directly (loading data wastes time, since we are going to
        # set it to an empty dict anyway).
        self._session_cache = {}
        self.accessed = True
        self.modified = True

    def is_empty(self):
        "Return True when there is no session_key and the session is empty."
        try:
            return not self.session_key and not self._session_cache
        except AttributeError:
            return True

    def _get_new_session_key(self):
        "Return session key that isn't being used."
        while True:
            session_key = get_random_string(32, string.ascii_lowercase + string.digits)
            if not self._model.objects.filter(session_key=session_key).exists():
                return session_key

    def _get_or_create_session_key(self):
        if self.session_key is None:
            self.session_key = self._get_new_session_key()
        return self.session_key

    def _get_session(self, no_load=False):
        """
        Lazily load session from storage (unless "no_load" is True, when only
        an empty dict is stored) and store it in the current instance.
        """
        self.accessed = True
        try:
            return self._session_cache
        except AttributeError:
            if self.session_key is None or no_load:
                self._session_cache = {}
            else:
                self._session_cache = self._load()
        return self._session_cache

    _session = property(_get_session)

    def flush(self):
        """
        Remove the current session data from the database and regenerate the
        key.
        """
        self.clear()
        try:
            self._model.objects.get(session_key=self.session_key).delete()
        except self._model.DoesNotExist:
            pass
        self.session_key = None

    def cycle_key(self):
        """
        Create a new session key, while retaining the current session data.
        """
        data = self._session
        key = self.session_key
        self.create()
        self._session_cache = data
        if key:
            try:
                self._model.objects.get(session_key=key).delete()
            except self._model.DoesNotExist:
                pass

    def _load(self):
        try:
            session = self._model.objects.get(
                session_key=self.session_key, expires_at__gt=timezone.now()
            )
        except self._model.DoesNotExist:
            self.session_key = None
            session = None

        return session.session_data if session else {}

    def create(self):
        self.session_key = self._get_new_session_key()
        data = self._get_session(no_load=True)
        with transaction.atomic():
            self._model.objects.create(
                session_key=self.session_key,
                session_data=data,
                expires_at=timezone.now()
                + timedelta(seconds=settings.SESSION_COOKIE_AGE),
            )
        self.modified = True

    def save(self):
        """
        Save the current session data to the database using update_or_create.
        """
        data = self._get_session(no_load=False)

        with transaction.atomic():
            _, created = self._model.objects.update_or_create(
                session_key=self._get_or_create_session_key(),
                defaults={
                    "session_data": data,
                    "expires_at": timezone.now()
                    + timedelta(seconds=settings.SESSION_COOKIE_AGE),
                },
            )

        if created:
            self.modified = True
