"""
Invokes django-admin when the django module is run as a script.

Example: python -m django check
"""
from pathlib import Path
import sys
from django.core import management

if __name__ == "__main__":
    # Automatically put the app dir on the Python path for convenience
    app_dir = Path.cwd() / "app"
    if app_dir.exists() and app_dir not in sys.path:
        sys.path.insert(0, app_dir.as_posix())

    management.execute_from_command_line()
