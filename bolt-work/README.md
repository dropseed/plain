# forge-work

A single command to run everything you need for Django development at once.

![Forge work command example](https://user-images.githubusercontent.com/649496/176533533-cfd44dc5-afe5-42af-8b5d-33a9fa23f8d9.gif)

The following processes will run simultaneously (some will only run if they are detected as available):

- [`manage.py runserver` (and migrations)](#runserver)
- [`forge-db start --logs`](#forge-db)
- [`forge-tailwind compile --watch`](#forge-tailwind)
- [`npm run watch`](#package-json)
- [`stripe listen --forward-to`](#stripe)
- [`ngrok http --subdomain`](#ngrok)


## Installation

### Forge installation

The `forge-work` package is a dependency of [`forge`](https://github.com/forgepackages/forge) and is available as `forge work`.

If you use the [Forge quickstart](https://www.forgepackages.com/docs/quickstart/),
everything you need will already be set up.

The [standard Django installation](#standard-django-installation) can give you an idea of the steps involved.


### Standard Django installation

This package can be used without `forge` by installing it as a regular Django app.

First, install `forge-work` from [PyPI](https://pypi.org/project/forge-work/):

```sh
pip install forge-work
```

Then add it to your `INSTALLED_APPS` in `settings.py`:

```python
INSTALLED_APPS = [
    ...
    "forgework",
]
```

Now instead of using the basic `manage.py runserver` (and a bunch of commands before and during that process), you can simply do:

```sh
python manage.py work
```

## Processes

### Runserver

The key process here is still `manage.py runserver`.
But, before that runs, it will also wait for the database to be available and run `manage.py migrate`.

### forge-db

The [`forge-db` package](https://github.com/forgepackages/forge-db) uses Docker to run a local Postgres database.

If `forge-db` is installed, it will automatically start and show the logs of the running database container.

### forge-tailwind

The [`forge-tailwind` package](https://github.com/forgepackages/forge-tailwind) compiles Tailwind CSS using the Tailwind standalone CLI.

If `forge-tailwind` is installed, it will automatically run the Tailwind `compile --watch` process.

### package.json

If a `package.json` file is found and contains a `watch` script,
it will automatically run.
This is an easy place to run your own custom JavaScript watch process.

### Stripe

If a `STRIPE_WEBHOOK_PATH` env variable is set then this will add a `STRIPE_WEBHOOK_SECRET` to `.env` (using `stripe listen --print-secret`) and it will then run `stripe listen --forward-to <runserver:port/stripe-webhook-path>`.

### Ngrok

If an `NGROK_SUBDOMAIN` env variable is set then this will run `ngrok http <runserver_port> --subdomain <subdomain>`.
