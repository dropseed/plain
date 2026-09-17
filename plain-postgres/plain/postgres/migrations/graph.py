from __future__ import annotations

from functools import total_ordering
from typing import TYPE_CHECKING, Any, cast

from plain.postgres.migrations.state import ProjectState

from .exceptions import CircularDependencyError, NodeNotFoundError

if TYPE_CHECKING:
    from plain.postgres.migrations.migration import Migration


@total_ordering
class Node:
    """
    A single node in the migration graph. Contains direct links to adjacent
    nodes in either direction.
    """

    def __init__(self, key: tuple[str, str]):
        self.key = key
        self.children: set[Node] = set()
        self.parents: set[Node] = set()

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Node):
            return self.key == other.key
        return self.key == other

    def __lt__(self, other: object) -> bool:
        if isinstance(other, Node):
            return self.key < other.key
        if isinstance(other, tuple):
            return self.key < cast(tuple[str, str], other)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.key)

    def __getitem__(self, item: int) -> str:
        return self.key[item]

    def __str__(self) -> str:
        return str(self.key)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: ({self.key[0]!r}, {self.key[1]!r})>"

    def add_child(self, child: Node) -> None:
        self.children.add(child)

    def add_parent(self, parent: Node) -> None:
        self.parents.add(parent)


class DummyNode(Node):
    """
    A node that doesn't correspond to a migration file on disk.
    (A dependency on a migration that was deleted, for example.)

    After the migration graph is processed, all dummy nodes should be removed.
    If there are any left, a nonexistent dependency error is raised.
    """

    def __init__(
        self,
        key: tuple[str, str],
        origin: Migration | tuple[str, str] | None,
        error_message: str,
    ):
        super().__init__(key)
        self.origin = origin
        self.error_message = error_message

    def raise_error(self) -> None:
        raise NodeNotFoundError(self.error_message, self.key, origin=self.origin)


class MigrationGraph:
    """
    Represent the digraph of all migrations in a project.

    Each migration is a node, and each dependency is an edge. There are
    no implicit dependencies between numbered migrations - the numbering is
    merely a convention to aid file listing. Every new numbered migration
    has a declared dependency to the previous number, meaning that VCS
    branch merges can be detected and resolved.

    A node should be a tuple: (app_path, migration_name). The tree special-cases
    things within an app - namely, root nodes and leaf nodes ignore dependencies
    to other packages.
    """

    def __init__(self):
        self.node_map: dict[tuple[str, str], Node] = {}
        self.nodes: dict[tuple[str, str], Migration | None] = {}

    def add_node(self, key: tuple[str, str], migration: Migration) -> None:
        assert key not in self.node_map
        node = Node(key)
        self.node_map[key] = node
        self.nodes[key] = migration

    def add_dummy_node(
        self,
        key: tuple[str, str],
        origin: Migration | tuple[str, str] | None,
        error_message: str,
    ) -> None:
        node = DummyNode(key, origin, error_message)
        self.node_map[key] = node
        self.nodes[key] = None

    def add_dependency(
        self,
        migration: Migration | tuple[str, str] | None,
        child: tuple[str, str],
        parent: tuple[str, str],
        skip_validation: bool = False,
    ) -> None:
        """
        This may create dummy nodes if they don't yet exist. If
        `skip_validation=True`, validate_consistency() should be called
        afterward.
        """
        if child not in self.nodes:
            error_message = (
                f"Migration {migration} dependencies reference nonexistent"
                f" child node {child!r}"
            )
            self.add_dummy_node(child, migration, error_message)
        if parent not in self.nodes:
            error_message = (
                f"Migration {migration} dependencies reference nonexistent"
                f" parent node {parent!r}"
            )
            self.add_dummy_node(parent, migration, error_message)
        self.node_map[child].add_parent(self.node_map[parent])
        self.node_map[parent].add_child(self.node_map[child])
        if not skip_validation:
            self.validate_consistency()

    def validate_consistency(self) -> None:
        """Ensure there are no dummy nodes remaining in the graph."""
        [n.raise_error() for n in self.node_map.values() if isinstance(n, DummyNode)]

    def forwards_plan(self, target: tuple[str, str]) -> list[tuple[str, str]]:
        """
        Given a node, return a list of which previous nodes (dependencies) must
        be applied, ending with the node itself. This is the list you would
        follow if applying the migrations to a database.
        """
        if target not in self.nodes:
            raise NodeNotFoundError(f"Node {target!r} not a valid node", target)
        return self.iterative_dfs(self.node_map[target])

    def iterative_dfs(
        self, start: Node, forwards: bool = True
    ) -> list[tuple[str, str]]:
        """Iterative depth-first search for finding dependencies."""
        visited: list[tuple[str, str]] = []
        visited_set: set[Node] = set()
        stack: list[tuple[Node, bool]] = [(start, False)]
        while stack:
            node, processed = stack.pop()
            if node in visited_set:
                pass
            elif processed:
                visited_set.add(node)
                visited.append(node.key)
            else:
                stack.append((node, True))
                stack += [
                    (n, False)
                    for n in sorted(node.parents if forwards else node.children)
                ]
        return visited

    def root_nodes(self, app: str | None = None) -> list[tuple[str, str]]:
        """
        Return all root nodes - that is, nodes with no dependencies inside
        their app. These are the starting point for an app.
        """
        roots: set[tuple[str, str]] = set()
        for node in self.nodes:
            if all(key[0] != node[0] for key in self.node_map[node].parents) and (
                not app or app == node[0]
            ):
                roots.add(node)
        return sorted(roots)

    def leaf_nodes(self, app: str | None = None) -> list[tuple[str, str]]:
        """
        Return all leaf nodes - that is, nodes with no dependents in their app.
        These are the "most current" version of an app's schema.
        Having more than one per app is technically an error, but one that
        gets handled further up, in the interactive command - it's usually the
        result of a VCS merge and needs some user input.
        """
        leaves: set[tuple[str, str]] = set()
        for node in self.nodes:
            if all(key[0] != node[0] for key in self.node_map[node].children) and (
                not app or app == node[0]
            ):
                leaves.add(node)
        return sorted(leaves)

    def ensure_not_cyclic(self) -> None:
        # Algo from GvR:
        # https://neopythonic.blogspot.com/2009/01/detecting-cycles-in-directed-graph.html
        todo: set[tuple[str, str]] = set(self.nodes)
        while todo:
            node = todo.pop()
            stack: list[tuple[str, str]] = [node]
            while stack:
                top = stack[-1]
                for child in self.node_map[top].children:
                    # Use child.key instead of child to speed up the frequent
                    # hashing.
                    node = child.key
                    if node in stack:
                        cycle = stack[stack.index(node) :]
                        raise CircularDependencyError(
                            ", ".join("{}.{}".format(*n) for n in cycle)
                        )
                    if node in todo:
                        stack.append(node)
                        todo.remove(node)
                        break
                else:
                    node = stack.pop()

    def __str__(self) -> str:
        return "Graph: {} nodes, {} edges".format(*self._nodes_and_edges())

    def __repr__(self) -> str:
        nodes, edges = self._nodes_and_edges()
        return f"<{self.__class__.__name__}: nodes={nodes}, edges={edges}>"

    def _nodes_and_edges(self) -> tuple[int, int]:
        return len(self.nodes), sum(
            len(node.parents) for node in self.node_map.values()
        )

    def _generate_plan(
        self, nodes: list[tuple[str, str]], at_end: bool
    ) -> list[tuple[str, str]]:
        plan: list[tuple[str, str]] = []
        for node in nodes:
            for migration in self.forwards_plan(node):
                if migration not in plan and (at_end or migration not in nodes):
                    plan.append(migration)
        return plan

    def make_state(
        self,
        nodes: tuple[str, str] | list[tuple[str, str]] | None = None,
        at_end: bool = True,
        real_packages: Any = None,
    ) -> ProjectState:
        """
        Given a migration node or nodes, return a complete ProjectState for it.
        If at_end is False, return the state before the migration has run.
        If nodes is not provided, return the overall most current project state.
        """
        if nodes is None:
            nodes = list(self.leaf_nodes())
        if not nodes:
            return ProjectState()
        if not isinstance(nodes[0], tuple):
            nodes = cast(list[tuple[str, str]], [nodes])
        assert isinstance(nodes, list)  # Type narrowing after checks above
        plan = self._generate_plan(nodes, at_end)
        project_state = ProjectState(real_packages=real_packages)
        for node in plan:
            migration = self.nodes[node]
            if migration is None:
                raise NodeNotFoundError(
                    f"Migration {node} is a placeholder with no migration to apply",
                    node,
                )
            project_state = migration.mutate_state(project_state, preserve=False)
        return project_state

    def __contains__(self, node: tuple[str, str]) -> bool:
        return node in self.nodes
