from users.models import User


def test_staff_login_required(db, client):
    # Login required
    assert client.get("/staff/").status_code == 302

    user = User.objects.create(username="test")
    client.force_login(user)

    # Not staff yet
    assert client.get("/staff/").status_code == 404

    user.is_staff = True
    user.save()

    # Now staff
    assert client.get("/staff/").status_code == 200
