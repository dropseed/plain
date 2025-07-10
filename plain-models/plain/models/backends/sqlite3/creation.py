import os
import sys
from pathlib import Path

from plain.models.backends.base.creation import BaseDatabaseCreation


class DatabaseCreation(BaseDatabaseCreation):
    @staticmethod
    def is_in_memory_db(database_name):
        return not isinstance(database_name, Path) and (
            database_name == ":memory:" or "mode=memory" in database_name
        )

    def _get_test_db_name(self, prefix=""):
        raw_name = self.connection.settings_dict["TEST"]["NAME"] or ":memory:"
        # Special in-memory case
        if raw_name == ":memory:":
            return "file:memorydb?mode=memory&cache=shared"

        test_database_name = raw_name

        if prefix:
            test_database_name = f"{prefix}_{test_database_name}"

        return test_database_name

    def _create_test_db(self, *, test_database_name, verbosity, autoclobber):
        """
        Internal implementation - delete existing SQLite test DB file if needed.
        """
        if not self.is_in_memory_db(test_database_name):
            # Erase the old test database file.
            if verbosity >= 1:
                self.log(f"Destroying old test database '{test_database_name}'...")
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

    def _destroy_test_db(self, test_database_name, verbosity):
        if test_database_name and not self.is_in_memory_db(test_database_name):
            # Remove the SQLite database file
            os.remove(test_database_name)

    def test_db_signature(self, prefix=""):
        """
        Return a tuple that uniquely identifies a test database.

        This takes into account the special cases of ":memory:" and "" for
        SQLite since the databases will be distinct despite having the same
        TEST NAME. See https://www.sqlite.org/inmemorydb.html
        """
        test_database_name = self._get_test_db_name(prefix)
        sig = [self.connection.settings_dict["NAME"]]
        if self.is_in_memory_db(test_database_name):
            sig.append(":memory:")
        else:
            sig.append(test_database_name)
        return tuple(sig)
