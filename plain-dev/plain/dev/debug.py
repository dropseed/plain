import os
import platform
import subprocess
import sys
from pathlib import Path

from . import pdb


def set_breakpoint_hook():
    """
    If a `plain dev` process is running, set a
    breakpoint hook to trigger a remote debugger.
    """

    if not os.environ.get("PLAIN_DEV"):
        # Only want to set the breakpoint hook if
        # we're in a process managed by `plain dev`
        return

    def _breakpoint():
        system = platform.system()

        if system == "Darwin":
            pwd = Path.cwd()
            script = f"""
            tell application "Terminal"
                activate
                do script "cd {pwd} && plain dev debug"
            end tell
            """
            subprocess.run(["osascript", "-e", script])
        else:
            raise OSError("Unsupported operating system")

        pdb.set_trace(
            # Make sure the debugger starts outside of this
            frame=sys._getframe().f_back,
        )

    sys.breakpointhook = _breakpoint
