import subprocess


def test_plain_cli_help():
    output = subprocess.check_output(["plain", "--help"])
    assert output.startswith(b"Usage: plain")


def test_plain_cli_compile():
    output = subprocess.check_output(["plain", "compile"])
    assert b"files copied" in output
