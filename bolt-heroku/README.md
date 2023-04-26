# forge-heroku

Deploy a Django project to Heroku with minimal configuration.

This package is specifically designed to work with the [Forge Heroku Buildpack](https://github.com/forgepackages/heroku-buildpack-forge).

```console
$ forge heroku
Usage: forge heroku [OPTIONS] COMMAND [ARGS]...

  Commands for deploying and managing Heroku apps

Options:
  --help  Show this message and exit.

Commands:
  create          Create a new Heroku app with Postgres...
  pre-deploy      Pre-deploy checks for release process
  serve           Run a production server using gunicorn
  set-buildpacks  Automatically determine and set buildpacks
  shell           Open a remote Django shell
```

## Default Procfile

When you use the Forge buildpack,
Heroku will automatically set up a `Procfile` for you.
Here's what it does:

```yaml
web: forge heroku serve
release: forge heroku pre-deploy
```

If you need to customize your `Procfile`, simply add one to your repo!

## Deploy checks

In the Heroku ["release" phase](https://devcenter.heroku.com/articles/release-phase) we run `manage.py check --deploy --fail-level WARNING` as part of `forge heroku pre-deploy`.

[This runs a number of Django system checks](https://docs.djangoproject.com/en/4.1/howto/deployment/checklist/#run-manage-py-check-deploy) (many related to the settings above) and will prevent deploying your app if any checks fail.
You can also [create your own checks](https://docs.djangoproject.com/en/4.1/topics/checks/) that will run during this process.

## Migrations

The `forge heroku pre-deploy` will also run `manage.py migrate` to ensure that your database is up to date.
