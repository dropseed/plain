import logging
from typing import Any

from plain.runtime import settings
from plain.utils import timezone
from plain.utils.functional import cached_property

from . import exceptions
from .utils import coerce_key

logger = logging.getLogger(__name__)


class Flag:
    def get_key(self) -> Any:
        """
        Determine a unique key for this instance of the flag.
        This should be a quick operation, as it will be called on every use of the flag.

        For convenience, you can return an instance of a Plain Model
        and it will be converted to a string automatically.

        Return a falsy value if you don't want to store the flag result.
        """
        raise NotImplementedError

    def get_value(self) -> Any:
        """
        Compute the resulting value of the flag.

        The value needs to be JSON serializable.

        If get_key() returns a value, this will only be called once per key
        and then subsequent calls will return the saved value from the DB.
        """
        raise NotImplementedError

    def get_db_name(self) -> str:
        """
        Should basically always be the name of the class.
        But this is overridable in case of renaming/refactoring/importing.
        """
        return self.__class__.__name__

    def retrieve_or_compute_value(self) -> Any:
        """
        Retrieve the value from the DB if it exists,
        otherwise compute the value and save it to the DB.
        """
        from .models import Flag, FlagResult  # So Plain app is ready...

        # Create an associated DB Flag that we can use to enable/disable
        # and tie the results to
        flag_obj, _ = Flag.objects.update_or_create(
            name=self.get_db_name(),
            defaults={"used_at": timezone.now()},
        )
        if not flag_obj.enabled:
            msg = f"The {flag_obj} flag has been disabled and should either not be called, or be re-enabled."
            if settings.DEBUG:
                raise exceptions.FlagDisabled(msg)
            else:
                logger.exception(msg)
                # Might not be the type of return value expected! Better than totally crashing now though.
                return None

        key = self.get_key()
        if not key:
            # No key, so we always recompute the value and return it
            return self.get_value()

        key = coerce_key(key)

        try:
            flag_result = FlagResult.objects.get(flag=flag_obj, key=key)
            return flag_result.value
        except FlagResult.DoesNotExist:
            value = self.get_value()
            flag_result = FlagResult.objects.create(flag=flag_obj, key=key, value=value)
            return flag_result.value

    @cached_property
    def value(self) -> Any:
        """
        Cached version of retrieve_or_compute_value()
        """
        return self.retrieve_or_compute_value()

    def __bool__(self) -> bool:
        """
        Allow for use in boolean expressions.
        """
        return bool(self.value)

    def __contains__(self, item) -> bool:
        """
        Allow for use in `in` expressions.
        """
        return item in self.value

    def __eq__(self, other) -> bool:
        """
        Allow for use in `==` expressions.
        """
        return self.value == other
