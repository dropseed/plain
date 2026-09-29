"""`isolated_cloud_env()` leaves the environment as it found it."""

import os

from cloud_test_helpers import isolated_cloud_env
from plain.test import cases, patch


@cases("PLAIN_CLOUD_TOKEN", "PLAIN_CLOUD_API_URL")
def test_a_variable_set_inside_the_block_is_gone_after_it(name):
    # Not set before the block, as in a run with no token exported.
    with patch(os.environ, name, "before"):
        del os.environ[name]

        with isolated_cloud_env():
            os.environ[name] = "set by the test"

        assert name not in os.environ


@cases("PLAIN_CLOUD_TOKEN", "PLAIN_CLOUD_API_URL")
def test_a_variable_set_before_the_block_is_back_after_it(name):
    with patch(os.environ, name, "before"):
        with isolated_cloud_env():
            assert name not in os.environ
            os.environ[name] = "set by the test"

        assert os.environ[name] == "before"
