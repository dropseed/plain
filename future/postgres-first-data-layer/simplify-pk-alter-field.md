# Simplify primary key handling in \_alter_field

Review the primary key migration machinery in `schema.py` `_alter_field`. After removing the FK auto-indexing (`db_index`), the remaining like-index and primary key blocks may have dead paths or unnecessary complexity. Check whether the Postgres-specific like-index creation/removal for primary key changes is still needed or can be simplified further.
