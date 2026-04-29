from app.users.models import User

from plain.admin.views.base import AdminView
from plain.admin.views.registry import registry
from plain.test import Client


def test_admin_login_required(db):
    client = Client()

    # Login required
    assert client.get("/admin/").status_code == 302

    user = User.query.create(username="test")
    client.force_login(user)

    # Not admin yet
    assert client.get("/admin/").status_code == 404

    user.is_admin = True
    user.save()

    # Now admin (currently redirects to the first view)
    resp = client.get("/admin/")
    assert resp.status_code == 302
    assert resp.url == "/admin/p/session/"


def test_has_permission_on_view(db):
    """A view with has_permission returning False denies access via check_auth."""

    class RestrictedView(AdminView):
        title = "Restricted"
        path = "restricted"
        nav_section = "Test"

        @classmethod
        def has_permission(cls, user) -> bool:
            return False  # Always denied

    user = User.query.create(username="admin", is_admin=True)

    # has_permission returns False
    assert RestrictedView.has_permission(user) is False

    # Default AdminView allows access
    assert AdminView.has_permission(user) is True


def test_has_permission_setting(db):
    """ADMIN_HAS_PERMISSION setting controls access to all views."""
    from plain.runtime import settings

    class TargetView(AdminView):
        title = "Target"
        path = "target"
        nav_section = "Test"

    def allow(view_cls, user):
        return view_cls is not TargetView

    user = User.query.create(username="admin", is_admin=True)

    original = settings.ADMIN_HAS_PERMISSION
    try:
        settings.ADMIN_HAS_PERMISSION = allow

        # Setting denies TargetView
        assert TargetView.has_permission(user) is False

        # But allows other views
        assert AdminView.has_permission(user) is True
    finally:
        settings.ADMIN_HAS_PERMISSION = original


def test_components_view_renders(db):
    """The components catalog page renders for an admin user."""
    user = User.query.create(username="admin", is_admin=True)
    client = Client()
    client.force_login(user)

    resp = client.get("/admin/components/")
    assert resp.status_code == 200
    body = resp.content.decode()
    # Sanity-check a few markers from each major section
    assert "Customizing the admin" in body
    assert "btn-primary" in body
    assert "badge-success" in body
    assert "data-theme-toggle" in body


def test_nav_sections_exclude_denied_views(db):
    """Nav sections should not include views the user is denied from."""

    class AllowedView(AdminView):
        title = "Allowed"
        path = "test-allowed"
        nav_section = "Test"

    class DeniedView(AdminView):
        title = "Denied"
        path = "test-denied"
        nav_section = "Test"

        @classmethod
        def has_permission(cls, user) -> bool:
            return False

    registry.register_view(AllowedView)
    registry.register_view(DeniedView)
    try:
        user = User.query.create(username="admin", is_admin=True)

        # Denied view is excluded from nav
        sections = registry.get_nav_sections(plain_packages=False, user=user)
        test_views = sections.get("Test", [])
        assert AllowedView in test_views
        assert DeniedView not in test_views
    finally:
        registry.registered_views.discard(AllowedView)
        registry.registered_views.discard(DeniedView)
        registry.__dict__.pop("slug_to_view", None)
        registry.__dict__.pop("path_to_view", None)
