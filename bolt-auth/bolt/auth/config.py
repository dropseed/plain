from bolt import preflight
from bolt.db.models.query_utils import DeferredAttribute
from bolt.packages import PackageConfig

from . import get_user_model
from .preflight import check_user_model
from .signals import user_logged_in


class AuthConfig(PackageConfig):
    default_auto_field = "bolt.db.models.AutoField"
    name = "bolt.auth"
    verbose_name = "Authentication and Authorization"

    def ready(self):
        last_login_field = getattr(get_user_model(), "last_login", None)
        # Register the handler only if UserModel.last_login is a field.
        if isinstance(last_login_field, DeferredAttribute):
            from .models import update_last_login

            user_logged_in.connect(update_last_login, dispatch_uid="update_last_login")
        preflight.register(check_user_model, preflight.Tags.models)
