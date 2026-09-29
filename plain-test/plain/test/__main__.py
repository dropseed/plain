from plain.cli.runtime import set_running_command

from .runner.main import main

# `python -m plain.test` is `plain test` started without the `plain` CLI,
# which is what would have said which command this is. Code that runs during
# setup asks: plain.dev starts the database for a test run.
set_running_command("test")

main()
