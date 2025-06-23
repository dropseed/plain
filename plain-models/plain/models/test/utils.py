from plain.models import db_connection


def setup_database(*, verbosity, prefix=""):
    old_name = db_connection.settings_dict["NAME"]
    db_connection.creation.create_test_db(verbosity=verbosity, prefix=prefix)
    return old_name


def teardown_database(old_name, verbosity):
    db_connection.creation.destroy_test_db(old_name, verbosity)
