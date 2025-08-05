from typing import TYPE_CHECKING

from plain import models
from plain.auth import get_user_model
from plain.exceptions import ValidationError
from plain.models import transaction
from plain.models.db import IntegrityError, OperationalError, ProgrammingError
from plain.preflight import Error
from plain.runtime import SettingsReference
from plain.utils import timezone

from .exceptions import OAuthUserAlreadyExistsError

if TYPE_CHECKING:
    from .providers import OAuthToken, OAuthUser


# TODO preflight check for deploy that ensures all provider keys in db are also in settings?


@models.register_model
class OAuthConnection(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    user = models.ForeignKey(
        SettingsReference("AUTH_USER_MODEL"),
        on_delete=models.CASCADE,
        related_name="oauth_connections",
    )

    # The key used to refer to this provider type (in settings)
    provider_key = models.CharField(max_length=100)

    # The unique ID of the user on the provider's system
    provider_user_id = models.CharField(max_length=100)

    # Token data
    access_token = models.CharField(max_length=2000)
    refresh_token = models.CharField(max_length=2000, required=False)
    access_token_expires_at = models.DateTimeField(required=False, allow_null=True)
    refresh_token_expires_at = models.DateTimeField(required=False, allow_null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider_key", "provider_user_id"],
                name="plainoauth_oauthconnection_unique_provider_key_user_id",
            )
        ]
        ordering = ("provider_key",)

    def __str__(self):
        return f"{self.provider_key}[{self.user}:{self.provider_user_id}]"

    def refresh_access_token(self) -> None:
        from .providers import OAuthToken, get_oauth_provider_instance

        provider_instance = get_oauth_provider_instance(provider_key=self.provider_key)
        oauth_token = OAuthToken(
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            access_token_expires_at=self.access_token_expires_at,
            refresh_token_expires_at=self.refresh_token_expires_at,
        )
        refreshed_oauth_token = provider_instance.refresh_oauth_token(
            oauth_token=oauth_token
        )
        self.set_token_fields(refreshed_oauth_token)
        self.save()

    def set_token_fields(self, oauth_token: "OAuthToken"):
        self.access_token = oauth_token.access_token
        self.refresh_token = oauth_token.refresh_token
        self.access_token_expires_at = oauth_token.access_token_expires_at
        self.refresh_token_expires_at = oauth_token.refresh_token_expires_at

    def set_user_fields(self, oauth_user: "OAuthUser"):
        self.provider_user_id = oauth_user.provider_id

    def access_token_expired(self) -> bool:
        return (
            self.access_token_expires_at is not None
            and self.access_token_expires_at < timezone.now()
        )

    def refresh_token_expired(self) -> bool:
        return (
            self.refresh_token_expires_at is not None
            and self.refresh_token_expires_at < timezone.now()
        )

    @classmethod
    def get_or_create_user(
        cls, *, provider_key: str, oauth_token: "OAuthToken", oauth_user: "OAuthUser"
    ) -> "OAuthConnection":
        try:
            connection = cls.objects.get(
                provider_key=provider_key,
                provider_user_id=oauth_user.provider_id,
            )
            connection.set_token_fields(oauth_token)
            connection.save()
            return connection
        except cls.DoesNotExist:
            with transaction.atomic():
                # If email needs to be unique, then we expect
                # that to be taken care of on the user model itself
                try:
                    user = get_user_model()(
                        **oauth_user.user_model_fields,
                    )
                    user.save()
                except (IntegrityError, ValidationError):
                    raise OAuthUserAlreadyExistsError()

                return cls.connect(
                    user=user,
                    provider_key=provider_key,
                    oauth_token=oauth_token,
                    oauth_user=oauth_user,
                )

    @classmethod
    def connect(
        cls,
        *,
        user,
        provider_key: str,
        oauth_token: "OAuthToken",
        oauth_user: "OAuthUser",
    ) -> "OAuthConnection":
        """
        Connect will either create a new connection or update an existing connection
        """
        try:
            connection = cls.objects.get(
                user=user,
                provider_key=provider_key,
                provider_user_id=oauth_user.provider_id,
            )
        except cls.DoesNotExist:
            # Create our own instance (not using get_or_create)
            # so that any created signals contain the token fields too
            connection = cls(
                user=user,
                provider_key=provider_key,
                provider_user_id=oauth_user.provider_id,
            )

        connection.set_user_fields(oauth_user)
        connection.set_token_fields(oauth_token)
        connection.save()

        return connection

    @classmethod
    def check(cls, **kwargs):
        """
        A system check for ensuring that provider_keys in the database are also present in settings.

        Note that the --database flag is required for this to work:
          plain check --database default
        """
        errors = super().check(**kwargs)

        database = kwargs.get("database", False)
        if not database:
            return errors

        from .providers import get_provider_keys

        try:
            keys_in_db = set(
                cls.objects.values_list("provider_key", flat=True).distinct()
            )
        except (OperationalError, ProgrammingError):
            # Check runs on plain migrate, and the table may not exist yet
            # or it may not be installed on the particular database intentionally
            return errors

        keys_in_settings = set(get_provider_keys())

        if keys_in_db - keys_in_settings:
            errors.append(
                Error(
                    "The following OAuth providers are in the database but not in the settings: {}".format(
                        ", ".join(keys_in_db - keys_in_settings)
                    ),
                    id="plain.oauth.E001",
                )
            )

        return errors
