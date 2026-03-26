# Admin: guard against empty target_ids in perform_action

When a user submits an action with no items selected, `target_ids` is `[]` and gets passed straight to `perform_action()` with no validation. The action silently runs against an empty queryset. Needs a guard + user-facing message.

Location: `plain-admin/plain/admin/views/objects.py`
