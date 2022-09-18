Deploy a Django project to Heroku with minimal configuration.

This package is specifically designed to work with the [Forge Quickstart](https://www.forgepackages.com/docs/forge/quickstart/) and the [Forge Heroku Buildpack](https://github.com/forgepackages/heroku-buildpack-forge).

Installation outside of the Forge Quickstart might work, but is not documented or necessarily recommended.

## Default Procfile

When you use the Forge buildpack,
Heroku will automatically set up a `Procfile` for you.
Here's what it does:

```yaml
web: forge serve
release: forge pre-deploy
```

If you need to customize your `Procfile`, simply add one to your repo!

## Deploy checks

In the Heroku ["release" phase](https://devcenter.heroku.com/articles/release-phase) we run `manage.py check --deploy --fail-level WARNING` as part of `forge pre-deploy`.

[This runs a number of Django system checks](https://docs.djangoproject.com/en/4.1/howto/deployment/checklist/#run-manage-py-check-deploy) (many related to the settings above) and will prevent deploying your app if any checks fail.
You can also [create your own checks](https://docs.djangoproject.com/en/4.1/topics/checks/) that will run during this process.

## Migrations

The `forge pre-deploy` will also run `manage.py migrate` to ensure that your database is up to date.
