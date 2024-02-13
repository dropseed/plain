import unicodedata

from bolt.db import models
from bolt.packages import packages
from bolt.runtime import settings
from bolt.utils import timezone
from bolt.utils.crypto import salted_hmac

from .validators import UnicodeUsernameValidator


def update_last_login(sender, user, **kwargs):
    """
    A signal receiver which updates the last_login date for
    the user logging in.
    """
    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])


class UserManager(models.Manager):
    use_in_migrations = True

    def create_user(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        if not username:
            raise ValueError("The given username must be set")
        email = self.normalize_email(email)
        # Lookup the real model class from the global app registry so this
        # manager method can be used in migrations. This is fine because
        # managers are by definition working on the real model.
        GlobalUserModel = packages.get_model(
            self.model._meta.package_label, self.model._meta.object_name
        )
        username = GlobalUserModel.normalize_username(username)
        user = self.model(username=username, email=email, **extra_fields)
        # user.password = hash_password(password)
        user.save(using=self._db)
        return user

    @classmethod
    def normalize_email(cls, email):
        """
        Normalize the email address by lowercasing the domain part of it.
        """
        email = email or ""
        try:
            email_name, domain_part = email.strip().rsplit("@", 1)
        except ValueError:
            pass
        else:
            email = email_name + "@" + domain_part.lower()
        return email

    def get_by_natural_key(self, username):
        return self.get(**{self.model.USERNAME_FIELD: username})


class AbstractUser(models.Model):
    """
    An abstract base class implementing a fully featured User model with
    admin-compliant permissions.

    Username and password are required. Other fields are optional.
    """

    username_validator = UnicodeUsernameValidator()

    username = models.CharField(
        "username",
        max_length=150,
        unique=True,
        help_text="Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.",
        validators=[username_validator],
        error_messages={
            "unique": "A user with that username already exists.",
        },
    )
    email = models.EmailField("email address", blank=True)
    is_staff = models.BooleanField(
        "staff status",
        default=False,
        help_text="Designates whether the user can log into this admin site.",
    )
    date_joined = models.DateTimeField("date joined", default=timezone.now)
    last_login = models.DateTimeField("last login", blank=True, null=True)

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email"]
    SESSION_HASH_FIELD = ""

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"
        abstract = True

    def clean(self):
        setattr(self, self.USERNAME_FIELD, self.normalize_username(self.get_username()))
        self.email = self.__class__.objects.normalize_email(self.email)

    def __str__(self):
        return self.get_username()

    def get_username(self):
        """Return the username for this User."""
        return getattr(self, self.USERNAME_FIELD)

    def get_session_auth_hash(self):
        """
        Return an HMAC of the password field.
        """
        return self._get_session_auth_hash()

    def get_session_auth_fallback_hash(self):
        for fallback_secret in settings.SECRET_KEY_FALLBACKS:
            yield self._get_session_auth_hash(secret=fallback_secret)

    def _get_session_auth_hash(self, secret=None):
        key_salt = "bolt.auth.models.AbstractBaseUser.get_session_auth_hash"
        return salted_hmac(
            key_salt,
            getattr(self, self.SESSION_HASH_FIELD),
            secret=secret,
            algorithm="sha256",
        ).hexdigest()

    @classmethod
    def normalize_username(cls, username):
        return (
            unicodedata.normalize("NFKC", username)
            if isinstance(username, str)
            else username
        )
