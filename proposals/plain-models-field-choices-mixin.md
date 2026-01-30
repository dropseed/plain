# plain-models: Extract choices parameter to ChoicesFieldMixin

- The `choices` parameter currently lives on the base `Field` class, but not all field types meaningfully support choices
- Extract `choices` into a `ChoicesFieldMixin` so only specific field types (CharField, IntegerField, etc.) accept it
- Removes `choices` from the base `Field.__init__`, `deconstruct`, `preflight`, and validation logic
- `ChoicesFieldMixin` in `plain/models/fields/mixins.py` owns `BLANK_CHOICE_DASH`, choice validation, and the `invalid_choice` error message

## Files involved

- `plain/models/fields/__init__.py` — remove choices from base Field
- `plain/models/fields/mixins.py` — add ChoicesFieldMixin with choices logic
- `plain/models/fields/timezones.py` — use mixin
- `plain/models/forms.py` — adjust imports
- `plain/models/types.pyi` — update type stubs

## Notes

- Had a WIP implementation in a git stash that applied cleanly as of Jan 2026
- Keep `"choices"` in `Field.non_db_attrs` so migrations don't trigger schema changes when only choices change
