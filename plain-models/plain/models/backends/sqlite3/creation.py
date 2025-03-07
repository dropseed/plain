import multiprocessing
import os
import sys
from pathlib import Path

from plain.models.backends.base.creation import BaseDatabaseCreation
from plain.models.db import NotSupportedError


class DatabaseCreation(BaseDatabaseCreation):
    @staticmethod
    def is_in_memory_db(database_name):
        return not isinstance(database_name, Path) and (
            database_name == ":memory:" or "mode=memory" in database_name
        )

    def _get_test_db_name(self):
        test_database_name = self.connection.settings_dict["TEST"]["NAME"] or ":memory:"
        if test_database_name == ":memory:":
            return f"file:memorydb_{self.connection.alias}?mode=memory&cache=shared"
        return test_database_name

    def _create_test_db(self, verbosity, autoclobber, keepdb=False):
        test_database_name = self._get_test_db_name()

        if keepdb:
            return test_database_name
        if not self.is_in_memory_db(test_database_name):
            # Erase the old test database
            if verbosity >= 1:
                self.log(
                    f"Destroying old test database for alias {self._get_database_display_str(verbosity, test_database_name)}..."
                )
            if os.access(test_database_name, os.F_OK):
                if not autoclobber:
                    confirm = input(
                        "Type 'yes' if you would like to try deleting the test "
                        f"database '{test_database_name}', or 'no' to cancel: "
                    )
                if autoclobber or confirm == "yes":
                    try:
                        os.remove(test_database_name)
                    except Exception as e:
                        self.log(f"Got an error deleting the old test database: {e}")
                        sys.exit(2)
                else:
                    self.log("Tests cancelled.")
                    sys.exit(1)
        return test_database_name

    def get_test_db_clone_settings(self, suffix):
        orig_settings_dict = self.connection.settings_dict
        source_database_name = orig_settings_dict["NAME"]

        if not self.is_in_memory_db(source_database_name):
            root, ext = os.path.splitext(source_database_name)
            return {**orig_settings_dict, "NAME": f"{root}_{suffix}{ext}"}

        start_method = multiprocessing.get_start_method()
        if start_method == "fork":
            return orig_settings_dict
        if start_method == "spawn":
            return {
                **orig_settings_dict,
                "NAME": f"{self.connection.alias}_{suffix}.sqlite3",
            }
        raise NotSupportedError(
            f"Cloning with start method {start_method!r} is not supported."
        )

    def _destroy_test_db(self, test_database_name, verbosity):
        if test_database_name and not self.is_in_memory_db(test_database_name):
            # Remove the SQLite database file
            os.remove(test_database_name)

    def test_db_signature(self):
        """
        Return a tuple that uniquely identifies a test database.

        This takes into account the special cases of ":memory:" and "" for
        SQLite since the databases will be distinct despite having the same
        TEST NAME. See https://www.sqlite.org/inmemorydb.html
        """
        test_database_name = self._get_test_db_name()
        sig = [self.connection.settings_dict["NAME"]]
        if self.is_in_memory_db(test_database_name):
            sig.append(self.connection.alias)
        else:
            sig.append(test_database_name)
        return tuple(sig)
