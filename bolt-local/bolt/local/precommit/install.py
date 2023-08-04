import os


def install_git_hook(repo_root):
    hook_path = os.path.join(repo_root, ".git", "hooks", "pre-commit")
    if os.path.exists(hook_path):
        print("pre-commit hook already exists")
    else:
        with open(hook_path, "w") as f:
            f.write(
                """#!/bin/sh
bolt pre-commit"""
            )
        os.chmod(hook_path, 0o755)
        print("pre-commit hook installed")
