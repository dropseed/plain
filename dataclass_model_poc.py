"""
Proof of Concept: Dataclass-based Model for plain-models

This demonstrates what the Model class could look like if it was built
on top of dataclasses, enabling:
- Type annotation support
- IDE autocompletion
- Type checking with mypy/pyright
- All dataclass features (repr, eq, etc.)
- Field defaults and factory functions
"""

from __future__ import annotations

from dataclasses import dataclass, field, Field as DataclassField
from typing import Any, ClassVar, TypeVar
from datetime import datetime
from uuid import UUID

# ==============================================================================
# Field Types (simplified versions)
# ==============================================================================


def CharField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: bool = False,
    default: Any = None,
    choices: Any = None,
    db_column: str | None = None,
) -> Any:
    """String field that maps to VARCHAR in database."""
    metadata = {
        "plain_field": "CharField",
        "max_length": max_length,
        "required": required,
        "allow_null": allow_null,
        "choices": choices,
        "db_column": db_column,
    }

    if default is not None:
        return field(default=default, metadata=metadata)
    elif not required:
        return field(default=None, metadata=metadata)
    else:
        # Required field with no default
        return field(metadata=metadata)


def IntegerField(
    *,
    required: bool = True,
    allow_null: bool = False,
    default: Any = None,
    choices: Any = None,
    db_column: str | None = None,
) -> Any:
    """Integer field that maps to INTEGER in database."""
    metadata = {
        "plain_field": "IntegerField",
        "required": required,
        "allow_null": allow_null,
        "choices": choices,
        "db_column": db_column,
    }

    if default is not None:
        return field(default=default, metadata=metadata)
    elif not required:
        return field(default=None, metadata=metadata)
    else:
        return field(metadata=metadata)


def DateTimeField(
    *,
    required: bool = True,
    allow_null: bool = False,
    auto_now: bool = False,
    auto_now_add: bool = False,
    default: Any = None,
    db_column: str | None = None,
) -> Any:
    """DateTime field that maps to TIMESTAMP in database."""
    metadata = {
        "plain_field": "DateTimeField",
        "required": required,
        "allow_null": allow_null,
        "auto_now": auto_now,
        "auto_now_add": auto_now_add,
        "db_column": db_column,
    }

    if default is not None:
        return field(default=default, metadata=metadata)
    elif not required:
        return field(default=None, metadata=metadata)
    else:
        return field(metadata=metadata)


def BooleanField(
    *,
    required: bool = True,
    default: Any = None,
    db_column: str | None = None,
) -> Any:
    """Boolean field that maps to BOOLEAN in database."""
    metadata = {
        "plain_field": "BooleanField",
        "required": required,
        "db_column": db_column,
    }

    if default is not None:
        return field(default=default, metadata=metadata)
    else:
        return field(metadata=metadata)


def UUIDField(
    *,
    required: bool = True,
    allow_null: bool = False,
    default: Any = None,
    db_column: str | None = None,
) -> Any:
    """UUID field that maps to UUID in database."""
    metadata = {
        "plain_field": "UUIDField",
        "required": required,
        "allow_null": allow_null,
        "db_column": db_column,
    }

    if default is not None:
        return field(default=default, metadata=metadata)
    elif not required:
        return field(default=None, metadata=metadata)
    else:
        return field(metadata=metadata)


# ==============================================================================
# Base Model with Dataclass
# ==============================================================================

T = TypeVar("T", bound="Model")


@dataclass
class Model:
    """
    Base model class using dataclass.

    Every model automatically gets an 'id' field.
    Subclasses should use @dataclass decorator and type annotations.
    """

    # Every model gets an automatic id field (not included in __init__)
    id: int | None = field(default=None, init=False, metadata={"plain_field": "PrimaryKeyField"})

    # Class-level descriptors/managers (these aren't instance fields)
    query: ClassVar[Any] = None  # QuerySet manager would go here
    model_options: ClassVar[Any] = None  # Options descriptor
    _model_meta: ClassVar[Any] = None  # Meta information

    def __post_init__(self):
        """Called after dataclass __init__. Use for model initialization."""
        # This is where you could add validation, setup _state, etc.
        self._state = ModelState()

    def save(
        self,
        *,
        clean_and_validate: bool = True,
        force_insert: bool = False,
        force_update: bool = False,
        update_fields: list[str] | None = None,
    ) -> None:
        """Save the model instance to the database."""
        if clean_and_validate:
            self.full_clean()
        # Implementation would go here
        print(f"Saving {self.__class__.__name__} instance...")

    def delete(self) -> tuple[int, dict[str, int]]:
        """Delete the model instance from the database."""
        if self.id is None:
            raise ValueError(f"{self.__class__.__name__} object can't be deleted because its id is None.")
        print(f"Deleting {self.__class__.__name__} instance with id={self.id}...")
        return (1, {self.__class__.__name__: 1})

    def full_clean(self) -> None:
        """Validate the model instance."""
        print(f"Validating {self.__class__.__name__} instance...")

    def refresh_from_db(self, fields: list[str] | None = None) -> None:
        """Reload field values from the database."""
        print(f"Refreshing {self.__class__.__name__} instance from database...")


class ModelState:
    """Store model instance state."""
    adding: bool = True
    fields_cache: dict[str, Any] = {}


# ==============================================================================
# Example Models
# ==============================================================================


@dataclass
class User(Model):
    """
    Example User model with type annotations.

    This shows how clean and readable the model definition becomes.
    """

    # All fields are type-annotated and IDE-friendly
    email: str = CharField(max_length=255, required=True)
    username: str = CharField(max_length=150, required=True)
    first_name: str = CharField(max_length=100, required=False)
    last_name: str = CharField(max_length=100, required=False)
    is_active: bool = BooleanField(default=True)
    is_staff: bool = BooleanField(default=False)
    date_joined: datetime = DateTimeField(auto_now_add=True, required=False)

    def get_full_name(self) -> str:
        """Return the full name of the user."""
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self) -> str:
        return self.username


@dataclass
class Post(Model):
    """Example Post model with type annotations."""

    title: str = CharField(max_length=200, required=True)
    content: str = CharField(max_length=5000, required=True)
    author_id: int = IntegerField(required=True)  # ForeignKey would need special handling
    published: bool = BooleanField(default=False)
    view_count: int = IntegerField(default=0)
    created_at: datetime = DateTimeField(auto_now_add=True, required=False)
    updated_at: datetime = DateTimeField(auto_now=True, required=False)

    def publish(self) -> None:
        """Publish the post."""
        self.published = True
        self.save()

    def __str__(self) -> str:
        return self.title


@dataclass
class Article(Model):
    """Example Article model showing optional fields."""

    uuid: UUID = UUIDField(required=True)
    title: str = CharField(max_length=200, required=True)
    slug: str = CharField(max_length=200, required=True)
    body: str = CharField(max_length=10000, required=True)
    published_at: datetime | None = DateTimeField(required=False)
    author_id: int | None = IntegerField(required=False)
    tags: str = CharField(max_length=500, required=False, default="")

    @property
    def is_published(self) -> bool:
        """Check if the article is published."""
        return self.published_at is not None

    def __str__(self) -> str:
        return self.title


# ==============================================================================
# Usage Examples
# ==============================================================================


def demo_basic_usage():
    """Demonstrate basic usage of dataclass-based models."""

    print("\n=== Basic Usage ===\n")

    # Creating instances with full type safety
    user = User(
        email="john@example.com",
        username="johndoe",
        first_name="John",
        last_name="Doe",
        is_active=True,
        is_staff=False,
    )

    print(f"Created user: {user}")
    print(f"User email: {user.email}")  # IDE knows this is a str
    print(f"User full name: {user.get_full_name()}")
    print(f"User is active: {user.is_active}")  # IDE knows this is a bool

    # Save the user
    user.save()

    # Dataclass gives us nice repr for free
    print(f"\nUser repr: {repr(user)}")


def demo_optional_fields():
    """Demonstrate optional fields."""

    print("\n=== Optional Fields ===\n")

    # Can create with minimal required fields
    user = User(
        email="jane@example.com",
        username="janedoe",
        # first_name and last_name are optional
    )

    print(f"Created user: {user}")
    print(f"First name: {user.first_name}")  # Will be None


def demo_defaults():
    """Demonstrate default values."""

    print("\n=== Default Values ===\n")

    post = Post(
        title="My First Post",
        content="This is the content of my first post.",
        author_id=1,
        # published defaults to False
        # view_count defaults to 0
    )

    print(f"Created post: {post}")
    print(f"Published: {post.published}")  # False
    print(f"View count: {post.view_count}")  # 0

    post.publish()
    print(f"After publish - Published: {post.published}")  # True


def demo_type_checking():
    """
    Demonstrate type checking benefits.

    With type annotations, your IDE and type checker can catch errors:
    - user.email is known to be str
    - user.is_active is known to be bool
    - user.id is known to be int | None

    This would catch errors like:
    - user.email.some_int_method()  # Error: str has no such method
    - if user.is_active == "yes":  # Warning: comparing bool to str
    """

    print("\n=== Type Checking Benefits ===\n")

    user = User(
        email="test@example.com",
        username="testuser",
    )

    # Type checker knows email is str
    email_upper: str = user.email.upper()
    print(f"Email uppercase: {email_upper}")

    # Type checker knows is_active is bool
    if user.is_active:
        print("User is active")

    # Type checker knows id is int | None
    user_id: int | None = user.id
    if user_id is not None:
        # Now type checker knows user_id is int (narrowed type)
        id_times_two: int = user_id * 2
        print(f"ID times 2: {id_times_two}")


def demo_dataclass_features():
    """Demonstrate built-in dataclass features."""

    print("\n=== Dataclass Features ===\n")

    user1 = User(email="test@example.com", username="user1")
    user2 = User(email="test@example.com", username="user1")

    # Dataclass gives us __eq__ for free (though we'd override for Model)
    print(f"user1 == user2: {user1 == user2}")

    # We also get a nice __repr__
    print(f"User repr:\n{repr(user1)}")

    # Could use dataclass features like:
    # - replace() to create modified copies
    # - fields() to introspect fields
    # - asdict() to convert to dict


# ==============================================================================
# Comparison: Current vs Dataclass-based
# ==============================================================================


def print_comparison():
    """Print a comparison of current vs dataclass approach."""

    comparison = """

=== COMPARISON: Current vs Dataclass-based Model ===

CURRENT APPROACH (plain-models today):
--------------------------------------

class User(Model):
    email = CharField(max_length=255)
    username = CharField(max_length=150)
    first_name = CharField(max_length=100, required=False)
    is_active = BooleanField(default=True)

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

# Issues:
# - No type hints on fields
# - IDE doesn't know user.email is a string
# - Type checkers can't verify correctness
# - No autocompletion for field values
# - Runtime attribute assignment


DATACLASS APPROACH (this POC):
-------------------------------

@dataclass
class User(Model):
    email: str = CharField(max_length=255)
    username: str = CharField(max_length=150)
    first_name: str = CharField(max_length=100, required=False)
    is_active: bool = BooleanField(default=True)

    def get_full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

# Benefits:
# ✓ Full type annotations
# ✓ IDE knows user.email is str
# ✓ Type checkers can verify (mypy, pyright, etc.)
# ✓ Better autocompletion
# ✓ Fields defined at class definition time
# ✓ Free __repr__, __eq__, etc. from dataclass
# ✓ Can use dataclass features (replace, asdict, etc.)
# ✓ More Pythonic and modern
# ✓ Better static analysis


USAGE COMPARISON:
-----------------

# Both approaches would work the same:
user = User(
    email="test@example.com",
    username="testuser",
    first_name="Test",
    is_active=True,
)
user.save()

# But with dataclass approach:
# - Your IDE gives better hints
# - Type checker catches mistakes
# - Code is more maintainable
# - Integration with modern Python tools is better


CHALLENGES TO SOLVE:
---------------------

1. Field descriptors - DeferredAttribute pattern needs to work
2. QuerySet descriptor - How to make Model.query work
3. Metaclass magic - ModelBase does important setup
4. Field introspection - Need to extract metadata from dataclass fields
5. Migrations - Need to detect field changes from dataclass fields
6. ForeignKey/relationships - More complex field types
7. Model inheritance - Plain doesn't support it, but need to ensure it stays that way
8. Performance - Dataclass __init__ vs current optimized __init__
9. Backward compatibility - Migration path for existing code


HYBRID APPROACH:
----------------

Could potentially use a hybrid where:
- User writes dataclass-style code with type annotations
- Metaclass converts it to current internal representation
- Best of both worlds: nice DX, same runtime behavior

Example:
@dataclass  # or custom @plain_model decorator
class User(Model):
    email: str = CharField(max_length=255)
    # ... more fields

# Metaclass sees this and converts to current Field system
# but preserves type information for IDE/type checkers
    """

    print(comparison)


# ==============================================================================
# Main
# ==============================================================================


if __name__ == "__main__":
    print("=" * 70)
    print("DATACLASS-BASED MODEL PROOF OF CONCEPT")
    print("=" * 70)

    # Run demos
    demo_basic_usage()
    demo_optional_fields()
    demo_defaults()
    demo_type_checking()
    demo_dataclass_features()

    # Show comparison
    print_comparison()

    print("\n" + "=" * 70)
    print("See the source code above for implementation details")
    print("=" * 70)
