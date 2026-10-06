from plain.cli.runtime import set_running_command, the_running_command_was_found

from .runner.main import main

# `python -m plain.testing` is `plain test` started without the `plain` CLI,
# which is what would have said which command this is, and that there is
# such a command. Code that runs during setup asks: plain.dev starts the
# database and the project's services for a test run.
set_running_command("test")
the_running_command_was_found()

main()
