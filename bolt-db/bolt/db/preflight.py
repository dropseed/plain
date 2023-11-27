import inspect
import types
from collections import defaultdict
from itertools import chain

from bolt.packages import packages
from bolt.preflight import Error, Warning, register
from bolt.runtime import settings


@register
def check_database_backends(databases=None, **kwargs):
    if databases is None:
        return []

    from bolt.db import connections

    issues = []
    for alias in databases:
        conn = connections[alias]
        issues.extend(conn.validation.check(**kwargs))
    return issues


@register
def check_all_models(package_configs=None, **kwargs):
    db_table_models = defaultdict(list)
    indexes = defaultdict(list)
    constraints = defaultdict(list)
    errors = []
    if package_configs is None:
        models = packages.get_models()
    else:
        models = chain.from_iterable(
            package_config.get_models() for package_config in package_configs
        )
    for model in models:
        if model._meta.managed and not model._meta.proxy:
            db_table_models[model._meta.db_table].append(model._meta.label)
        if not inspect.ismethod(model.check):
            errors.append(
                Error(
                    "The '{}.check()' class method is currently overridden by {!r}.".format(
                        model.__name__, model.check
                    ),
                    obj=model,
                    id="models.E020",
                )
            )
        else:
            errors.extend(model.check(**kwargs))
        for model_index in model._meta.indexes:
            indexes[model_index.name].append(model._meta.label)
        for model_constraint in model._meta.constraints:
            constraints[model_constraint.name].append(model._meta.label)
    if settings.DATABASE_ROUTERS:
        error_class, error_id = Warning, "models.W035"
        error_hint = (
            "You have configured settings.DATABASE_ROUTERS. Verify that %s "
            "are correctly routed to separate databases."
        )
    else:
        error_class, error_id = Error, "models.E028"
        error_hint = None
    for db_table, model_labels in db_table_models.items():
        if len(model_labels) != 1:
            model_labels_str = ", ".join(model_labels)
            errors.append(
                error_class(
                    "db_table '{}' is used by multiple models: {}.".format(
                        db_table, model_labels_str
                    ),
                    obj=db_table,
                    hint=(error_hint % model_labels_str) if error_hint else None,
                    id=error_id,
                )
            )
    for index_name, model_labels in indexes.items():
        if len(model_labels) > 1:
            model_labels = set(model_labels)
            errors.append(
                Error(
                    "index name '{}' is not unique {} {}.".format(
                        index_name,
                        "for model" if len(model_labels) == 1 else "among models:",
                        ", ".join(sorted(model_labels)),
                    ),
                    id="models.E029" if len(model_labels) == 1 else "models.E030",
                ),
            )
    for constraint_name, model_labels in constraints.items():
        if len(model_labels) > 1:
            model_labels = set(model_labels)
            errors.append(
                Error(
                    "constraint name '{}' is not unique {} {}.".format(
                        constraint_name,
                        "for model" if len(model_labels) == 1 else "among models:",
                        ", ".join(sorted(model_labels)),
                    ),
                    id="models.E031" if len(model_labels) == 1 else "models.E032",
                ),
            )
    return errors


def _check_lazy_references(packages, ignore=None):
    """
    Ensure all lazy (i.e. string) model references have been resolved.

    Lazy references are used in various places throughout Bolt, primarily in
    related fields and model signals. Identify those common cases and provide
    more helpful error messages for them.

    The ignore parameter is used by StatePackages to exclude swappable models from
    this check.
    """
    pending_models = set(packages._pending_operations) - (ignore or set())

    # Short circuit if there aren't any errors.
    if not pending_models:
        return []

    from bolt.db.models import signals

    model_signals = {
        signal: name
        for name, signal in vars(signals).items()
        if isinstance(signal, signals.ModelSignal)
    }

    def extract_operation(obj):
        """
        Take a callable found in Packages._pending_operations and identify the
        original callable passed to Packages.lazy_model_operation(). If that
        callable was a partial, return the inner, non-partial function and
        any arguments and keyword arguments that were supplied with it.

        obj is a callback defined locally in Packages.lazy_model_operation() and
        annotated there with a `func` attribute so as to imitate a partial.
        """
        operation, args, keywords = obj, [], {}
        while hasattr(operation, "func"):
            args.extend(getattr(operation, "args", []))
            keywords.update(getattr(operation, "keywords", {}))
            operation = operation.func
        return operation, args, keywords

    def app_model_error(model_key):
        try:
            packages.get_package_config(model_key[0])
            model_error = "app '{}' doesn't provide model '{}'".format(*model_key)
        except LookupError:
            model_error = "app '%s' isn't installed" % model_key[0]
        return model_error

    # Here are several functions which return CheckMessage instances for the
    # most common usages of lazy operations throughout Bolt. These functions
    # take the model that was being waited on as an (package_label, modelname)
    # pair, the original lazy function, and its positional and keyword args as
    # determined by extract_operation().

    def field_error(model_key, func, args, keywords):
        error_msg = (
            "The field %(field)s was declared with a lazy reference "
            "to '%(model)s', but %(model_error)s."
        )
        params = {
            "model": ".".join(model_key),
            "field": keywords["field"],
            "model_error": app_model_error(model_key),
        }
        return Error(error_msg % params, obj=keywords["field"], id="fields.E307")

    def signal_connect_error(model_key, func, args, keywords):
        error_msg = (
            "%(receiver)s was connected to the '%(signal)s' signal with a "
            "lazy reference to the sender '%(model)s', but %(model_error)s."
        )
        receiver = args[0]
        # The receiver is either a function or an instance of class
        # defining a `__call__` method.
        if isinstance(receiver, types.FunctionType):
            description = "The function '%s'" % receiver.__name__
        elif isinstance(receiver, types.MethodType):
            description = "Bound method '{}.{}'".format(
                receiver.__self__.__class__.__name__,
                receiver.__name__,
            )
        else:
            description = "An instance of class '%s'" % receiver.__class__.__name__
        signal_name = model_signals.get(func.__self__, "unknown")
        params = {
            "model": ".".join(model_key),
            "receiver": description,
            "signal": signal_name,
            "model_error": app_model_error(model_key),
        }
        return Error(error_msg % params, obj=receiver.__module__, id="signals.E001")

    def default_error(model_key, func, args, keywords):
        error_msg = (
            "%(op)s contains a lazy reference to %(model)s, but %(model_error)s."
        )
        params = {
            "op": func,
            "model": ".".join(model_key),
            "model_error": app_model_error(model_key),
        }
        return Error(error_msg % params, obj=func, id="models.E022")

    # Maps common uses of lazy operations to corresponding error functions
    # defined above. If a key maps to None, no error will be produced.
    # default_error() will be used for usages that don't appear in this dict.
    known_lazy = {
        ("bolt.db.models.fields.related", "resolve_related_class"): field_error,
        ("bolt.db.models.fields.related", "set_managed"): None,
        ("bolt.signals.dispatch.dispatcher", "connect"): signal_connect_error,
    }

    def build_error(model_key, func, args, keywords):
        key = (func.__module__, func.__name__)
        error_fn = known_lazy.get(key, default_error)
        return error_fn(model_key, func, args, keywords) if error_fn else None

    return sorted(
        filter(
            None,
            (
                build_error(model_key, *extract_operation(func))
                for model_key in pending_models
                for func in packages._pending_operations[model_key]
            ),
        ),
        key=lambda error: error.msg,
    )


@register
def check_lazy_references(package_configs=None, **kwargs):
    return _check_lazy_references(packages)


@register
def check_database_tables(package_configs, **kwargs):
    from bolt.db import connection

    databases = kwargs.get("databases", None)
    if not databases:
        return []

    errors = []

    if hasattr(settings, "CACHES"):
        cache_tables = [
            x["LOCATION"]
            for x in settings.CACHES.values()
            if x["BACKEND"] == "bolt.cache.backends.db.DatabaseCache"
        ]
    else:
        cache_tables = []

    for database in databases:
        db_tables = connection.introspection.table_names()
        model_tables = connection.introspection.bolt_table_names()

        unknown_tables = set(db_tables) - set(model_tables) - set(cache_tables)
        unknown_tables.discard("django_migrations")  # Know this could be there
        if unknown_tables:
            table_names = ", ".join(unknown_tables)
            specific_hint = (
                f'echo "DROP TABLE IF EXISTS {unknown_tables.pop()}" | bolt db shell'
            )
            errors.append(
                Error(
                    f"Unknown tables in {database} database: {table_names}",
                    hint=(
                        "Tables may be from packages/models that have been uninstalled. "
                        "Make sure you have a backup and delete the tables manually "
                        f"(ex. `{specific_hint}`)."
                    ),
                    id="bolt.db.E001",
                )
            )

    return errors
