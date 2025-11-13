"""
A class for storing a tree graph. Primarily used for filter constructs in the
ORM.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from typing import Self

from plain.utils.hashable import make_hashable


class Node:
    """
    A single internal node in the tree graph. A Node should be viewed as a
    connection (the root) with the children being either leaf nodes or other
    Node instances.
    """

    # Standard connector type. Clients usually won't use this at all and
    # subclasses will usually override the value.
    default: str = "DEFAULT"

    def __init__(
        self,
        children: list[Any] | None = None,
        connector: str | None = None,
        negated: bool = False,
    ) -> None:
        """Construct a new Node. If no connector is given, use the default."""
        self.children: list[Any] = children[:] if children else []
        self.connector: str = connector or self.default
        self.negated: bool = negated

    @classmethod
    def create(
        cls,
        children: list[Any] | None = None,
        connector: str | None = None,
        negated: bool = False,
    ) -> Self:
        """
        Create a new instance using Node() instead of __init__() as some
        subclasses, e.g. plain.models.query_utils.Q, may implement a custom
        __init__() with a signature that conflicts with the one defined in
        Node.__init__().
        """
        obj = Node(children, connector or cls.default, negated)
        obj.__class__ = cls
        return obj  # type: ignore[return-value]

    def __str__(self) -> str:
        template = "(NOT (%s: %s))" if self.negated else "(%s: %s)"
        return template % (self.connector, ", ".join(str(c) for c in self.children))

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self}>"

    def __copy__(self) -> Self:
        obj = self.create(connector=self.connector, negated=self.negated)
        obj.children = self.children  # Don't [:] as .__init__() via .create() does.
        return obj

    copy = __copy__

    def __deepcopy__(self, memodict: dict[int, Any]) -> Self:
        obj = self.create(connector=self.connector, negated=self.negated)
        obj.children = copy.deepcopy(self.children, memodict)
        return obj

    def __len__(self) -> int:
        """Return the number of children this node has."""
        return len(self.children)

    def __bool__(self) -> bool:
        """Return whether or not this node has children."""
        return bool(self.children)

    def __contains__(self, other: Any) -> bool:
        """Return True if 'other' is a direct child of this instance."""
        return other in self.children

    def __eq__(self, other: Any) -> bool:
        return (
            self.__class__ == other.__class__
            and self.connector == other.connector
            and self.negated == other.negated
            and self.children == other.children
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.__class__,
                self.connector,
                self.negated,
                *make_hashable(self.children),
            )
        )

    def add(self, data: Any, conn_type: str) -> Any:
        """
        Combine this tree and the data represented by data using the
        connector conn_type. The combine is done by squashing the node other
        away if possible.

        This tree (self) will never be pushed to a child node of the
        combined tree, nor will the connector or negated properties change.

        Return a node which can be used in place of data regardless if the
        node other got squashed or not.
        """
        if self.connector != conn_type:
            obj = self.copy()
            self.connector = conn_type
            self.children = [obj, data]
            return data
        elif (
            isinstance(data, Node)
            and not data.negated
            and (data.connector == conn_type or len(data) == 1)
        ):
            # We can squash the other node's children directly into this node.
            # We are just doing (AB)(CD) == (ABCD) here, with the addition that
            # if the length of the other node is 1 the connector doesn't
            # matter. However, for the len(self) == 1 case we don't want to do
            # the squashing, as it would alter self.connector.
            self.children.extend(data.children)
            return self
        else:
            # We could use perhaps additional logic here to see if some
            # children could be used for pushdown here.
            self.children.append(data)
            return data

    def negate(self) -> None:
        """Negate the sense of the root connector."""
        self.negated = not self.negated
