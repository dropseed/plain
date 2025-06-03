import sys

from plain.models.backends.base.creation import BaseDatabaseCreation


class DatabaseCreation(BaseDatabaseCreation):
    def sql_table_creation_suffix(self):
        suffix = []
        test_settings = self.connection.settings_dict["TEST"]
        if test_settings["CHARSET"]:
            suffix.append("CHARACTER SET {}".format(test_settings["CHARSET"]))
        if test_settings["COLLATION"]:
            suffix.append("COLLATE {}".format(test_settings["COLLATION"]))
        return " ".join(suffix)

    def _execute_create_test_db(self, cursor, parameters):
        try:
            super()._execute_create_test_db(cursor, parameters)
        except Exception as e:
            if len(e.args) < 1 or e.args[0] != 1007:
                # All errors except "database exists" (1007) cancel tests.
                self.log(f"Got an error creating the test database: {e}")
                sys.exit(2)
            else:
                raise
