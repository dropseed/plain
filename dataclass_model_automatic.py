"""
Option C: Automatic Detection of Dataclass-Style Models

This demonstrates how the metaclass could automatically detect when
a model uses type annotations and apply dataclass transformation.

Key insight: Check if class has __annotations__ and Field definitions
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, MISSING
from typing import Any, ClassVar, get_type_hints
from datetime import datetime


# ==============================================================================
# Field Factory Functions (same as before)
# ==============================================================================


def CharField(
    *,
    max_length: int | None = None,
    required: bool = True,
    default: Any = MISSING,
) -> Any:
    """Create a string field."""
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
    """Create an integer field."""
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
    """Create a boolean field."""
    metadata = {
        'plain_field_type': 'BooleanField',
        'required': True,
    }

    if default is not MISSING:
        return field(default=default, metadata=metadata)
    else:
        return field(metadata=metadata)


# ==============================================================================
# Legacy Field Classes (for backward compatibility)
# ==============================================================================


class LegacyField:
    """Old-style Field class (no annotations)."""

    def __init__(self, max_length=None, required=True, default=None):
        self.max_length = max_length
        self.required = required
        self.default = default
        self.name = None

    def __set_name__(self, owner, name):
        self.name = name


class LegacyCharField(LegacyField):
    """Old-style CharField."""
    pass


class LegacyIntegerField(LegacyField):
    """Old-style IntegerField."""
    pass


# ==============================================================================
# Automatic Detection Metaclass
# ==============================================================================


class ModelMeta(type):
    """
    Metaclass that automatically detects dataclass-style vs legacy style.

    Detection logic:
    1. Check if class has __annotations__
    2. Check if annotated attributes are assigned dataclass fields
    3. If yes -> apply dataclass transformation
    4. If no -> use legacy Field system
    """

    def __new__(mcs, name: str, bases: tuple[type, ...], attrs: dict[str, Any], **kwargs):
        # Don't process the base Model class
        if name == 'Model' and not bases:
            return super().__new__(mcs, name, bases, attrs)

        # Create the class first
        cls = super().__new__(mcs, name, bases, attrs)

        # DETECTION: Check if this is a dataclass-style model
        is_dataclass_style = mcs._is_dataclass_style_model(cls, attrs)

        if is_dataclass_style:
            print(f"[AUTO-DETECT] {name} uses dataclass style -> applying dataclass")
            cls = mcs._setup_dataclass_model(cls, attrs)
        else:
            print(f"[AUTO-DETECT] {name} uses legacy style -> using legacy system")
            cls = mcs._setup_legacy_model(cls, attrs)

        return cls

    @staticmethod
    def _is_dataclass_style_model(cls: type, attrs: dict[str, Any]) -> bool:
        """
        Detect if this model uses dataclass style.

        Criteria:
        1. Has __annotations__
        2. Annotated fields are assigned to dataclass.field() calls
        3. NOT assigned to legacy Field instances
        """
        # No annotations = definitely legacy
        if not hasattr(cls, '__annotations__') or not cls.__annotations__:
            return False

        # Check each annotated attribute
        for attr_name in cls.__annotations__:
            attr_value = attrs.get(attr_name)

            # Skip special attributes
            if attr_name.startswith('_'):
                continue

            # Skip ClassVar
            if 'ClassVar' in str(cls.__annotations__[attr_name]):
                continue

            # If it's a legacy Field instance, definitely legacy style
            if isinstance(attr_value, LegacyField):
                return False

            # If it's a dataclass field or callable that returns one, it's dataclass style
            # (CharField() etc return dataclass.field())
            # We can check if the attribute has __class__.__name__ == 'Field'
            if hasattr(attr_value, '__class__') and attr_value.__class__.__name__ == 'Field':
                return True

        # Has annotations but no field assignments? Ambiguous, default to legacy
        return False

    @staticmethod
    def _setup_dataclass_model(cls: type, attrs: dict[str, Any]) -> type:
        """Setup a dataclass-style model."""
        # Apply dataclass transformation
        cls = dataclass(cls)

        # Extract field metadata
        plain_fields = {}
        for dc_field in fields(cls):
            if 'plain_field_type' in dc_field.metadata:
                plain_fields[dc_field.name] = {
                    'name': dc_field.name,
                    'metadata': dc_field.metadata,
                }

        cls._plain_fields = plain_fields
        cls._model_style = 'dataclass'
        return cls

    @staticmethod
    def _setup_legacy_model(cls: type, attrs: dict[str, Any]) -> type:
        """Setup a legacy-style model."""
        # Collect legacy Field instances
        legacy_fields = {}
        for attr_name, attr_value in attrs.items():
            if isinstance(attr_value, LegacyField):
                legacy_fields[attr_name] = attr_value

        cls._plain_fields = legacy_fields
        cls._model_style = 'legacy'
        return cls


# ==============================================================================
# Base Model
# ==============================================================================


class Model(metaclass=ModelMeta):
    """
    Base Model that supports BOTH styles automatically.

    No @dataclass decorator needed - it's applied automatically!
    """

    # These work for both styles
    id: int | None = None
    query: ClassVar[Any] = None

    def save(self):
        print(f"Saving {self.__class__.__name__} ({self._model_style} style)")

    def delete(self):
        print(f"Deleting {self.__class__.__name__} ({self._model_style} style)")


# ==============================================================================
# Example Models - Different Styles
# ==============================================================================


# DATACLASS STYLE - Automatically detected!
class DataclassUser(Model):
    """This will be automatically detected as dataclass style."""
    email: str = CharField(max_length=255)
    username: str = CharField(max_length=150)
    age: int = IntegerField(required=False)
    is_active: bool = BooleanField(default=True)


# LEGACY STYLE - Automatically detected!
class LegacyUser(Model):
    """This will be automatically detected as legacy style."""
    email = LegacyCharField(max_length=255)
    username = LegacyCharField(max_length=150)
    age = LegacyIntegerField(required=False)


# MIXED STYLE - What happens?
class MixedUser(Model):
    """Has annotations but uses legacy Fields - detected as legacy."""
    email: str = LegacyCharField(max_length=255)  # Legacy Field with annotation
    username: str = LegacyCharField(max_length=150)


# NO FIELDS STYLE - Just methods
class EmptyModel(Model):
    """Has no fields, just methods."""

    def do_something(self):
        pass


# ==============================================================================
# Demonstrations
# ==============================================================================


def demo_automatic_detection():
    """Demonstrate automatic style detection."""
    print("=" * 70)
    print("AUTOMATIC DETECTION DEMONSTRATION")
    print("=" * 70)

    # Dataclass style
    print("\n--- Dataclass Style ---")
    dc_user = DataclassUser(
        email="test@example.com",
        username="testuser",
        is_active=True,
    )
    print(f"Created: {dc_user}")
    print(f"Style: {dc_user._model_style}")
    print(f"Has __dataclass_fields__: {hasattr(dc_user, '__dataclass_fields__')}")
    print(f"Fields: {list(dc_user._plain_fields.keys())}")
    dc_user.save()

    # Legacy style
    print("\n--- Legacy Style ---")
    legacy_user = LegacyUser()
    legacy_user.email = "legacy@example.com"
    legacy_user.username = "legacyuser"
    print(f"Created: {legacy_user}")
    print(f"Style: {legacy_user._model_style}")
    print(f"Has __dataclass_fields__: {hasattr(legacy_user, '__dataclass_fields__')}")
    print(f"Fields: {list(legacy_user._plain_fields.keys())}")
    legacy_user.save()


def demo_detection_edge_cases():
    """Demonstrate edge cases in detection."""
    print("\n" + "=" * 70)
    print("EDGE CASES")
    print("=" * 70)

    # Mixed style
    print("\n--- Mixed Style (annotation + legacy field) ---")
    mixed = MixedUser()
    print(f"Detected as: {mixed._model_style}")
    print(f"Why: Has annotations but uses legacy Field instances")

    # Empty model
    print("\n--- Empty Model ---")
    empty = EmptyModel()
    print(f"Detected as: {empty._model_style}")
    print(f"Why: No fields at all")


def demo_how_it_works():
    """Explain how the detection works."""
    print("\n" + "=" * 70)
    print("HOW AUTOMATIC DETECTION WORKS")
    print("=" * 70)

    explanation = """
    The metaclass inspects the class definition and checks:

    1. Does the class have __annotations__?
       - No annotations → Legacy style
       - Has annotations → Continue checking...

    2. What are the annotated fields assigned to?
       - dataclass.field() objects → Dataclass style
       - Legacy Field instances → Legacy style
       - Nothing → Legacy style (default)

    3. Apply appropriate transformation:
       - Dataclass style → Apply @dataclass decorator
       - Legacy style → Use current Field system

    Detection happens in __new__ BEFORE the class is fully created,
    so users never see any difference!

    Example flow for DataclassUser:

    class DataclassUser(Model):
        email: str = CharField(...)  # <- CharField returns field()

    Metaclass sees:
    - __annotations__ = {'email': str, ...}
    - email = field(metadata={...})  # dataclass.field object

    Metaclass decides: "This is dataclass style"
    → Applies @dataclass(DataclassUser)
    → Extracts field metadata
    → Returns dataclass-enabled class

    Example flow for LegacyUser:

    class LegacyUser(Model):
        email = LegacyCharField(...)  # <- No annotation

    Metaclass sees:
    - No __annotations__ or empty
    - email = LegacyCharField(...)  # Legacy Field instance

    Metaclass decides: "This is legacy style"
    → Uses current Field descriptor system
    → Returns legacy class
    """
    print(explanation)


def demo_benefits_and_challenges():
    """Discuss benefits and challenges of automatic detection."""
    print("\n" + "=" * 70)
    print("BENEFITS AND CHALLENGES")
    print("=" * 70)

    content = """
    BENEFITS:
    ---------
    ✓ No explicit opt-in needed (no @dataclass decorator)
    ✓ Backward compatible - old models still work
    ✓ Gradual migration - mix styles in same codebase
    ✓ Users just add type annotations naturally
    ✓ Less cognitive overhead - "it just works"

    CHALLENGES:
    -----------
    ✗ Detection logic must be bulletproof
    ✗ Edge cases can be confusing (mixed annotations)
    ✗ Harder to debug when detection goes wrong
    ✗ "Magic" behavior - less explicit
    ✗ What if user adds annotations to legacy fields later?
    ✗ Performance impact of detection logic

    EDGE CASES TO HANDLE:
    ---------------------
    1. Annotations but legacy Fields
       → Currently: Detected as legacy (Field takes precedence)
       → Could be: Error or warning?

    2. Partial annotations (some fields annotated, some not)
       → Currently: Detected as legacy if any legacy Field
       → Could be: Require all or nothing?

    3. Inheritance mixing styles
       → Parent is dataclass, child is legacy?
       → Parent is legacy, child is dataclass?
       → Currently: Each class detected independently

    4. Dynamic field addition
       → setattr(cls, 'new_field', CharField())
       → Can't be detected at class definition time

    ALTERNATIVE DETECTION APPROACHES:
    ----------------------------------

    Approach A: Strict (current implementation)
    - If ANY legacy Field → legacy style
    - Requires consistency within a model

    Approach B: Lenient
    - If ANY dataclass field → dataclass style
    - Allow mixing (risky!)

    Approach C: Explicit marker
    - Check for _use_dataclass = True attribute
    - Falls back to automatic detection if not set

    Approach D: Configuration
    - Settings like PLAIN_MODELS_STYLE = 'dataclass'
    - Override per-model with class attribute

    RECOMMENDATION:
    ---------------
    Automatic detection is RISKY for production.
    Better to use explicit opt-in for safety:

    # Option 1: Class attribute
    class User(Model):
        _use_dataclass = True
        email: str = CharField(...)

    # Option 2: Decorator
    @dataclass_model
    class User(Model):
        email: str = CharField(...)

    # Option 3: Subclass
    class User(DataclassModel):
        email: str = CharField(...)

    But automatic detection is cool for exploration!
    """
    print(content)


# ==============================================================================
# Main
# ==============================================================================


if __name__ == "__main__":
    demo_automatic_detection()
    demo_detection_edge_cases()
    demo_how_it_works()
    demo_benefits_and_challenges()

    print("\n" + "=" * 70)
    print("SUMMARY: Automatic detection is POSSIBLE but RISKY")
    print("Recommend explicit opt-in for production use")
    print("=" * 70)
