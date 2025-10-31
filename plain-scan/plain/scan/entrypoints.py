def setup() -> None:
    """Register the scan CLI command."""
    # Import the CLI to trigger registration
    from .cli import cli  # noqa: F401
