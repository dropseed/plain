# Dataclass Model Implementation Options

## Overview

Three approaches for adding dataclass support to Plain models, with different trade-offs between explicitness, safety, and user experience.

---

## Option A: Explicit Decorator

**Users write:**
```python
@dataclass_model  # Explicit opt-in
class User(Model):
    email: str = CharField(max_length=255)
    username: str = CharField(max_length=150)
    is_active: bool = BooleanField(default=True)
```

**How it works:**
```python
def dataclass_model(cls):
    """Decorator that applies dataclass transformation."""
    # Apply @dataclass
    cls = dataclass(cls)
    # Extract field metadata
    # Set up descriptors
    # Register model
    return cls
```

### ✅ Pros
- **Crystal clear intent** - You see `@dataclass_model`, you know what you get
- **Easy to debug** - Explicit decorator shows where transformation happens
- **Safe** - Can't accidentally trigger dataclass behavior
- **Simple to implement** - Just a decorator function
- **Easy to document** - "Add this decorator to use dataclass features"
- **Gradual migration** - Add decorator one model at a time

### ❌ Cons
- **Extra boilerplate** - Need to remember the decorator
- **Not ergonomic** - Feels redundant (type hints already signal intent)
- **Two-step opt-in** - Add annotations AND decorator
- **Import required** - `from plain.models import dataclass_model`

### Implementation complexity: ⭐ Low

### Example in practice:
```python
# Old style - still works
class OldUser(Model):
    email = CharField(max_length=255)

# New style - explicit opt-in
@dataclass_model
class NewUser(Model):
    email: str = CharField(max_length=255)
```

---

## Option B: Explicit Subclass

**Users write:**
```python
class User(DataclassModel):  # Different base class
    email: str = CharField(max_length=255)
    username: str = CharField(max_length=150)
    is_active: bool = BooleanField(default=True)
```

**How it works:**
```python
@dataclass
class DataclassModel(Model):
    """Model subclass with dataclass transformation applied."""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Ensure subclass is also a dataclass
        # Extract field metadata
        # Set up descriptors
```

### ✅ Pros
- **Very explicit** - Base class clearly signals behavior
- **Type-checker friendly** - Different base = different type
- **Clean separation** - Two distinct Model types
- **No decorator needed** - Just inherit
- **Easy to grep** - Find all dataclass models: `grep "DataclassModel"`
- **Can have different methods** - DataclassModel can add dataclass-specific APIs

### ❌ Cons
- **Inheritance hierarchy** - Another class to understand
- **Not ergonomic** - Changing base class feels heavyweight
- **Two Model types** - `Model` vs `DataclassModel` confusion
- **Import required** - `from plain.models import DataclassModel`
- **Type annotations** - Might need `Union[Model, DataclassModel]` in some places

### Implementation complexity: ⭐⭐ Medium

### Example in practice:
```python
# Old style
class OldUser(Model):
    email = CharField(max_length=255)

# New style - different base
class NewUser(DataclassModel):
    email: str = CharField(max_length=255)

# Works with type hints
def get_user() -> NewUser:  # Return type is specific
    return NewUser.query.get(id=1)
```

---

## Option C: Automatic Detection

**Users write:**
```python
# Just add type annotations - automatic!
class User(Model):
    email: str = CharField(max_length=255)
    username: str = CharField(max_length=150)
    is_active: bool = BooleanField(default=True)
```

**How it works:**
```python
class ModelMeta(type):
    def __new__(mcs, name, bases, attrs, **kwargs):
        cls = super().__new__(mcs, name, bases, attrs)

        # AUTOMATIC DETECTION
        if mcs._has_type_annotations(cls) and mcs._uses_dataclass_fields(attrs):
            # This is dataclass style!
            cls = dataclass(cls)
            # Extract field metadata...
        else:
            # This is legacy style
            # Use current Field system...

        return cls
```

**Detection logic:**
1. Check if class has `__annotations__`
2. Check if annotated attributes are assigned to `dataclass.field()` objects
3. If both true → apply dataclass transformation
4. Otherwise → use legacy system

### ✅ Pros
- **Zero boilerplate** - Just add type hints
- **Natural Python** - Type hints are standard practice
- **Great UX** - "It just works"
- **Gradual migration** - Add type hints to any model, automatically upgraded
- **Backward compatible** - Old models work unchanged
- **No imports needed** - Same Model base class

### ❌ Cons
- **"Magic" behavior** - Not obvious when dataclass is applied
- **Hard to debug** - When detection fails, why?
- **Edge cases** - What about partially annotated models?
- **Implicit** - Behavior changes based on annotations
- **Performance** - Detection logic runs for every model
- **Risky** - Wrong detection = subtle bugs
- **Confusing mixed cases** - Annotations + legacy Fields = ???

### Implementation complexity: ⭐⭐⭐⭐ High

### Example in practice:
```python
# Old style - no annotations
class OldUser(Model):
    email = CharField(max_length=255)
    # Detected as: LEGACY

# New style - with annotations
class NewUser(Model):
    email: str = CharField(max_length=255)
    # Detected as: DATACLASS

# Mixed style - annotations + old Fields
class MixedUser(Model):
    email: str = LegacyCharField(max_length=255)
    # Detected as: LEGACY (legacy Field takes precedence)
    # OR: Error? Warning? Depends on policy...

# Partial annotations
class PartialUser(Model):
    email: str = CharField(max_length=255)  # Annotated
    username = CharField(max_length=150)     # Not annotated
    # Detected as: ??? Ambiguous!
```

---

## Comparison Table

| Aspect | Option A (Decorator) | Option B (Subclass) | Option C (Automatic) |
|--------|---------------------|---------------------|---------------------|
| **Explicitness** | ⭐⭐⭐⭐⭐ Very explicit | ⭐⭐⭐⭐⭐ Very explicit | ⭐ Implicit |
| **User ergonomics** | ⭐⭐⭐ Some boilerplate | ⭐⭐⭐ Different base class | ⭐⭐⭐⭐⭐ Zero boilerplate |
| **Safety** | ⭐⭐⭐⭐⭐ Very safe | ⭐⭐⭐⭐⭐ Very safe | ⭐⭐ Edge cases risky |
| **Debuggability** | ⭐⭐⭐⭐⭐ Easy to debug | ⭐⭐⭐⭐ Easy to debug | ⭐⭐ Hard to debug |
| **Implementation** | ⭐⭐⭐⭐⭐ Simple | ⭐⭐⭐⭐ Moderate | ⭐⭐ Complex |
| **Migration path** | ⭐⭐⭐⭐ Clear | ⭐⭐⭐⭐ Clear | ⭐⭐⭐ Automatic |
| **Type checker** | ⭐⭐⭐⭐ Works well | ⭐⭐⭐⭐⭐ Best support | ⭐⭐⭐⭐ Works well |
| **Backward compat** | ⭐⭐⭐⭐⭐ Perfect | ⭐⭐⭐⭐⭐ Perfect | ⭐⭐⭐⭐⭐ Perfect |

---

## Hybrid Approach: Best of All Worlds?

Combine options for maximum flexibility:

```python
# Option 1: Automatic (if safe)
class User(Model):
    email: str = CharField(max_length=255)
    # Auto-detected as dataclass IF all fields annotated

# Option 2: Explicit override with class attribute
class User(Model):
    _dataclass_model = True  # Force dataclass mode
    email: str = CharField(max_length=255)

# Option 3: Explicit override with decorator
@dataclass_model
class User(Model):
    email: str = CharField(max_length=255)
```

**Precedence:**
1. Decorator `@dataclass_model` → Force dataclass
2. Class attribute `_dataclass_model = True` → Force dataclass
3. Automatic detection → Best guess
4. Default → Legacy

---

## Recommendation

### For Production: **Option A (Decorator)** ✅

**Why:**
- Explicit and safe
- Easy to understand and debug
- Simple to implement
- Clear migration path
- No ambiguity

**Usage:**
```python
from plain.models import Model, dataclass_model, CharField

@dataclass_model
class User(Model):
    email: str = CharField(max_length=255)
    username: str = CharField(max_length=150)
```

### For Exploration: **Option C (Automatic)** 🔬

**Why:**
- Best user experience
- Interesting technical challenge
- Shows what's possible
- Good for experimentation

**But not recommended for production without:**
- Extensive testing
- Clear error messages
- Warnings for edge cases
- Way to disable if needed

---

## Implementation Recommendation

**Phase 1: Start with Option A**
- Implement `@dataclass_model` decorator
- Test thoroughly with all field types
- Validate migrations work
- Performance benchmarks

**Phase 2: Consider Option B**
- If decorator feels clunky in practice
- Create `DataclassModel` base class
- Migrate decorator users

**Phase 3: Maybe Option C**
- After Option A/B is stable
- Add automatic detection as experimental feature
- Can be enabled via setting: `PLAIN_MODELS_AUTO_DATACLASS = True`
- Gather feedback before making default

---

## Key Insight: The Real Challenge

The implementation approach (A, B, or C) is actually the **easy part**.

The **hard parts** are the same regardless:
1. ✅ Field descriptor integration
2. ✅ ForeignKey relationship handling
3. ✅ Migration compatibility
4. ✅ QuerySet type generics
5. ✅ Performance optimization
6. ✅ All field types support
7. ✅ Comprehensive testing

**Therefore:** Start with simplest approach (Option A) to focus on the hard problems.
