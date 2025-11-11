from plain.models.db import OperationalError, ProgrammingError
from plain.preflight import PreflightCheck, PreflightResult, register_check
from plain.runtime import settings

from .bridge import get_flag_class
from .exceptions import FlagImportError


@register_check(name="flags.unused_flags")
class CheckUnusedFlags(PreflightCheck):
    """
    Check for flags that are in the database, but no longer defined in code.

    Only returns Info errors because it is valid to leave them if you're worried about
    putting the flag back, but they should probably be deleted eventually.
    """

    def run(self) -> list[PreflightResult]:
        # Import here to avoid circular import
        from .models import Flag

        errors = []

        flag_names = Flag.query.all().values_list("name", flat=True)

        try:
            flag_names = set(flag_names)
        except (ProgrammingError, OperationalError):
            # The table doesn't exist yet
            # (migrations probably haven't run yet),
            # so we can't check it.
            return errors

        for flag_name in flag_names:
            try:
                get_flag_class(flag_name)
            except FlagImportError:
                errors.append(
                    PreflightResult(
                        fix=f"Flag {flag_name} is not used. Remove the flag from the database or define it in the {settings.FLAGS_MODULE} module.",
                        warning=True,
                        id="flags.unused_flags",
                    )
                )

        return errors
