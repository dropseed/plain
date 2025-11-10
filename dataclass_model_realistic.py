"""
Realistic Dataclass-based Model Implementation

This shows a more complete implementation that handles:
- Metaclass integration
- Field descriptors
- QuerySet integration
- Field introspection from dataclass metadata
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, Field as DataclassField, MISSING
from typing import Any, ClassVar, TypeVar, Generic, get_type_hints
from datetime import datetime

# ==============================================================================
# Field Descriptor System
# ==============================================================================


class DeferredAttribute:
    """
    Descriptor for accessing model field values.

    This enables lazy loading, change tracking, and other features.
    """

    def __init__(self, field_name: str, field_metadata: dict[str, Any]):
        self.field_name = field_name
        self.field_metadata = field_metadata

    def __get__(self, instance: Any, owner: type | None = None):
        if instance is None:
            # Accessing from class, return descriptor
            return self

        # Check if value is deferred (not loaded from database)
        if self.field_name in instance._state.deferred_fields:
            # Load from database
            instance.refresh_from_db(fields=[self.field_name])

        # Return the value from instance __dict__
        return instance.__dict__.get(self.field_name)

    def __set__(self, instance: Any, value: Any):
        # Track that field has changed
        if hasattr(instance, '_state'):
            instance._state.changed_fields.add(self.field_name)

        # Store value in instance __dict__
        instance.__dict__[self.field_name] = value


# ==============================================================================
# QuerySet System
# ==============================================================================


T = TypeVar('T')


class QuerySet(Generic[T]):
    """Generic QuerySet that returns typed model instances."""

    def __init__(self, model_class: type[T] | None = None):
        self.model_class = model_class
        self._filters = []

    def __get__(self, instance: Any, owner: type[T]) -> QuerySet[T]:
        """Descriptor protocol - bind to model class when accessed."""
        if instance is not None:
            raise AttributeError("QuerySet is only accessible via class, not instance")
        # Return new QuerySet bound to this model class
        return QuerySet(owner)

    def filter(self, **kwargs) -> QuerySet[T]:
        """Filter queryset - returns same type."""
        new_qs = QuerySet(self.model_class)
        new_qs._filters = self._filters + [kwargs]
        return new_qs

    def get(self, **kwargs) -> T:
        """Get single instance - returns model type."""
        # Simulate database fetch
        print(f"Fetching {self.model_class.__name__} with {kwargs}")
        # Create instance (simplified)
        if self.model_class:
            return self.model_class(**kwargs)
        raise ValueError("No model class")

    def all(self) -> QuerySet[T]:
        """Return all instances."""
        return QuerySet(self.model_class)

    def count(self) -> int:
        """Return count of instances."""
        return 0  # Simplified


# ==============================================================================
# Model State
# ==============================================================================


class ModelState:
    """Track model instance state."""

    def __init__(self):
        self.adding = True  # True if not yet saved to DB
        self.deferred_fields: set[str] = set()  # Fields not loaded from DB
        self.changed_fields: set[str] = set()  # Fields modified since load


# ==============================================================================
# Field Factory Functions
# ==============================================================================


def CharField(
    *,
    max_length: int | None = None,
    required: bool = True,
    default: Any = MISSING,
) -> Any:
    """Create a string field for dataclass with Plain metadata."""
    metadata = {
        'plain_field_type': 'CharField',
        'max_length': max_length,
        'required': required,
    }

    if default is not MISSING:
        return field(default=default, metadata=metadata)
    elif not required:
        return field(default=None, metadata=metadata)
    else:
        return field(metadata=metadata)


def IntegerField(
    *,
    required: bool = True,
    default: Any = MISSING,
) -> Any:
    """Create an integer field for dataclass with Plain metadata."""
    metadata = {
        'plain_field_type': 'IntegerField',
        'required': required,
    }

    if default is not MISSING:
        return field(default=default, metadata=metadata)
    elif not required:
        return field(default=None, metadata=metadata)
    else:
        return field(metadata=metadata)


def BooleanField(
    *,
    default: Any = MISSING,
) -> Any:
    """Create a boolean field for dataclass with Plain metadata."""
    metadata = {
        'plain_field_type': 'BooleanField',
        'required': True,
    }

    if default is not MISSING:
        return field(default=default, metadata=metadata)
    else:
        return field(metadata=metadata)


def DateTimeField(
    *,
    auto_now: bool = False,
    auto_now_add: bool = False,
    required: bool = True,
) -> Any:
    """Create a datetime field for dataclass with Plain metadata."""
    metadata = {
        'plain_field_type': 'DateTimeField',
        'auto_now': auto_now,
        'auto_now_add': auto_now_add,
        'required': required,
    }

    # auto_now and auto_now_add fields always default to None
    # They get set automatically on save
    if auto_now or auto_now_add or not required:
        return field(default=None, metadata=metadata)
    else:
        return field(metadata=metadata)


# ==============================================================================
# Metaclass that Integrates Dataclass and Plain Models
# ==============================================================================


class ModelMeta(type):
    """
    Metaclass that:
    1. Applies dataclass transformation
    2. Extracts field metadata
    3. Sets up field descriptors
    4. Registers the model
    """

    def __new__(mcs, name: str, bases: tuple[type, ...], attrs: dict[str, Any], **kwargs):
        # Don't process the base Model class itself
        if name == 'Model' and not bases:
            return super().__new__(mcs, name, bases, attrs)

        # Apply dataclass decorator FIRST
        # This processes annotations and creates __init__
        cls = super().__new__(mcs, name, bases, attrs)
        cls = dataclass(cls)

        # Now extract Plain field information from dataclass fields
        type_hints = get_type_hints(cls)
        plain_fields = {}

        for dc_field in fields(cls):
            # Skip special fields (like id, _state)
            if dc_field.name.startswith('_'):
                continue

            # Check if this is a Plain field (has our metadata)
            if 'plain_field_type' in dc_field.metadata:
                # Get the type annotation
                field_type = type_hints.get(dc_field.name)

                # Store field info
                plain_fields[dc_field.name] = {
                    'name': dc_field.name,
                    'type': field_type,
                    'metadata': dc_field.metadata,
                    'dc_field': dc_field,
                }

                # IMPORTANT: Replace the dataclass field with our descriptor
                # This allows us to intercept access and implement lazy loading
                descriptor = DeferredAttribute(dc_field.name, dc_field.metadata)
                setattr(cls, dc_field.name, descriptor)

        # Store field information on the class
        cls._plain_fields = plain_fields

        # Set up model metadata
        cls._model_meta = type('Meta', (), {
            'fields': plain_fields,
            'model_name': name,
        })

        print(f"Registered model: {name} with fields: {list(plain_fields.keys())}")

        return cls


# ==============================================================================
# Base Model Class
# ==============================================================================


@dataclass
class Model(metaclass=ModelMeta):
    """
    Base model class using dataclass + metaclass.

    Features:
    - Type annotations for IDE/type checker support
    - Dataclass benefits (init, repr, etc.)
    - Plain model features (descriptors, lazy loading, etc.)
    """

    # Primary key field (not part of __init__)
    id: int | None = field(default=None, init=False, repr=True)

    # State tracking (not part of __init__)
    _state: ModelState = field(default_factory=ModelState, init=False, repr=False)

    # Class-level query manager (not an instance field)
    query: ClassVar[QuerySet] = QuerySet()

    def __post_init__(self):
        """Called after dataclass __init__."""
        # Additional setup if needed
        # Note: _state is already created by dataclass default_factory
        pass

    def save(self, *, validate: bool = True) -> None:
        """Save the model instance."""
        if validate:
            self.full_clean()

        # Auto-update auto_now fields
        for field_name, field_info in self._plain_fields.items():
            if field_info['metadata'].get('auto_now'):
                setattr(self, field_name, datetime.now())

        # Auto-set auto_now_add fields on first save
        if self._state.adding:
            for field_name, field_info in self._plain_fields.items():
                if field_info['metadata'].get('auto_now_add'):
                    setattr(self, field_name, datetime.now())

        print(f"Saving {self.__class__.__name__} (id={self.id})")
        # Simulate save...
        if self.id is None:
            self.id = 123  # Simulate database-assigned ID

        self._state.adding = False
        self._state.changed_fields.clear()

    def delete(self) -> tuple[int, dict[str, int]]:
        """Delete the model instance."""
        if self.id is None:
            raise ValueError("Cannot delete unsaved instance")
        print(f"Deleting {self.__class__.__name__} (id={self.id})")
        return (1, {self.__class__.__name__: 1})

    def full_clean(self) -> None:
        """Validate the model instance."""
        print(f"Validating {self.__class__.__name__}")
        # Validation logic here

    def refresh_from_db(self, fields: list[str] | None = None) -> None:
        """Reload from database."""
        print(f"Refreshing {self.__class__.__name__} from database")
        # Database refresh logic here

    @classmethod
    def get_fields(cls) -> dict[str, dict[str, Any]]:
        """Get field information - useful for introspection."""
        return cls._plain_fields.copy()


# ==============================================================================
# Example Models
# ==============================================================================


@dataclass
class User(Model):
    """
    User model with full type annotations.

    Type checkers see:
    - email: str
    - username: str
    - first_name: str | None
    - last_name: str | None
    - is_active: bool
    - is_staff: bool
    - date_joined: datetime | None
    """

    email: str = CharField(max_length=255)
    username: str = CharField(max_length=150)
    first_name: str = CharField(max_length=100, required=False)
    last_name: str = CharField(max_length=100, required=False)
    is_active: bool = BooleanField(default=True)
    is_staff: bool = BooleanField(default=False)
    date_joined: datetime | None = DateTimeField(auto_now_add=True)

    def get_full_name(self) -> str:
        """Get user's full name."""
        parts = [self.first_name, self.last_name]
        return ' '.join(p for p in parts if p) or self.username

    def __str__(self) -> str:
        return self.username


@dataclass
class Post(Model):
    """Blog post model."""

    # Required fields first
    title: str = CharField(max_length=200)
    content: str = CharField(max_length=5000)
    author_id: int = IntegerField()
    # Fields with defaults after
    published: bool = BooleanField(default=False)
    view_count: int = IntegerField(default=0)
    # Auto fields last (they have defaults of None)
    created_at: datetime | None = DateTimeField(auto_now_add=True, required=False)
    updated_at: datetime | None = DateTimeField(auto_now=True, required=False)

    def publish(self) -> None:
        """Publish the post."""
        self.published = True
        self.save()

    def increment_views(self) -> None:
        """Increment view count."""
        self.view_count += 1
        self.save()

    def __str__(self) -> str:
        return self.title


# ==============================================================================
# Demonstrations
# ==============================================================================


def demo_type_safety():
    """Demonstrate type safety benefits."""
    print("\n" + "=" * 70)
    print("TYPE SAFETY DEMONSTRATION")
    print("=" * 70)

    # Create user - IDE provides autocompletion for all parameters
    user = User(
        email="alice@example.com",
        username="alice",
        first_name="Alice",
        last_name="Smith",
        is_active=True,
        is_staff=False,
    )

    # Type checker knows these types:
    email: str = user.email  # ✓ str
    is_active: bool = user.is_active  # ✓ bool
    first_name: str | None = user.first_name  # ✓ str | None

    print(f"User email (str): {email}")
    print(f"User active (bool): {is_active}")
    print(f"User first name (str | None): {first_name}")

    # This would be caught by type checker:
    # user.email = 123  # Error: int is not assignable to str
    # user.is_active.upper()  # Error: bool has no method upper


def demo_queryset_typing():
    """Demonstrate typed QuerySet."""
    print("\n" + "=" * 70)
    print("QUERYSET TYPING DEMONSTRATION")
    print("=" * 70)

    # QuerySet operations are fully typed
    users: QuerySet[User] = User.query.filter(is_active=True)
    print(f"Filtered users: {users}")

    # get() returns User, not Model
    user: User = User.query.get(username="test", email="test@example.com")
    print(f"Got user: {user}")
    # Simulate setting ID after "loading from database"
    user.id = 1

    # Type checker knows user is User
    full_name: str = user.get_full_name()
    print(f"Full name: {full_name}")


def demo_field_introspection():
    """Demonstrate field introspection."""
    print("\n" + "=" * 70)
    print("FIELD INTROSPECTION DEMONSTRATION")
    print("=" * 70)

    print("\nUser fields:")
    for field_name, field_info in User.get_fields().items():
        print(f"  {field_name}:")
        print(f"    Type: {field_info['type']}")
        print(f"    Field: {field_info['metadata']['plain_field_type']}")
        print(f"    Required: {field_info['metadata']['required']}")
        if 'max_length' in field_info['metadata']:
            print(f"    Max length: {field_info['metadata']['max_length']}")


def demo_model_usage():
    """Demonstrate full model lifecycle."""
    print("\n" + "=" * 70)
    print("MODEL LIFECYCLE DEMONSTRATION")
    print("=" * 70)

    # Create and save
    post = Post(
        title="My First Post",
        content="This is a great post about dataclasses!",
        author_id=1,
    )
    print(f"\nCreated: {post}")
    print(f"State - adding: {post._state.adding}")

    post.save()
    print(f"State - adding: {post._state.adding}")
    print(f"Post ID: {post.id}")

    # Modify and save again
    post.publish()
    print(f"Published: {post.published}")

    # Increment views
    post.increment_views()
    print(f"Views: {post.view_count}")


def demo_dataclass_features():
    """Demonstrate dataclass features we get for free."""
    print("\n" + "=" * 70)
    print("DATACLASS FEATURES DEMONSTRATION")
    print("=" * 70)

    user1 = User(
        email="bob@example.com",
        username="bob",
    )

    user2 = User(
        email="bob@example.com",
        username="bob",
    )

    # Nice repr for free
    print(f"\nUser repr:\n{repr(user1)}")

    # Equality (though we'd override for Model to check ID)
    print(f"\nuser1 == user2: {user1 == user2}")

    # Can introspect with dataclass fields()
    from dataclasses import fields as dc_fields
    print(f"\nDataclass fields:")
    for f in dc_fields(User):
        print(f"  {f.name}: {f.type}")


# ==============================================================================
# Main
# ==============================================================================


if __name__ == "__main__":
    print("=" * 70)
    print("REALISTIC DATACLASS-BASED MODEL IMPLEMENTATION")
    print("=" * 70)

    demo_type_safety()
    demo_queryset_typing()
    demo_field_introspection()
    demo_model_usage()
    demo_dataclass_features()

    print("\n" + "=" * 70)
    print("This demonstrates a production-ready approach to dataclass models!")
    print("=" * 70)
