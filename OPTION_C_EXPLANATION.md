# How Option C (Automatic Detection) Actually Works

## The Core Question

**"How would automatic detection work without requiring users to add a decorator or change the base class?"**

## The Answer: Metaclass Inspection

The metaclass inspects the class **at definition time** (before the class is fully created) and decides whether to apply dataclass transformation based on what it sees.

---

## Step-by-Step: What Actually Happens

### 1. User Writes Model Code

```python
class User(Model):
    email: str = CharField(max_length=255)
    username: str = CharField(max_length=150)
```

### 2. Python Invokes Metaclass

When Python sees `class User(Model):`, it calls `ModelMeta.__new__()`:

```python
ModelMeta.__new__(
    mcs=ModelMeta,
    name="User",
    bases=(Model,),
    attrs={
        'email': <dataclass.Field object>,  # CharField() returned this
        'username': <dataclass.Field object>,
        '__annotations__': {'email': str, 'username': str},
    },
    **kwargs
)
```

### 3. Metaclass Inspects the Class Definition

```python
class ModelMeta(type):
    def __new__(mcs, name, bases, attrs, **kwargs):
        # Create the class object first
        cls = super().__new__(mcs, name, bases, attrs)

        # DETECTION LOGIC
        has_annotations = bool(getattr(cls, '__annotations__', None))
        uses_dataclass_fields = any(
            hasattr(v, '__class__') and v.__class__.__name__ == 'Field'
            for k, v in attrs.items()
            if k in cls.__annotations__
        )

        if has_annotations and uses_dataclass_fields:
            # ✅ This is dataclass style!
            print(f"Detected dataclass style for {name}")
            cls = dataclass(cls)  # Apply dataclass transformation
            # ... extract metadata, set up descriptors
        else:
            # ❌ This is legacy style
            print(f"Detected legacy style for {name}")
            # ... use current Field system

        return cls
```

### 4. Python Gets Back the Transformed Class

The metaclass returns either:
- A dataclass-transformed class (if detected as new style)
- A legacy Field-based class (if detected as old style)

### 5. User's Code Works Either Way

```python
# Both work the same way!
user = User(email="test@example.com", username="testuser")
user.save()
```

---

## Detection Logic in Detail

### Key Insight: `CharField()` Returns a Dataclass Field

```python
def CharField(max_length=None, required=True, default=MISSING):
    # This returns a dataclass.field() object!
    return field(
        default=default if default is not MISSING else None,
        metadata={'max_length': max_length, 'required': required}
    )
```

So when you write:
```python
email: str = CharField(max_length=255)
```

The class attribute `email` is actually a `dataclass.Field` object.

### Detection Decision Tree

```
Is this a dataclass-style model?
│
├─ Does it have __annotations__?
│  ├─ No → LEGACY STYLE
│  └─ Yes → Continue...
│
├─ Are annotated attributes assigned to dataclass.field() objects?
│  ├─ Yes → DATACLASS STYLE ✅
│  └─ No → LEGACY STYLE
│
└─ Are annotated attributes assigned to legacy Field instances?
   ├─ Yes → LEGACY STYLE
   └─ No → LEGACY STYLE (default)
```

### Code Implementation

```python
def _is_dataclass_style_model(cls, attrs):
    """Detect if model uses dataclass style."""

    # Check 1: Must have annotations
    annotations = getattr(cls, '__annotations__', {})
    if not annotations:
        return False  # No annotations = legacy

    # Check 2: What are the annotated fields assigned to?
    for field_name in annotations:
        if field_name.startswith('_'):
            continue  # Skip private

        field_value = attrs.get(field_name)

        # Is it a legacy Field instance?
        if isinstance(field_value, LegacyField):
            return False  # Legacy Field found = legacy style

        # Is it a dataclass field?
        if hasattr(field_value, '__class__') and field_value.__class__.__name__ == 'Field':
            # Found dataclass field = dataclass style!
            continue
        else:
            # Unknown or missing = default to legacy
            return False

    # All annotated fields are dataclass fields
    return True
```

---

## Visual Example: Detection Flow

### Dataclass Style Example

```python
# User writes:
class User(Model):
    email: str = CharField(max_length=255)
    ^^^^^^     ^^^^^^^^^^^^^^^^^^^^^^^^^^^
       |                    |
       |                    └─ Returns dataclass.Field object
       └─ Type annotation present
```

**Metaclass sees:**
```python
{
    '__annotations__': {'email': str},
    'email': Field(default=None, metadata={'max_length': 255})
}
```

**Decision:** ✅ Dataclass style
- Has annotations: ✅
- Uses dataclass fields: ✅

**Action:** Apply `@dataclass` transformation

---

### Legacy Style Example

```python
# User writes:
class User(Model):
    email = CharField(max_length=255)
    ^^^^^
      |
      └─ No type annotation
```

**Metaclass sees:**
```python
{
    '__annotations__': {},  # Empty!
    'email': CharField(max_length=255)  # Legacy Field instance
}
```

**Decision:** ❌ Legacy style
- Has annotations: ❌

**Action:** Use current Field system

---

### Mixed Style Example (Tricky!)

```python
# User writes:
class User(Model):
    email: str = LegacyCharField(max_length=255)
    ^^^^^^     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
       |                    |
       |                    └─ Legacy Field instance
       └─ Type annotation present
```

**Metaclass sees:**
```python
{
    '__annotations__': {'email': str},
    'email': LegacyCharField(...)  # Legacy Field instance!
}
```

**Decision:** ❌ Legacy style
- Has annotations: ✅
- Uses dataclass fields: ❌ (found legacy Field instead)

**Action:** Use current Field system

**Note:** This prevents accidents where user adds type hints but still uses legacy Fields.

---

## When Detection Happens

```
Timeline:
─────────────────────────────────────────────────────────>

1. User types code:
   class User(Model):
       email: str = CharField(...)

2. Python parses syntax
   └─> Creates annotations dict
   └─> Evaluates CharField() call → returns dataclass.Field

3. Python calls ModelMeta.__new__()
   └─> Metaclass inspects annotations and fields
   └─> Makes detection decision
   └─> Applies transformation

4. ModelMeta.__new__() returns completed class

5. User's code runs:
   user = User(...)  # Works!
```

**Key point:** Detection happens at **class definition time**, not at runtime.

---

## Why This Works

### 1. Metaclass Runs Before Class is Complete

When `ModelMeta.__new__()` is called, the class isn't fully formed yet. This gives us a chance to transform it.

### 2. Dataclass Transformation is Just a Function

```python
from dataclasses import dataclass

# These are equivalent:
@dataclass
class Foo:
    pass

# vs.
class Foo:
    pass
Foo = dataclass(Foo)

# So metaclass can do:
cls = dataclass(cls)
```

### 3. `CharField()` Returns Different Object for Each Style

```python
# For dataclass style:
def CharField(...):
    return field(metadata={...})  # dataclass.field()

# For legacy style:
class CharField(Field):  # A class, not a function
    pass
```

The metaclass distinguishes based on what `CharField` returns.

---

## Edge Cases Handled

### Case 1: No Annotations

```python
class User(Model):
    email = CharField(max_length=255)
```

**Detection:** Legacy (no annotations)
**Result:** Uses current Field system ✅

### Case 2: Annotations but Legacy Fields

```python
class User(Model):
    email: str = LegacyCharField(max_length=255)
```

**Detection:** Legacy (legacy Field found)
**Result:** Uses current Field system ✅

### Case 3: Empty Model

```python
class User(Model):
    pass
```

**Detection:** Legacy (no annotations)
**Result:** Uses current Field system ✅

### Case 4: Partial Annotations

```python
class User(Model):
    email: str = CharField(max_length=255)  # Annotated
    username = CharField(max_length=150)    # Not annotated
```

**Detection:** ???
**Options:**
- Strict: Error (all or nothing)
- Lenient: Legacy (one field not annotated = legacy)
- Hybrid: Dataclass for annotated, legacy for others (risky!)

**Current implementation:** Legacy (safer)

---

## The Magic Behind the Scenes

When detection succeeds and applies dataclass:

```python
# User wrote:
class User(Model):
    email: str = CharField(max_length=255)

# Metaclass transforms to (conceptually):
@dataclass
class User(Model):
    email: str = field(default=None, metadata={'max_length': 255})

    def __init__(self, email: str = None):
        # Dataclass-generated __init__
        self.email = email

# Then metaclass extracts metadata:
User._plain_fields = {
    'email': {
        'type': str,
        'max_length': 255,
        'required': True,
    }
}
```

---

## Why It's "Automatic"

The user doesn't need to:
- Add `@dataclass_model` decorator
- Change base class to `DataclassModel`
- Import anything special
- Opt-in explicitly

They just:
- Add type annotations (standard Python)
- Use field functions that return dataclass fields

The metaclass figures out the rest!

---

## Why It's Risky

1. **Implicit behavior** - User might not realize dataclass is being applied
2. **Edge cases** - Partial annotations, mixed styles, inheritance
3. **Debugging** - When detection fails, error messages are confusing
4. **Magic** - "Explicit is better than implicit" (Python Zen)
5. **Performance** - Detection logic runs for every model class
6. **Maintenance** - Complex detection code to maintain

---

## Making It Safer

### Option 1: Strict Mode

```python
class ModelMeta(type):
    def __new__(mcs, name, bases, attrs, **kwargs):
        # ... detection logic ...

        if is_ambiguous(cls, attrs):
            raise TypeError(
                f"{name}: Cannot mix annotated and non-annotated fields. "
                "Either annotate all fields or none."
            )
```

### Option 2: Warning Mode

```python
import warnings

if is_mixed_style(cls, attrs):
    warnings.warn(
        f"{name}: Model has both annotated and non-annotated fields. "
        "Using legacy style. Add annotations to all fields to use dataclass style.",
        DeprecationWarning
    )
```

### Option 3: Opt-Out

```python
class User(Model):
    _disable_dataclass_detection = True  # Explicit opt-out
    email: str = CharField(max_length=255)  # Won't use dataclass
```

### Option 4: Settings-Based

```python
# settings.py
PLAIN_MODELS_AUTO_DATACLASS = False  # Require explicit opt-in

# models.py
class User(Model):
    _use_dataclass = True  # Explicit opt-in when auto-detection disabled
    email: str = CharField(max_length=255)
```

---

## Summary

**How Option C works:**
1. Metaclass inspects class at definition time
2. Checks for type annotations + dataclass field objects
3. Applies `@dataclass` transformation if detected
4. Otherwise uses legacy Field system
5. Returns transformed class

**Why it's "automatic":**
- No decorator needed
- No base class change needed
- Just add type annotations

**Why it's risky:**
- Implicit magic
- Edge cases
- Hard to debug
- Violates "explicit is better than implicit"

**Recommendation:**
Start with explicit opt-in (Option A or B) for production. Use automatic detection (Option C) for experimentation and exploration.

---

## Try It Yourself

Run the demonstration:

```bash
uv run python dataclass_model_automatic.py
```

See the detection in action! The output shows exactly when each model is detected as dataclass vs legacy style.
