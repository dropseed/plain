import sys

from plain.packages import packages


def emit_pre_migrate_signal(verbosity, interactive, db, **kwargs):
    # Emit the pre_migrate signal for every application.
    for package_config in packages.get_package_configs():
        if package_config.models_module is None:
            continue
        if verbosity >= 2:
            stdout = kwargs.get("stdout", sys.stdout)
            stdout.write(
                "Running pre-migrate handlers for application %s" % package_config.label
            )
        try:
            from plain import models
        except ImportError:
            continue
        models.signals.pre_migrate.send(
            sender=package_config,
            package_config=package_config,
            verbosity=verbosity,
            interactive=interactive,
            using=db,
            **kwargs,
        )


def emit_post_migrate_signal(verbosity, interactive, db, **kwargs):
    # Emit the post_migrate signal for every application.
    for package_config in packages.get_package_configs():
        if package_config.models_module is None:
            continue
        if verbosity >= 2:
            stdout = kwargs.get("stdout", sys.stdout)
            stdout.write(
                "Running post-migrate handlers for application %s"
                % package_config.label
            )
        try:
            from plain import models
        except ImportError:
            continue
        models.signals.post_migrate.send(
            sender=package_config,
            package_config=package_config,
            verbosity=verbosity,
            interactive=interactive,
            using=db,
            **kwargs,
        )
