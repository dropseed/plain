import functools
import sys
import threading
import warnings
from collections import Counter, defaultdict
from functools import partial

from plain.exceptions import ImproperlyConfigured, PackageRegistryNotReady

from .config import PackageConfig


class Packages:
    """
    A registry that stores the configuration of installed applications.

    It also keeps track of models, e.g. to provide reverse relations.
    """

    def __init__(self, installed_packages=()):
        # installed_packages is set to None when creating the main registry
        # because it cannot be populated at that point. Other registries must
        # provide a list of installed packages and are populated immediately.
        if installed_packages is None and hasattr(sys.modules[__name__], "packages"):
            raise RuntimeError("You must supply an installed_packages argument.")

        # Mapping of app labels => model names => model classes. Every time a
        # model is imported, ModelBase.__new__ calls packages.register_model which
        # creates an entry in all_models. All imported models are registered,
        # regardless of whether they're defined in an installed application
        # and whether the registry has been populated. Since it isn't possible
        # to reimport a module safely (it could reexecute initialization code)
        # all_models is never overridden or reset.
        self.all_models = defaultdict(dict)

        # Mapping of labels to PackageConfig instances for installed packages.
        self.package_configs = {}

        # Stack of package_configs. Used to store the current state in
        # set_available_packages and set_installed_packages.
        self.stored_package_configs = []

        # Whether the registry is populated.
        self.packages_ready = self.models_ready = self.ready = False

        # Lock for thread-safe population.
        self._lock = threading.RLock()
        self.loading = False

        # Maps ("package_label", "modelname") tuples to lists of functions to be
        # called when the corresponding model is ready. Used by this class's
        # `lazy_model_operation()` and `do_pending_operations()` methods.
        self._pending_operations = defaultdict(list)

        # Populate packages and models, unless it's the main registry.
        if installed_packages is not None:
            self.populate(installed_packages)

    def populate(self, installed_packages=None):
        """
        Load application configurations and models.

        Import each application module and then each model module.

        It is thread-safe and idempotent, but not reentrant.
        """
        if self.ready:
            return

        # populate() might be called by two threads in parallel on servers
        # that create threads before initializing the WSGI callable.
        with self._lock:
            if self.ready:
                return

            # An RLock prevents other threads from entering this section. The
            # compare and set operation below is atomic.
            if self.loading:
                # Prevent reentrant calls to avoid running PackageConfig.ready()
                # methods twice.
                raise RuntimeError("populate() isn't reentrant")
            self.loading = True

            # Phase 1: initialize app configs and import app modules.
            for entry in installed_packages:
                if isinstance(entry, PackageConfig):
                    package_config = entry
                else:
                    package_config = PackageConfig.create(entry)
                if package_config.label in self.package_configs:
                    raise ImproperlyConfigured(
                        "Package labels aren't unique, "
                        "duplicates: %s" % package_config.label
                    )

                self.package_configs[package_config.label] = package_config
                package_config.packages = self

            # Check for duplicate app names.
            counts = Counter(
                package_config.name for package_config in self.package_configs.values()
            )
            duplicates = [name for name, count in counts.most_common() if count > 1]
            if duplicates:
                raise ImproperlyConfigured(
                    "Package names aren't unique, "
                    "duplicates: %s" % ", ".join(duplicates)
                )

            self.packages_ready = True

            # Phase 2: import models modules.
            for package_config in self.package_configs.values():
                package_config.import_models()

            self.clear_cache()

            self.models_ready = True

            # Phase 3: run ready() methods of app configs.
            for package_config in self.get_package_configs():
                package_config.ready()

            self.ready = True

    def check_packages_ready(self):
        """Raise an exception if all packages haven't been imported yet."""
        if not self.packages_ready:
            from plain.runtime import settings

            # If "not ready" is due to unconfigured settings, accessing
            # INSTALLED_PACKAGES raises a more helpful ImproperlyConfigured
            # exception.
            settings.INSTALLED_PACKAGES
            raise PackageRegistryNotReady("Packages aren't loaded yet.")

    def check_models_ready(self):
        """Raise an exception if all models haven't been imported yet."""
        if not self.models_ready:
            raise PackageRegistryNotReady("Models aren't loaded yet.")

    def get_package_configs(self):
        """Import applications and return an iterable of app configs."""
        self.check_packages_ready()
        return self.package_configs.values()

    def get_package_config(self, package_label):
        """
        Import applications and returns an app config for the given label.

        Raise LookupError if no application exists with this label.
        """
        self.check_packages_ready()
        try:
            return self.package_configs[package_label]
        except KeyError:
            message = "No installed app with label '%s'." % package_label
            for package_config in self.get_package_configs():
                if package_config.name == package_label:
                    message += " Did you mean '%s'?" % package_config.label
                    break
            raise LookupError(message)

    # This method is performance-critical at least for Plain's test suite.
    @functools.cache
    def get_models(self, include_auto_created=False, include_swapped=False):
        """
        Return a list of all installed models.

        By default, the following models aren't included:

        - auto-created models for many-to-many relations without
          an explicit intermediate table,
        - models that have been swapped out.

        Set the corresponding keyword argument to True to include such models.
        """
        self.check_models_ready()

        result = []
        for package_config in self.package_configs.values():
            result.extend(
                package_config.get_models(include_auto_created, include_swapped)
            )
        return result

    def get_model(self, package_label, model_name=None, require_ready=True):
        """
        Return the model matching the given package_label and model_name.

        As a shortcut, package_label may be in the form <package_label>.<model_name>.

        model_name is case-insensitive.

        Raise LookupError if no application exists with this label, or no
        model exists with this name in the application. Raise ValueError if
        called with a single argument that doesn't contain exactly one dot.
        """
        if require_ready:
            self.check_models_ready()
        else:
            self.check_packages_ready()

        if model_name is None:
            package_label, model_name = package_label.split(".")

        package_config = self.get_package_config(package_label)

        if not require_ready and package_config.models is None:
            package_config.import_models()

        return package_config.get_model(model_name, require_ready=require_ready)

    def register_model(self, package_label, model):
        # Since this method is called when models are imported, it cannot
        # perform imports because of the risk of import loops. It mustn't
        # call get_package_config().
        model_name = model._meta.model_name
        app_models = self.all_models[package_label]
        if model_name in app_models:
            if (
                model.__name__ == app_models[model_name].__name__
                and model.__module__ == app_models[model_name].__module__
            ):
                warnings.warn(
                    "Model '{}.{}' was already registered. Reloading models is not "
                    "advised as it can lead to inconsistencies, most notably with "
                    "related models.".format(package_label, model_name),
                    RuntimeWarning,
                    stacklevel=2,
                )
            else:
                raise RuntimeError(
                    "Conflicting '{}' models in application '{}': {} and {}.".format(
                        model_name, package_label, app_models[model_name], model
                    )
                )
        app_models[model_name] = model
        self.do_pending_operations(model)
        self.clear_cache()

    def is_installed(self, package_name):
        """
        Check whether an application with this name exists in the registry.

        package_name is the full name of the app e.g. 'plain.staff'.
        """
        self.check_packages_ready()
        return any(ac.name == package_name for ac in self.package_configs.values())

    def get_containing_package_config(self, object_name):
        """
        Look for an app config containing a given object.

        object_name is the dotted Python path to the object.

        Return the app config for the inner application in case of nesting.
        Return None if the object isn't in any registered app config.
        """
        self.check_packages_ready()
        candidates = []
        for package_config in self.package_configs.values():
            if object_name.startswith(package_config.name):
                subpath = object_name.removeprefix(package_config.name)
                if subpath == "" or subpath[0] == ".":
                    candidates.append(package_config)
        if candidates:
            return sorted(candidates, key=lambda ac: -len(ac.name))[0]

    def get_registered_model(self, package_label, model_name):
        """
        Similar to get_model(), but doesn't require that an app exists with
        the given package_label.

        It's safe to call this method at import time, even while the registry
        is being populated.
        """
        model = self.all_models[package_label].get(model_name.lower())
        if model is None:
            raise LookupError(f"Model '{package_label}.{model_name}' not registered.")
        return model

    @functools.cache
    def get_swappable_settings_name(self, to_string):
        """
        For a given model string (e.g. "auth.User"), return the name of the
        corresponding settings name if it refers to a swappable model. If the
        referred model is not swappable, return None.

        This method is decorated with @functools.cache because it's performance
        critical when it comes to migrations. Since the swappable settings don't
        change after Plain has loaded the settings, there is no reason to get
        the respective settings attribute over and over again.
        """
        to_string = to_string.lower()
        for model in self.get_models(include_swapped=True):
            swapped = model._meta.swapped
            # Is this model swapped out for the model given by to_string?
            if swapped and swapped.lower() == to_string:
                return model._meta.swappable
            # Is this model swappable and the one given by to_string?
            if model._meta.swappable and model._meta.label_lower == to_string:
                return model._meta.swappable
        return None

    def set_available_packages(self, available):
        """
        Restrict the set of installed packages used by get_package_config[s].

        available must be an iterable of application names.

        set_available_packages() must be balanced with unset_available_packages().

        Primarily used for performance optimization in TransactionTestCase.

        This method is safe in the sense that it doesn't trigger any imports.
        """
        available = set(available)
        installed = {
            package_config.name for package_config in self.get_package_configs()
        }
        if not available.issubset(installed):
            raise ValueError(
                "Available packages isn't a subset of installed packages, extra packages: %s"
                % ", ".join(available - installed)
            )

        self.stored_package_configs.append(self.package_configs)
        self.package_configs = {
            label: package_config
            for label, package_config in self.package_configs.items()
            if package_config.name in available
        }
        self.clear_cache()

    def unset_available_packages(self):
        """Cancel a previous call to set_available_packages()."""
        self.package_configs = self.stored_package_configs.pop()
        self.clear_cache()

    def set_installed_packages(self, installed):
        """
        Enable a different set of installed packages for get_package_config[s].

        installed must be an iterable in the same format as INSTALLED_PACKAGES.

        set_installed_packages() must be balanced with unset_installed_packages(),
        even if it exits with an exception.

        Primarily used as a receiver of the setting_changed signal in tests.

        This method may trigger new imports, which may add new models to the
        registry of all imported models. They will stay in the registry even
        after unset_installed_packages(). Since it isn't possible to replay
        imports safely (e.g. that could lead to registering listeners twice),
        models are registered when they're imported and never removed.
        """
        if not self.ready:
            raise PackageRegistryNotReady("Package registry isn't ready yet.")
        self.stored_package_configs.append(self.package_configs)
        self.package_configs = {}
        self.packages_ready = self.models_ready = self.loading = self.ready = False
        self.clear_cache()
        self.populate(installed)

    def clear_cache(self):
        """
        Clear all internal caches, for methods that alter the app registry.

        This is mostly used in tests.
        """
        # Call expire cache on each model. This will purge
        # the relation tree and the fields cache.
        self.get_models.cache_clear()
        if self.ready:
            # Circumvent self.get_models() to prevent that the cache is refilled.
            # This particularly prevents that an empty value is cached while cloning.
            for package_config in self.package_configs.values():
                for model in package_config.get_models(include_auto_created=True):
                    model._meta._expire_cache()

    def lazy_model_operation(self, function, *model_keys):
        """
        Take a function and a number of ("package_label", "modelname") tuples, and
        when all the corresponding models have been imported and registered,
        call the function with the model classes as its arguments.

        The function passed to this method must accept exactly n models as
        arguments, where n=len(model_keys).
        """
        # Base case: no arguments, just execute the function.
        if not model_keys:
            function()
        # Recursive case: take the head of model_keys, wait for the
        # corresponding model class to be imported and registered, then apply
        # that argument to the supplied function. Pass the resulting partial
        # to lazy_model_operation() along with the remaining model args and
        # repeat until all models are loaded and all arguments are applied.
        else:
            next_model, *more_models = model_keys

            # This will be executed after the class corresponding to next_model
            # has been imported and registered. The `func` attribute provides
            # duck-type compatibility with partials.
            def apply_next_model(model):
                next_function = partial(apply_next_model.func, model)
                self.lazy_model_operation(next_function, *more_models)

            apply_next_model.func = function

            # If the model has already been imported and registered, partially
            # apply it to the function now. If not, add it to the list of
            # pending operations for the model, where it will be executed with
            # the model class as its sole argument once the model is ready.
            try:
                model_class = self.get_registered_model(*next_model)
            except LookupError:
                self._pending_operations[next_model].append(apply_next_model)
            else:
                apply_next_model(model_class)

    def do_pending_operations(self, model):
        """
        Take a newly-prepared model and pass it to each function waiting for
        it. This is called at the very end of Packages.register_model().
        """
        key = model._meta.package_label, model._meta.model_name
        for function in self._pending_operations.pop(key, []):
            function(model)


packages = Packages(installed_packages=None)
