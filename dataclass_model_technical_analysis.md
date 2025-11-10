# Dataclass-based Model: Technical Analysis

This document provides a detailed technical analysis of what it would take to make Plain's Model class based on dataclasses, enabling full type annotation support.

## Quick Summary

**The POC demonstrates:** A dataclass-based Model can provide excellent type safety and IDE support while maintaining a similar API to the current Plain models.

**Key insight:** We can use dataclass field metadata to store Plain's field configuration, allowing type annotations to coexist with database field definitions.

## Core Design

### Current Approach

```python
class User(Model):
    email = CharField(max_length=255)
    username = CharField(max_length=150)
    is_active = BooleanField(default=True)
```

**How it works:**
- Fields are class attributes assigned to Field instances
- ModelBase metaclass collects these Field instances
- Field instances use descriptors (DeferredAttribute) to intercept attribute access
- At runtime, instance.__dict__ contains the actual values
- `__init__` is custom and highly optimized for performance

**Problems:**
- No type information for IDE/type checkers
- IDE doesn't know `user.email` is a string
- Can't use modern Python typing tools

### Dataclass Approach

```python
@dataclass
class User(Model):
    email: str = CharField(max_length=255)
    username: str = CharField(max_length=150)
    is_active: bool = BooleanField(default=True)
```

**How it would work:**
- Fields are type-annotated class attributes
- CharField() returns a dataclass.field() with metadata
- Dataclass generates __init__ from annotations
- Metaclass extracts field info from dataclass fields
- Type checkers see the annotations

**Benefits:**
- Full type safety
- IDE autocompletion works perfectly
- Type checkers (mypy, pyright) can verify code
- More modern and Pythonic
- Free __repr__, __eq__, etc.

## Implementation Challenges

### 1. Field Descriptors

**Challenge:** Plain uses DeferredAttribute descriptors to enable lazy loading and change tracking.

**Current implementation:**
```python
class DeferredAttribute:
    def __get__(self, instance, cls):
        # Load field from database if deferred
        # Return cached value
        pass
```

**Solution for dataclass:**
Dataclass fields need to remain as regular attributes for type checking, but we can:

1. Use `__post_init__` to set up descriptors after dataclass __init__
2. Replace class-level field definitions with descriptors in metaclass
3. Store field values in a separate namespace (like _field_values)

Example:
```python
@dataclass
class Model:
    def __post_init__(self):
        # Move values to internal storage
        # Set up descriptors
        pass
```

### 2. QuerySet Descriptor

**Challenge:** `Model.query` needs to be a class-level descriptor but shouldn't be an instance field.

**Current:**
```python
class Model:
    query = QuerySet()  # Descriptor
```

**Solution:**
Use `ClassVar` annotation to exclude from dataclass:
```python
@dataclass
class Model:
    query: ClassVar[QuerySet] = QuerySet()
```

This tells dataclass to ignore it but keeps type information.

### 3. Metaclass Integration

**Challenge:** Both dataclass and ModelBase use metaclasses. How do they coexist?

**Current metaclass responsibilities:**
- Collecting Field instances from class attributes
- Setting up Options and Meta
- Registering models
- Validation checks

**Solutions:**

Option A: Sequential processing
```python
class ModelBase(type):
    def __new__(cls, name, bases, attrs, **kwargs):
        # Let dataclass process first
        new_class = dataclass(super().__new__(cls, name, bases, attrs))
        # Then do our Model setup
        cls._setup_fields(new_class)
        return new_class
```

Option B: Custom decorator instead of @dataclass
```python
def plain_model(cls):
    # Apply dataclass
    cls = dataclass(cls)
    # Apply Plain model magic
    return cls

@plain_model
class User(Model):
    ...
```

Option C: Make ModelBase handle both
```python
class ModelBase(type):
    def __new__(cls, name, bases, attrs, **kwargs):
        # Extract annotations and field definitions
        # Apply dataclass transformation
        # Apply Plain model setup
        # Return combined class
        pass
```

**Recommendation:** Option A is cleanest - use Python 3.10+ `__init_subclass__` hooks.

### 4. Field Introspection

**Challenge:** Migrations and other tools need to introspect model fields.

**Current:**
```python
for field in Model._model_meta.fields:
    print(field.name, field.max_length)
```

**With dataclass:**
```python
from dataclasses import fields

for dc_field in fields(Model):
    plain_metadata = dc_field.metadata
    print(dc_field.name, plain_metadata.get('max_length'))
```

The metadata dict in dataclass fields is perfect for storing Plain field configuration!

### 5. Field Definition Functions

**Challenge:** CharField() needs to return both a dataclass field AND preserve Plain config.

**Implementation:**
```python
def CharField(
    *,
    max_length: int | None = None,
    required: bool = True,
    default: Any = None,
) -> Any:
    """Returns a dataclass field with Plain metadata."""
    metadata = {
        'plain_field': 'CharField',
        'max_length': max_length,
        'required': required,
    }

    if default is not None:
        return field(default=default, metadata=metadata)
    elif not required:
        return field(default=None, metadata=metadata)
    else:
        return field(metadata=metadata)
```

The return type annotation is `Any` to not confuse type checkers.

### 6. ForeignKey and Relationships

**Challenge:** Relationships are complex and need special handling.

**Current:**
```python
class Post(Model):
    author = ForeignKey(User, on_delete=CASCADE)
```

**Dataclass approach:**
```python
@dataclass
class Post(Model):
    author_id: int = ForeignKey(User, on_delete=CASCADE)
    # Maybe also:
    author: User | None = field(init=False, default=None)
```

Challenges:
- ForeignKey creates both `author_id` and `author` attributes
- Type of `author` is `User | None` but defined via `author_id`
- Related manager setup

**Potential solution:**
```python
def ForeignKey(to: type[Model], *, on_delete, required=True):
    """Returns field metadata for a foreign key."""
    metadata = {
        'plain_field': 'ForeignKey',
        'to': to,
        'on_delete': on_delete,
        'required': required,
    }

    # Return the _id field
    if required:
        return field(metadata=metadata)
    else:
        return field(default=None, metadata=metadata)
```

Then in metaclass, create the related object descriptor separately.

### 7. Primary Key Field

**Challenge:** Every model gets an automatic `id` field.

**Solution:**
```python
@dataclass
class Model:
    # Use init=False so it's not required in __init__
    id: int | None = field(default=None, init=False)
```

Subclasses automatically inherit this field.

### 8. Performance

**Challenge:** Current `__init__` is highly optimized for bulk loading from database.

**Current optimization:**
```python
def __init__(self, *args, **kwargs):
    # Optimized for positional args from database
    # Uses direct setattr to bypass descriptors
    # Special handling for deferred fields
    pass
```

**Dataclass concern:**
- Dataclass-generated `__init__` might be slower
- Need to benchmark

**Solutions:**
1. Keep optimized `from_db()` classmethod for database loading
2. Override `__init__` if needed for performance
3. Benchmark and optimize as needed

Python's dataclass is pretty fast, but we can always override:
```python
@dataclass
class Model:
    def __init__(self, **kwargs):
        # Custom optimized version
        pass
```

### 9. Backward Compatibility

**Challenge:** Can't break existing code.

**Migration strategy:**

Phase 1: Optional support
```python
# Old way still works
class User(Model):
    email = CharField(max_length=255)

# New way available
@dataclass
class User(Model):
    email: str = CharField(max_length=255)
```

Phase 2: Encourage new style
- Documentation shows new style
- Type stubs for old style
- Deprecation warnings optional

Phase 3: Default to new style (future)
- New projects use dataclass style
- Old code still works via compatibility layer

### 10. Model State

**Challenge:** Models need `_state` for tracking if they're saved, deferred fields, etc.

**Solution:**
```python
@dataclass
class Model:
    # These aren't regular fields
    _state: ModelState = field(init=False, repr=False, default_factory=ModelState)
```

Or in `__post_init__`:
```python
def __post_init__(self):
    object.__setattr__(self, '_state', ModelState())
```

## Type Annotation Benefits

### IDE Autocompletion

**Before:**
```python
user = User.query.get(id=1)
user.  # IDE shows: no suggestions or generic object methods
```

**After:**
```python
user = User.query.get(id=1)  # -> User
user.  # IDE shows: email, username, is_active, get_full_name(), etc.
```

### Type Checking

**Before:**
```python
def send_email(email: str):
    pass

user = User.query.get(id=1)
send_email(user.email)  # Type checker can't verify this is safe
```

**After:**
```python
def send_email(email: str):
    pass

user = User.query.get(id=1)
send_email(user.email)  # ✓ Type checker knows email is str
```

### Catching Errors

**Before:**
```python
user.is_active.upper()  # Runtime error - bool has no upper()
```

**After:**
```python
user.is_active.upper()  # Type error caught before running!
                        # Error: "bool" has no attribute "upper"
```

### Generic QuerySets

Can make QuerySet generic:
```python
class QuerySet(Generic[T]):
    def get(self, **kwargs) -> T:
        pass

    def filter(self, **kwargs) -> QuerySet[T]:
        pass

class Model:
    query: ClassVar[QuerySet[Self]]
```

Then:
```python
user = User.query.get(id=1)  # Type: User (not Model)
users = User.query.filter(is_active=True)  # Type: QuerySet[User]
```

## Example Integration Points

### Migration Generator

Would need to inspect dataclass fields:

```python
from dataclasses import fields

def get_model_fields(model_class):
    """Extract Plain fields from a dataclass-based model."""
    plain_fields = []

    for dc_field in fields(model_class):
        metadata = dc_field.metadata
        if 'plain_field' in metadata:
            plain_fields.append({
                'name': dc_field.name,
                'type': metadata['plain_field'],
                'annotation': dc_field.type,
                **metadata
            })

    return plain_fields
```

### Form Generation

```python
def generate_form(model_class):
    """Generate a form from model fields."""
    for dc_field in fields(model_class):
        field_type = dc_field.type
        metadata = dc_field.metadata

        # Use type annotation and metadata to create form field
        if field_type == str:
            form_field = TextInput(
                required=metadata.get('required', True),
                max_length=metadata.get('max_length'),
            )
```

### Serialization

```python
from dataclasses import asdict

user = User(email="test@example.com", username="test")
# Get dict representation
user_dict = asdict(user)
```

## Recommended Approach

### Hybrid System

Best approach: Keep internal Field system, add type-friendly interface:

1. **User writes:**
```python
@dataclass
class User(Model):
    email: str = CharField(max_length=255)
    username: str = CharField(max_length=150)
```

2. **Metaclass processes:**
   - Extract dataclass field definitions
   - Create internal Field instances (CharField, etc.)
   - Set up descriptors for database interaction
   - Register model as usual

3. **Runtime behavior:**
   - Uses existing Field system (proven, optimized)
   - Benefits from dataclass features where helpful
   - Type checkers see annotations

4. **Benefits:**
   - ✓ Type safety for users
   - ✓ Existing functionality preserved
   - ✓ Gradual migration possible
   - ✓ Performance unchanged

### Minimal Example

```python
from dataclasses import dataclass, field, fields
from typing import ClassVar, Any

class ModelBase(type):
    """Metaclass that handles both dataclass and Plain model setup."""

    def __new__(cls, name, bases, attrs, **kwargs):
        # Let the class be created
        new_class = super().__new__(cls, name, bases, attrs)

        # Apply dataclass transformation
        new_class = dataclass(new_class)

        # Extract Plain field info from dataclass fields
        plain_fields = {}
        for dc_field in fields(new_class):
            if 'plain_field' in dc_field.metadata:
                # Create actual Plain Field instance from metadata
                field_class = FIELD_MAP[dc_field.metadata['plain_field']]
                plain_fields[dc_field.name] = field_class(
                    **{k: v for k, v in dc_field.metadata.items()
                       if k != 'plain_field'}
                )

        # Store in meta
        new_class._plain_fields = plain_fields

        return new_class

class Model(metaclass=ModelBase):
    id: int | None = field(default=None, init=False)
    query: ClassVar[Any] = None
```

## Next Steps

To implement this for real:

1. **Prototype**: Create working prototype with basic field types
2. **Performance**: Benchmark vs current implementation
3. **Migration**: Test converting existing models
4. **Relationships**: Implement ForeignKey, ManyToMany
5. **Testing**: Ensure all existing tests pass
6. **Documentation**: Update docs with new patterns
7. **Type stubs**: Generate .pyi files for old-style models

## Conclusion

**Is it feasible?** Yes! Dataclasses provide an excellent foundation for type-safe models.

**Is it worth it?** Depends on priorities:
- If type safety and modern tooling are important → Yes
- If backward compatibility is critical → Hybrid approach
- If performance is paramount → Benchmark first

**Biggest challenges:**
1. Field descriptors and lazy loading
2. ForeignKey relationship handling
3. Migration system compatibility
4. Maintaining performance
5. Backward compatibility

**Biggest benefits:**
1. Full IDE support
2. Type checker integration
3. Better developer experience
4. More Pythonic code
5. Modern Python features

The POC demonstrates this is definitely achievable with thoughtful design!
