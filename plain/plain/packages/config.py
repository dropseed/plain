import inspect
import os
from importlib import import_module

from plain.exceptions import ImproperlyConfigured
from plain.utils.module_loading import import_string, module_has_submodule

CONFIG_MODULE_NAME = "config"
MODELS_MODULE_NAME = "models"


class PackageConfig:
    """Class representing a Plain application and its configuration."""

    migrations_module = "migrations"

    def __init__(self, package_name, package_module):
        # Full Python path to the application e.g. 'plain.staff.admin'.
        self.name = package_name

        # Root module for the application e.g. <module 'plain.staff.admin'
        # from 'staff/__init__.py'>.
        self.module = package_module

        # Reference to the Packages registry that holds this PackageConfig. Set by the
        # registry when it registers the PackageConfig instance.
        self.packages = None

        # The following attributes could be defined at the class level in a
        # subclass, hence the test-and-set pattern.

        # Last component of the Python path to the application e.g. 'admin'.
        # This value must be unique across a Plain project.
        if not hasattr(self, "label"):
            self.label = package_name.rpartition(".")[2]
        if not self.label.isidentifier():
            raise ImproperlyConfigured(
                "The app label '%s' is not a valid Python identifier." % self.label
            )

        # Filesystem path to the application directory e.g.
        # '/path/to/admin'.
        if not hasattr(self, "path"):
            self.path = self._path_from_module(package_module)

        # Module containing models e.g. <module 'plain.staff.models'
        # from 'staff/models.py'>. Set by import_models().
        # None if the application doesn't have a models module.
        self.models_module = None

        # Mapping of lowercase model names to model classes. Initially set to
        # None to prevent accidental access before import_models() runs.
        self.models = None

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.label}>"

    def _path_from_module(self, module):
        """Attempt to determine app's filesystem path from its module."""
        # See #21874 for extended discussion of the behavior of this method in
        # various cases.
        # Convert to list because __path__ may not support indexing.
        paths = list(getattr(module, "__path__", []))
        if len(paths) != 1:
            filename = getattr(module, "__file__", None)
            if filename is not None:
                paths = [os.path.dirname(filename)]
            else:
                # For unknown reasons, sometimes the list returned by __path__
                # contains duplicates that must be removed (#25246).
                paths = list(set(paths))
        if len(paths) > 1:
            raise ImproperlyConfigured(
                "The app module {!r} has multiple filesystem locations ({!r}); "
                "you must configure this app with an PackageConfig subclass "
                "with a 'path' class attribute.".format(module, paths)
            )
        elif not paths:
            raise ImproperlyConfigured(
                "The app module %r has no filesystem location, "
                "you must configure this app with an PackageConfig subclass "
                "with a 'path' class attribute." % module
            )
        return paths[0]

    @classmethod
    def create(cls, entry):
        """
        Factory that creates an app config from an entry in INSTALLED_PACKAGES.
        """
        # create() eventually returns package_config_class(package_name, package_module).
        package_config_class = None
        package_name = None
        package_module = None

        # If import_module succeeds, entry points to the app module.
        try:
            package_module = import_module(entry)
        except Exception:
            pass
        else:
            # If package_module has an packages submodule that defines a single
            # PackageConfig subclass, use it automatically.
            # To prevent this, an PackageConfig subclass can declare a class
            # variable default = False.
            # If the packages module defines more than one PackageConfig subclass,
            # the default one can declare default = True.
            if module_has_submodule(package_module, CONFIG_MODULE_NAME):
                mod_path = f"{entry}.{CONFIG_MODULE_NAME}"
                mod = import_module(mod_path)
                # Check if there's exactly one PackageConfig candidate,
                # excluding those that explicitly define default = False.
                package_configs = [
                    (name, candidate)
                    for name, candidate in inspect.getmembers(mod, inspect.isclass)
                    if (
                        issubclass(candidate, cls)
                        and candidate is not cls
                        and getattr(candidate, "default", True)
                    )
                ]
                if len(package_configs) == 1:
                    package_config_class = package_configs[0][1]
                else:
                    # Check if there's exactly one PackageConfig subclass,
                    # among those that explicitly define default = True.
                    package_configs = [
                        (name, candidate)
                        for name, candidate in package_configs
                        if getattr(candidate, "default", False)
                    ]
                    if len(package_configs) > 1:
                        candidates = [repr(name) for name, _ in package_configs]
                        raise RuntimeError(
                            "{!r} declares more than one default PackageConfig: "
                            "{}.".format(mod_path, ", ".join(candidates))
                        )
                    elif len(package_configs) == 1:
                        package_config_class = package_configs[0][1]

            # Use the default app config class if we didn't find anything.
            if package_config_class is None:
                package_config_class = cls
                package_name = entry

        # If import_string succeeds, entry is an app config class.
        if package_config_class is None:
            try:
                package_config_class = import_string(entry)
            except Exception:
                pass
        # If both import_module and import_string failed, it means that entry
        # doesn't have a valid value.
        if package_module is None and package_config_class is None:
            # If the last component of entry starts with an uppercase letter,
            # then it was likely intended to be an app config class; if not,
            # an app module. Provide a nice error message in both cases.
            mod_path, _, cls_name = entry.rpartition(".")
            if mod_path and cls_name[0].isupper():
                # We could simply re-trigger the string import exception, but
                # we're going the extra mile and providing a better error
                # message for typos in INSTALLED_PACKAGES.
                # This may raise ImportError, which is the best exception
                # possible if the module at mod_path cannot be imported.
                mod = import_module(mod_path)
                candidates = [
                    repr(name)
                    for name, candidate in inspect.getmembers(mod, inspect.isclass)
                    if issubclass(candidate, cls) and candidate is not cls
                ]
                msg = f"Module '{mod_path}' does not contain a '{cls_name}' class."
                if candidates:
                    msg += " Choices are: %s." % ", ".join(candidates)
                raise ImportError(msg)
            else:
                # Re-trigger the module import exception.
                import_module(entry)

        # Check for obvious errors. (This check prevents duck typing, but
        # it could be removed if it became a problem in practice.)
        if not issubclass(package_config_class, PackageConfig):
            raise ImproperlyConfigured(
                "'%s' isn't a subclass of PackageConfig." % entry
            )

        # Obtain package name here rather than in PackageClass.__init__ to keep
        # all error checking for entries in INSTALLED_PACKAGES in one place.
        if package_name is None:
            try:
                package_name = package_config_class.name
            except AttributeError:
                raise ImproperlyConfigured("'%s' must supply a name attribute." % entry)

        # Ensure package_name points to a valid module.
        try:
            package_module = import_module(package_name)
        except ImportError:
            raise ImproperlyConfigured(
                "Cannot import '{}'. Check that '{}.{}.name' is correct.".format(
                    package_name,
                    package_config_class.__module__,
                    package_config_class.__qualname__,
                )
            )

        # Entry is a path to an app config class.
        return package_config_class(package_name, package_module)

    def get_model(self, model_name, require_ready=True):
        """
        Return the model with the given case-insensitive model_name.

        Raise LookupError if no model exists with this name.
        """
        if require_ready:
            self.packages.check_models_ready()
        else:
            self.packages.check_packages_ready()
        try:
            return self.models[model_name.lower()]
        except KeyError:
            raise LookupError(
                f"Package '{self.label}' doesn't have a '{model_name}' model."
            )

    def get_models(self, include_auto_created=False, include_swapped=False):
        """
        Return an iterable of models.

        By default, the following models aren't included:

        - auto-created models for many-to-many relations without
          an explicit intermediate table,
        - models that have been swapped out.

        Set the corresponding keyword argument to True to include such models.
        Keyword arguments aren't documented; they're a private API.
        """
        self.packages.check_models_ready()
        for model in self.models.values():
            if model._meta.auto_created and not include_auto_created:
                continue
            if model._meta.swapped and not include_swapped:
                continue
            yield model

    def import_models(self):
        # Dictionary of models for this app, primarily maintained in the
        # 'all_models' attribute of the Packages this PackageConfig is attached to.
        self.models = self.packages.all_models[self.label]

        if module_has_submodule(self.module, MODELS_MODULE_NAME):
            models_module_name = f"{self.name}.{MODELS_MODULE_NAME}"
            self.models_module = import_module(models_module_name)

    def ready(self):
        """
        Override this method in subclasses to run code when Plain starts.
        """
