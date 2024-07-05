from plain.utils.inspect import func_accepts_kwargs
from plain.utils.itercompat import is_iterable


class CheckRegistry:
    def __init__(self):
        self.registered_checks = set()
        self.deployment_checks = set()

    def register(self, check=None, deploy=False):
        """
        Can be used as a function or a decorator. Register given function
        `f`. The function should receive **kwargs
        and return list of Errors and Warnings.

        Example::

            registry = CheckRegistry()
            @registry.register('mytag', 'anothertag')
            def my_check(package_configs, **kwargs):
                # ... perform checks and collect `errors` ...
                return errors
            # or
            registry.register(my_check, 'mytag', 'anothertag')
        """

        def inner(check):
            if not func_accepts_kwargs(check):
                raise TypeError(
                    "Check functions must accept keyword arguments (**kwargs)."
                )
            checks = self.deployment_checks if deploy else self.registered_checks
            checks.add(check)
            return check

        if callable(check):
            return inner(check)
        else:
            return inner

    def run_checks(
        self,
        package_configs=None,
        include_deployment_checks=False,
        databases=None,
    ):
        """
        Run all registered checks and return list of Errors and Warnings.
        """
        errors = []
        checks = self.get_checks(include_deployment_checks)

        for check in checks:
            new_errors = check(package_configs=package_configs, databases=databases)
            if not is_iterable(new_errors):
                raise TypeError(
                    "The function %r did not return a list. All functions "
                    "registered with the checks registry must return a list." % check,
                )
            errors.extend(new_errors)
        return errors

    def get_checks(self, include_deployment_checks=False):
        checks = list(self.registered_checks)
        if include_deployment_checks:
            checks.extend(self.deployment_checks)
        return checks


registry = CheckRegistry()
register = registry.register
run_checks = registry.run_checks
