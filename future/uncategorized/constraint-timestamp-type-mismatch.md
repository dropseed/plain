# Integrity errors with timestamp types in constraint validation

Possible type mismatch in unique constraint validation. In `constraints.py`, values are retrieved via `getattr(instance, field.attname)` as raw Python objects before `get_prep_value()` runs. If a timestamp comes in as a string instead of a `datetime` object, it could compare differently against existing rows or fail at the DB level. Also a timing issue with `auto_now_add` fields — `validate_unique()` might run before `pre_save()` sets the value.
