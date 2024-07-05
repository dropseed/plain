import functools
import os

from plain.assets import utils
from plain.assets.storage import FileSystemStorage
from plain.exceptions import ImproperlyConfigured
from plain.packages import packages
from plain.runtime import APP_PATH
from plain.utils._os import safe_join
from plain.utils.module_loading import import_string

# To keep track on which directories the finder has searched the static files.
searched_locations = []


APP_ASSETS_DIR = APP_PATH / "assets"


class BaseFinder:
    """
    A base file finder to be used for custom assets finder classes.
    """

    def check(self, **kwargs):
        raise NotImplementedError(
            "subclasses may provide a check() method to verify the finder is "
            "configured correctly."
        )

    def find(self, path, all=False):
        """
        Given a relative file path, find an absolute file path.

        If the ``all`` parameter is False (default) return only the first found
        file path; if True, return a list of all found files paths.
        """
        raise NotImplementedError(
            "subclasses of BaseFinder must provide a find() method"
        )

    def list(self, ignore_patterns):
        """
        Given an optional list of paths to ignore, return a two item iterable
        consisting of the relative path and storage instance.
        """
        raise NotImplementedError(
            "subclasses of BaseFinder must provide a list() method"
        )


class FileSystemFinder(BaseFinder):
    """
    A static files finder that looks in "static"
    """

    def __init__(self, package_names=None, *args, **kwargs):
        # List of locations with static files
        self.locations = []
        # Maps dir paths to an appropriate storage instance
        self.storages = {}

        root = APP_ASSETS_DIR

        if isinstance(root, list | tuple):
            prefix, root = root
        else:
            prefix = ""
        if (prefix, root) not in self.locations:
            self.locations.append((prefix, root))
        for prefix, root in self.locations:
            filesystem_storage = FileSystemStorage(location=root)
            filesystem_storage.prefix = prefix
            self.storages[root] = filesystem_storage
        super().__init__(*args, **kwargs)

    # def check(self, **kwargs):
    #     errors = []
    #     if settings.ASSETS_ROOT and os.path.abspath(
    #         settings.ASSETS_ROOT
    #     ) == os.path.abspath(self.path):
    #         errors.append(
    #             Error(
    #                 "The STATICFILES_DIR setting should not contain the "
    #                 "ASSETS_ROOT setting.",
    #                 id="assets.E002",
    #             )
    #         )
    #     return errors

    def find(self, path, all=False):
        matches = []
        for prefix, root in self.locations:
            if root not in searched_locations:
                searched_locations.append(root)
            matched_path = self.find_location(root, path, prefix)
            if matched_path:
                if not all:
                    return matched_path
                matches.append(matched_path)
        return matches

    def find_location(self, root, path, prefix=None):
        """
        Find a requested static file in a location and return the found
        absolute path (or ``None`` if no match).
        """
        if prefix:
            prefix = f"{prefix}{os.sep}"
            if not path.startswith(prefix):
                return None
            path = path.removeprefix(prefix)
        path = safe_join(root, path)
        if os.path.exists(path):
            return path

    def list(self, ignore_patterns):
        """
        List all files in all locations.
        """
        for prefix, root in self.locations:
            # Skip nonexistent directories.
            if os.path.isdir(root):
                storage = self.storages[root]
                for path in utils.get_files(storage, ignore_patterns):
                    yield path, storage


class PackageDirectoriesFinder(BaseFinder):
    """
    A static files finder that looks in the directory of each app as
    specified in the source_dir attribute.
    """

    storage_class = FileSystemStorage
    source_dir = "assets"

    def __init__(self, package_names=None, *args, **kwargs):
        # The list of packages that are handled
        self.packages = []
        # Mapping of app names to storage instances
        self.storages = {}
        package_configs = packages.get_package_configs()
        if package_names:
            package_names = set(package_names)
            package_configs = [ac for ac in package_configs if ac.name in package_names]
        for package_config in package_configs:
            app_storage = self.storage_class(
                os.path.join(package_config.path, self.source_dir)
            )
            if os.path.isdir(app_storage.location):
                self.storages[package_config.name] = app_storage
                if package_config.name not in self.packages:
                    self.packages.append(package_config.name)
        super().__init__(*args, **kwargs)

    def list(self, ignore_patterns):
        """
        List all files in all app storages.
        """
        for storage in self.storages.values():
            if storage.exists(""):  # check if storage location exists
                for path in utils.get_files(storage, ignore_patterns):
                    yield path, storage

    def find(self, path, all=False):
        """
        Look for files in the app directories.
        """
        matches = []
        for app in self.packages:
            app_location = self.storages[app].location
            if app_location not in searched_locations:
                searched_locations.append(app_location)
            match = self.find_in_app(app, path)
            if match:
                if not all:
                    return match
                matches.append(match)
        return matches

    def find_in_app(self, app, path):
        """
        Find a requested static file in an app's static locations.
        """
        storage = self.storages.get(app)
        # Only try to find a file if the source dir actually exists.
        if storage and storage.exists(path):
            matched_path = storage.path(path)
            if matched_path:
                return matched_path


def find(path, all=False):
    """
    Find a static file with the given path using all enabled finders.

    If ``all`` is ``False`` (default), return the first matching
    absolute path (or ``None`` if no match). Otherwise return a list.
    """
    searched_locations[:] = []
    matches = []
    for finder in get_finders():
        result = finder.find(path, all=all)
        if not all and result:
            return result
        if not isinstance(result, list | tuple):
            result = [result]
        matches.extend(result)
    if matches:
        return matches
    # No match.
    return [] if all else None


def get_finders():
    from plain.runtime import settings

    for finder_path in settings.ASSETS_FINDERS:
        yield get_finder(finder_path)


@functools.cache
def get_finder(import_path):
    """
    Import the assets finder class described by import_path, where
    import_path is the full Python path to the class.
    """
    Finder = import_string(import_path)
    if not issubclass(Finder, BaseFinder):
        raise ImproperlyConfigured(
            f'Finder "{Finder}" is not a subclass of "{BaseFinder}"'
        )
    return Finder()
