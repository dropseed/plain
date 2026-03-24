# Simplify AuthView by Moving admin_required to AdminView

## Goal

- Remove `admin_required` from `AuthView` (make it purely about login/sessions)
- Move all admin-related logic to `AdminView` in plain-admin
- Keep toolbar standalone but with optional impersonation awareness when plain-admin is installed
- Fix undeclared dependency (plain-admin → plain-toolbar)

## Files to Modify

### 1. plain-admin/pyproject.toml

Add `plain.toolbar` as explicit dependency (fixes undeclared import in `admin/toolbar.py`)

### 2. plain-auth/plain/auth/views.py

**Remove:**

- `admin_required = False` class attribute
- Optional import of `get_request_impersonator` from `plain.admin.impersonate`
- Admin-related logic in `check_auth()`

**Keep:**

- `login_required` flag and logic
- Everything else unchanged

### 3. plain-admin/plain/admin/views/base.py

**Add to `AdminView`:**

- Override `check_auth()` with admin logic including impersonation awareness
- Set `login_required = True`

```python
def check_auth(self) -> None:
    super().check_auth()  # Handle login requirement

    # Check if impersonation is active
    if impersonator := get_request_impersonator(self.request):
        if not impersonator.is_admin:
            raise ForbiddenError403("You do not have permission to access this page.")
        return

    if not self.user.is_admin:
        raise NotFoundError404()
```

### 4. plain-observer/plain/observer/views.py

Replace `admin_required = True` with explicit admin check in `check_auth()`:

```python
def check_auth(self) -> None:
    if settings.DEBUG:
        return
    super().check_auth()
    if not self.user.is_admin:
        raise NotFoundError404()
```

### 5. plain-toolbar/plain/toolbar/toolbar.py

**No changes needed** - the current optional import pattern is correct:

- Works standalone (DEBUG or is_admin)
- Gains impersonation awareness when plain-admin is installed

### 6. plain-auth/tests/

- Remove admin-related test view and test from plain-auth
- Add equivalent tests to plain-admin

### 7. plain-auth/plain/auth/README.md

- Remove `admin_required` from documentation
- Add note pointing to `AdminView` for admin-only views

## Order of Changes

1. Add plain.toolbar dependency to plain-admin/pyproject.toml
2. Add admin_required logic to AdminView (plain-admin)
3. Update plain-observer views to use explicit admin checks
4. Remove admin_required from AuthView (plain-auth)
5. Update tests
6. Update documentation

## Breaking Changes

| Change                                   | Migration                                                           |
| ---------------------------------------- | ------------------------------------------------------------------- |
| `admin_required` removed from `AuthView` | Use `AdminView` from plain-admin or implement custom `check_auth()` |
