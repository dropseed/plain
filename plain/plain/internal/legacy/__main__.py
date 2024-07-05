import sys
from pathlib import Path

from plain.internal.legacy import management

if __name__ == "__main__":
    # Automatically put the app dir on the Python path for convenience
    app_dir = Path.cwd() / "app"
    if app_dir.exists() and app_dir not in sys.path:
        sys.path.insert(0, app_dir.as_posix())

    management.execute_from_command_line()
