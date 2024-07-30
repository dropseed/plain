from plain.flags import Flag


def test_flag(db):
    class TestFlag(Flag):
        def get_key(self):
            return "test"

        def get_value(self):
            return True

    flag = TestFlag()
    assert flag.value is True
