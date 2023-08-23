from bolt.apps import AppConfig
from bolt import checks
from django.db.models.query_utils import DeferredAttribute

from . import get_user_model
from .checks import check_user_model
from .signals import user_logged_in


class AuthConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "bolt.auth"
    verbose_name = "Authentication and Authorization"

    def ready(self):
        last_login_field = getattr(get_user_model(), "last_login", None)
        # Register the handler only if UserModel.last_login is a field.
        if isinstance(last_login_field, DeferredAttribute):
            from .models import update_last_login

            user_logged_in.connect(update_last_login, dispatch_uid="update_last_login")
        checks.register(check_user_model, checks.Tags.models)
