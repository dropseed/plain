Local development made easy.

## Local development - opinions

One of my original goals in extending Django was to build a complete local development experience.
What's the single command that gets my project up and running locally?

At one point I tried to use [tmux](https://github.com/tmux/tmux) for this,
but even I am not old enough to care to learn how tmux works.

After that I built `forge-work`, which automatically detected which processes you needed and ran them using [Honcho](https://honcho.readthedocs.io/en/latest/).
This became `bolt work`.

### Removed runsever

### `bolt work`

rename to dev?

# bolt-work

A single command to run everything you need for local Django development.

![Bolt work command example](https://user-images.githubusercontent.com/649496/176533533-cfd44dc5-afe5-42af-8b5d-33a9fa23f8d9.gif)

The following processes will run simultaneously (some will only run if they are detected as available):

- [`manage.py runserver` (and migrations)](#runserver)
- [`bolt-db start --logs`](#bolt-db)
- [`bolt-tailwind compile --watch`](#bolt-tailwind)
- [`npm run watch`](#package-json)
- [`stripe listen --forward-to`](#stripe)
- [`ngrok http --subdomain`](#ngrok)
- [`celery worker`](#celery)

It also comes with [debugging](#debugging) tools to make local debugging easier with VS Code.

## Installation

First, install `bolt-work` from [PyPI](https://pypi.org/project/bolt-work/):

```sh
pip install bolt-work
```

Now instead of using the basic `manage.py runserver` (and a bunch of commands before and during that process), you can simply do:

```sh
bolt work
```

## Development processes

### Runserver

The key process here is still `manage.py runserver`.
But, before that runs, it will also wait for the database to be available and run `manage.py migrate`.

### bolt-db

If [`bolt-db`](https://github.com/boltpackages/bolt-db) is installed, it will automatically start and show the logs of the running database container.

### bolt-tailwind

If [`bolt-tailwind`](https://github.com/boltpackages/bolt-tailwind) is installed, it will automatically run the Tailwind `compile --watch` process.

### package.json

If a `package.json` file is found and contains a `watch` script,
it will automatically run.
This is an easy place to run your own custom JavaScript watch process.

### Stripe

If a `STRIPE_WEBHOOK_PATH` env variable is set then this will add a `STRIPE_WEBHOOK_SECRET` to `.env` (using `stripe listen --print-secret`) and it will then run `stripe listen --forward-to <runserver:port/stripe-webhook-path>`.

## Debugging

[View on YouTube →](https://www.youtube.com/watch?v=pG0KaJSVyBw)

Since `bolt work` runs multiple processes at once, the regular [pdb](https://docs.python.org/3/library/pdb.html) debuggers can be hard to use.
Instead, we include [microsoft/debugpy](https://github.com/microsoft/debugpy) and an `attach` function to make it even easier to use VS Code's debugger.

First, import and run the `debug.attach()` function:

```python
class HomeView(TemplateView):
    template_name = "home.html"

    def get_context(self, **kwargs):
        context = super().get_context(**kwargs)

        # Make sure the debugger is attached (will need to be if runserver reloads)
        from bolt.work import debug; debug.attach()

        # Add a breakpoint (or use the gutter in VSCode to add one)
        breakpoint()

        return context
```

When you load the page, you'll see "Waiting for debugger to attach...".

Add a new VS Code debug configuration (using localhost and port 5768) by saving this to `.vscode/launch.json` or using the GUI:

```json
// .vscode/launch.json
{
    // Use IntelliSense to learn about possible attributes.
    // Hover to view descriptions of existing attributes.
    // For more information, visit: https://go.microsoft.com/fwlink/?linkid=830387
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Bolt: Attach to Django",
            "type": "python",
            "request": "attach",
            "connect": {
                "host": "localhost",
                "port": 5678
            },
            "pathMappings": [
                {
                    "localRoot": "${workspaceFolder}",
                    "remoteRoot": "."
                }
            ],
            "justMyCode": true,
            "django": true
        }
    ]
}
```

Then in the "Run and Debug" tab, you can click the green arrow next to "Bolt: Attach to Django" to start the debugger.

In your terminal is should tell you it was attached, and when you hit a breakpoint you'll see the debugger information in VS Code.
If Django's runserver reloads, you'll be prompted to reattach by clicking the green arrow again.
