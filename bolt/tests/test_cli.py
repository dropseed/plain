import subprocess


def test_bolt_cli_help():
    output = subprocess.check_output(["bolt", "--help"])
    assert output.startswith(b"Usage: bolt")


def test_bolt_cli_compile():
    output = subprocess.check_output(["bolt", "compile"])
    assert b"files copied" in output
