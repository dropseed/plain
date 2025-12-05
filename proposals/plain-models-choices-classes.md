# plain-models: Evaluate custom Choices classes vs standard enums

- `plain-models/plain/models/enums.py` defines `Choices`, `IntegerChoices`, and `TextChoices`
- These use a custom `ChoicesMeta` metaclass
- Evaluate whether standard Python enums (`StrEnum`/`IntEnum`) could replace these

## Current features

The custom classes add:

- `.label` property on members
- `.choices`, `.names`, `.labels`, `.values` class properties
- `__contains__` that matches by value (not just member)
- `_generate_next_value_` for `auto()` support (unused internally)

## Questions to answer

- How often are `.label`, `.choices`, `.labels` actually used?
- Could labels be handled with docstrings or a simpler pattern?
- Are the typing difficulties worth the conveniences?
- What would migration to standard enums look like?

## Potential approaches

1. Keep as-is if conveniences justify complexity
2. Simplify to thin wrappers around `StrEnum`/`IntEnum`
3. Remove entirely in favor of standard enums with documentation on patterns

## Considerations

- Breaking change for external users
- Typing difficulties with current implementation
- Python's enum ecosystem has evolved since these were created
