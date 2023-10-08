import subprocess


def test_bolt_cli_help():
    output = subprocess.check_output(["bolt", "--help"])
    assert output.startswith(b"Usage: bolt")
