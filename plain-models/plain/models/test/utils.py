from plain.exceptions import ImproperlyConfigured
from plain.models import DEFAULT_DB_ALIAS, connections


def setup_databases(
    verbosity,
    *,
    keepdb=False,
    debug_sql=False,
    aliases=None,
    serialized_aliases=None,
    **kwargs,
):
    """Create the test databases."""

    test_databases, mirrored_aliases = get_unique_databases_and_mirrors(aliases)

    old_names = []

    for db_name, aliases in test_databases.values():
        first_alias = None
        for alias in aliases:
            connection = connections[alias]
            old_names.append((connection, db_name, first_alias is None))

            # Actually create the database for the first connection
            if first_alias is None:
                first_alias = alias
                serialize_alias = (
                    serialized_aliases is None or alias in serialized_aliases
                )
                connection.creation.create_test_db(
                    verbosity=verbosity,
                    autoclobber=True,
                    keepdb=keepdb,
                    serialize=serialize_alias,
                )
            # Configure all other connections as mirrors of the first one
            else:
                connections[alias].creation.set_as_test_mirror(
                    connections[first_alias].settings_dict
                )

    # Configure the test mirrors.
    for alias, mirror_alias in mirrored_aliases.items():
        connections[alias].creation.set_as_test_mirror(
            connections[mirror_alias].settings_dict
        )

    if debug_sql:
        for alias in connections:
            connections[alias].force_debug_cursor = True

    return old_names


def get_unique_databases_and_mirrors(aliases=None):
    """
    Figure out which databases actually need to be created.

    Deduplicate entries in DATABASES that correspond the same database or are
    configured as test mirrors.

    Return two values:
    - test_databases: ordered mapping of signatures to (name, list of aliases)
                      where all aliases share the same underlying database.
    - mirrored_aliases: mapping of mirror aliases to original aliases.
    """
    if aliases is None:
        aliases = connections
    mirrored_aliases = {}
    test_databases = {}
    dependencies = {}
    default_sig = connections[DEFAULT_DB_ALIAS].creation.test_db_signature()

    for alias in connections:
        connection = connections[alias]
        test_settings = connection.settings_dict["TEST"]

        if test_settings["MIRROR"]:
            # If the database is marked as a test mirror, save the alias.
            mirrored_aliases[alias] = test_settings["MIRROR"]
        elif alias in aliases:
            # Store a tuple with DB parameters that uniquely identify it.
            # If we have two aliases with the same values for that tuple,
            # we only need to create the test database once.
            item = test_databases.setdefault(
                connection.creation.test_db_signature(),
                (connection.settings_dict["NAME"], []),
            )
            # The default database must be the first because data migrations
            # use the default alias by default.
            if alias == DEFAULT_DB_ALIAS:
                item[1].insert(0, alias)
            else:
                item[1].append(alias)

            if "DEPENDENCIES" in test_settings:
                dependencies[alias] = test_settings["DEPENDENCIES"]
            else:
                if (
                    alias != DEFAULT_DB_ALIAS
                    and connection.creation.test_db_signature() != default_sig
                ):
                    dependencies[alias] = test_settings.get(
                        "DEPENDENCIES", [DEFAULT_DB_ALIAS]
                    )

    test_databases = dict(dependency_ordered(test_databases.items(), dependencies))
    return test_databases, mirrored_aliases


def teardown_databases(old_config, verbosity, keepdb=False):
    """Destroy all the non-mirror databases."""
    for connection, old_name, destroy in old_config:
        if destroy:
            connection.creation.destroy_test_db(old_name, verbosity, keepdb)


def dependency_ordered(test_databases, dependencies):
    """
    Reorder test_databases into an order that honors the dependencies
    described in TEST[DEPENDENCIES].
    """
    ordered_test_databases = []
    resolved_databases = set()

    # Maps db signature to dependencies of all its aliases
    dependencies_map = {}

    # Check that no database depends on its own alias
    for sig, (_, aliases) in test_databases:
        all_deps = set()
        for alias in aliases:
            all_deps.update(dependencies.get(alias, []))
        if not all_deps.isdisjoint(aliases):
            raise ImproperlyConfigured(
                "Circular dependency: databases %r depend on each other, "
                "but are aliases." % aliases
            )
        dependencies_map[sig] = all_deps

    while test_databases:
        changed = False
        deferred = []

        # Try to find a DB that has all its dependencies met
        for signature, (db_name, aliases) in test_databases:
            if dependencies_map[signature].issubset(resolved_databases):
                resolved_databases.update(aliases)
                ordered_test_databases.append((signature, (db_name, aliases)))
                changed = True
            else:
                deferred.append((signature, (db_name, aliases)))

        if not changed:
            raise ImproperlyConfigured("Circular dependency in TEST[DEPENDENCIES]")
        test_databases = deferred
    return ordered_test_databases
