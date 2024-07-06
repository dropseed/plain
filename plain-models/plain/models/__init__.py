from plain import signals
from plain.exceptions import ObjectDoesNotExist
from plain.models import signals as model_signals  # NOQA
from plain.models.aggregates import *  # NOQA
from plain.models.aggregates import __all__ as aggregates_all
from plain.models.constraints import *  # NOQA
from plain.models.constraints import __all__ as constraints_all
from plain.models.db_utils import (
    DEFAULT_DB_ALIAS,
    PLAIN_VERSION_PICKLE_KEY,
    ConnectionHandler,
    ConnectionRouter,
    DatabaseError,
    DataError,
    Error,
    IntegrityError,
    InterfaceError,
    InternalError,
    NotSupportedError,
    OperationalError,
    ProgrammingError,
)
from plain.models.deletion import (
    CASCADE,
    DO_NOTHING,
    PROTECT,
    RESTRICT,
    SET,
    SET_DEFAULT,
    SET_NULL,
    ProtectedError,
    RestrictedError,
)
from plain.models.enums import *  # NOQA
from plain.models.enums import __all__ as enums_all
from plain.models.expressions import (
    Case,
    Exists,
    Expression,
    ExpressionList,
    ExpressionWrapper,
    F,
    Func,
    OrderBy,
    OuterRef,
    RowRange,
    Subquery,
    Value,
    ValueRange,
    When,
    Window,
    WindowFrame,
)
from plain.models.fields import *  # NOQA
from plain.models.fields import __all__ as fields_all
from plain.models.fields.json import JSONField
from plain.models.fields.proxy import OrderWrt
from plain.models.indexes import *  # NOQA
from plain.models.indexes import __all__ as indexes_all
from plain.models.lookups import Lookup, Transform
from plain.models.manager import Manager
from plain.models.query import Prefetch, QuerySet, prefetch_related_objects
from plain.models.query_utils import FilteredRelation, Q
from plain.utils.connection import ConnectionProxy

from . import preflight  # noqa

# Imports that would create circular imports if sorted
from plain.models.base import DEFERRED, Model  # isort:skip
from plain.models.fields.related import (  # isort:skip
    ForeignKey,
    ForeignObject,
    OneToOneField,
    ManyToManyField,
    ForeignObjectRel,
    ManyToOneRel,
    ManyToManyRel,
    OneToOneRel,
)


__all__ = aggregates_all + constraints_all + enums_all + fields_all + indexes_all
__all__ += [
    "ObjectDoesNotExist",
    "signals",
    "CASCADE",
    "DO_NOTHING",
    "PROTECT",
    "RESTRICT",
    "SET",
    "SET_DEFAULT",
    "SET_NULL",
    "ProtectedError",
    "RestrictedError",
    "Case",
    "Exists",
    "Expression",
    "ExpressionList",
    "ExpressionWrapper",
    "F",
    "Func",
    "OrderBy",
    "OuterRef",
    "RowRange",
    "Subquery",
    "Value",
    "ValueRange",
    "When",
    "Window",
    "WindowFrame",
    "JSONField",
    "OrderWrt",
    "Lookup",
    "Transform",
    "Manager",
    "Prefetch",
    "Q",
    "QuerySet",
    "prefetch_related_objects",
    "DEFERRED",
    "Model",
    "FilteredRelation",
    "ForeignKey",
    "ForeignObject",
    "OneToOneField",
    "ManyToManyField",
    "ForeignObjectRel",
    "ManyToOneRel",
    "ManyToManyRel",
    "OneToOneRel",
]

__all__ += [
    "connection",
    "connections",
    "router",
    "DatabaseError",
    "IntegrityError",
    "InternalError",
    "ProgrammingError",
    "DataError",
    "NotSupportedError",
    "Error",
    "InterfaceError",
    "OperationalError",
    "DEFAULT_DB_ALIAS",
    "PLAIN_VERSION_PICKLE_KEY",
]

connections = ConnectionHandler()

router = ConnectionRouter()

# For backwards compatibility. Prefer connections['default'] instead.
connection = ConnectionProxy(connections, DEFAULT_DB_ALIAS)


# Register an event to reset saved queries when a Plain request is started.
def reset_queries(**kwargs):
    for conn in connections.all(initialized_only=True):
        conn.queries_log.clear()


signals.request_started.connect(reset_queries)


# Register an event to reset transaction state and close connections past
# their lifetime.
def close_old_connections(**kwargs):
    for conn in connections.all(initialized_only=True):
        conn.close_if_unusable_or_obsolete()


signals.request_started.connect(close_old_connections)
signals.request_finished.connect(close_old_connections)
