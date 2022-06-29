from forgecore.packages import forgepackage_installed


def test_package_installed():
    assert forgepackage_installed("core")


def test_package_not_installed():
    assert not forgepackage_installed("foo")
