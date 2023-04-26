import os
import sys

from forgecore import Forge


def install_git_hook():
    forge = Forge()

    if not forge.repo_root:
        print("Not in a git repository")
        sys.exit(1)

    hook_path = os.path.join(forge.repo_root, ".git", "hooks", "pre-commit")
    if os.path.exists(hook_path):
        print("pre-commit hook already exists")
    else:
        with open(hook_path, "w") as f:
            f.write(
                """#!/bin/sh
forge pre-commit"""
            )
        os.chmod(hook_path, 0o755)
        print("pre-commit hook installed")
