from __future__ import annotations

import os
import re
from importlib import import_module
from typing import Any

from plain.models import migrations
from plain.models.migrations.loader import MigrationLoader
from plain.models.migrations.migration import SettingsTuple
from plain.models.migrations.serializer import serializer_factory
from plain.packages import packages_registry
from plain.runtime import __version__
from plain.utils.inspect import get_func_args
from plain.utils.module_loading import module_dir
from plain.utils.timezone import now


class OperationWriter:
    def __init__(self, operation: Any, indentation: int = 2) -> None:
        self.operation = operation
        self.buff: list[str] = []
        self.indentation = indentation

    def serialize(self) -> tuple[str, set[str]]:
        def _write(_arg_name: str, _arg_value: Any) -> None:
            if _arg_name in self.operation.serialization_expand_args and isinstance(
                _arg_value, list | tuple | dict
            ):
                if isinstance(_arg_value, dict):
                    self.feed(f"{_arg_name}={{")
                    self.indent()
                    for key, value in _arg_value.items():
                        key_string, key_imports = MigrationWriter.serialize(key)
                        arg_string, arg_imports = MigrationWriter.serialize(value)
                        args = arg_string.splitlines()
                        if len(args) > 1:
                            self.feed(f"{key_string}: {args[0]}")
                            for arg in args[1:-1]:
                                self.feed(arg)
                            self.feed(f"{args[-1]},")
                        else:
                            self.feed(f"{key_string}: {arg_string},")
                        imports.update(key_imports)
                        imports.update(arg_imports)
                    self.unindent()
                    self.feed("},")
                else:
                    self.feed(f"{_arg_name}=[")
                    self.indent()
                    for item in _arg_value:
                        arg_string, arg_imports = MigrationWriter.serialize(item)
                        args = arg_string.splitlines()
                        if len(args) > 1:
                            for arg in args[:-1]:
                                self.feed(arg)
                            self.feed(f"{args[-1]},")
                        else:
                            self.feed(f"{arg_string},")
                        imports.update(arg_imports)
                    self.unindent()
                    self.feed("],")
            else:
                arg_string, arg_imports = MigrationWriter.serialize(_arg_value)
                args = arg_string.splitlines()
                if len(args) > 1:
                    self.feed(f"{_arg_name}={args[0]}")
                    for arg in args[1:-1]:
                        self.feed(arg)
                    self.feed(f"{args[-1]},")
                else:
                    self.feed(f"{_arg_name}={arg_string},")
                imports.update(arg_imports)

        imports = set()
        name, args, kwargs = self.operation.deconstruct()
        operation_args = get_func_args(self.operation.__init__)

        # See if this operation is in plain.models.migrations. If it is,
        # We can just use the fact we already have that imported,
        # otherwise, we need to add an import for the operation class.
        if getattr(migrations, name, None) == self.operation.__class__:
            self.feed(f"migrations.{name}(")
        else:
            imports.add(f"import {self.operation.__class__.__module__}")
            self.feed(f"{self.operation.__class__.__module__}.{name}(")

        self.indent()

        for i, arg in enumerate(args):
            arg_value = arg
            arg_name = operation_args[i]
            _write(arg_name, arg_value)

        i = len(args)
        # Only iterate over remaining arguments
        for arg_name in operation_args[i:]:
            if arg_name in kwargs:  # Don't sort to maintain signature order
                arg_value = kwargs[arg_name]
                _write(arg_name, arg_value)

        self.unindent()
        self.feed("),")
        return self.render(), imports

    def indent(self) -> None:
        self.indentation += 1

    def unindent(self) -> None:
        self.indentation -= 1

    def feed(self, line: str) -> None:
        self.buff.append(" " * (self.indentation * 4) + line)

    def render(self) -> str:
        return "\n".join(self.buff)


class MigrationWriter:
    """
    Take a Migration instance and is able to produce the contents
    of the migration file from it.
    """

    def __init__(self, migration: Any, include_header: bool = True) -> None:
        self.migration = migration
        self.include_header = include_header
        self.needs_manual_porting = False

    def as_string(self) -> str:
        """Return a string of the file contents."""
        items = {
            "replaces_str": "",
            "initial_str": "",
        }

        imports = set()

        # Deconstruct operations
        operations = []
        for operation in self.migration.operations:
            operation_string, operation_imports = OperationWriter(operation).serialize()
            imports.update(operation_imports)
            operations.append(operation_string)
        items["operations"] = "\n".join(operations) + "\n" if operations else ""

        # Format dependencies and write out settings dependencies right
        dependencies = []
        for dependency in self.migration.dependencies:
            if isinstance(dependency, SettingsTuple):
                dependencies.append(
                    f"        migrations.settings_dependency(settings.{dependency[1]}),"
                )
                imports.add("from plain.runtime import settings")
            else:
                dependencies.append(f"        {self.serialize(dependency)[0]},")
        items["dependencies"] = "\n".join(dependencies) + "\n" if dependencies else ""

        # Format imports nicely, swapping imports of functions from migration files
        # for comments
        migration_imports = set()
        for line in list(imports):
            if re.match(r"^import (.*)\.\d+[^\s]*$", line):
                migration_imports.add(line.split("import")[1].strip())
                imports.remove(line)
                self.needs_manual_porting = True

        imports.add("from plain.models import migrations")

        # Sort imports by the package / module to be imported (the part after
        # "from" in "from ... import ..." or after "import" in "import ...").
        # First group the "import" statements, then "from ... import ...".
        sorted_imports = sorted(
            imports, key=lambda i: (i.split()[0] == "from", i.split()[1])
        )
        items["imports"] = "\n".join(sorted_imports) + "\n" if imports else ""
        if migration_imports:
            items["imports"] += (
                "\n\n# Functions from the following migrations need manual "
                "copying.\n# Move them and any dependencies into this file, "
                "then update the\n# RunPython operations to refer to the local "
                "versions:\n# {}"
            ).format("\n# ".join(sorted(migration_imports)))
        # If there's a replaces, make a string for it
        if self.migration.replaces:
            items["replaces_str"] = (
                f"\n    replaces = {self.serialize(self.migration.replaces)[0]}\n"
            )
        # Hinting that goes into comment
        if self.include_header:
            items["migration_header"] = MIGRATION_HEADER_TEMPLATE % {
                "version": __version__,
                "timestamp": now().strftime("%Y-%m-%d %H:%M"),
            }
        else:
            items["migration_header"] = ""

        if self.migration.initial:
            items["initial_str"] = "\n    initial = True\n"

        return MIGRATION_TEMPLATE % items

    @property
    def basedir(self) -> str:
        migrations_package_name, _ = MigrationLoader.migrations_module(
            self.migration.package_label
        )

        if migrations_package_name is None:
            raise ValueError(
                f"Plain can't create migrations for app '{self.migration.package_label}' because "
                "migrations have been disabled via the MIGRATION_MODULES "
                "setting."
            )

        # See if we can import the migrations module directly
        try:
            migrations_module = import_module(migrations_package_name)
        except ImportError:
            pass
        else:
            try:
                return module_dir(migrations_module)
            except ValueError:
                pass

        # Alright, see if it's a direct submodule of the app
        package_config = packages_registry.get_package_config(
            self.migration.package_label
        )
        (
            maybe_package_name,
            _,
            migrations_package_basename,
        ) = migrations_package_name.rpartition(".")
        if package_config.name == maybe_package_name:
            return os.path.join(package_config.path, migrations_package_basename)

        # In case of using MIGRATION_MODULES setting and the custom package
        # doesn't exist, create one, starting from an existing package
        existing_dirs, missing_dirs = migrations_package_name.split("."), []
        while existing_dirs:
            missing_dirs.insert(0, existing_dirs.pop(-1))
            try:
                base_module = import_module(".".join(existing_dirs))
            except (ImportError, ValueError):
                continue
            else:
                try:
                    base_dir = module_dir(base_module)
                except ValueError:
                    continue
                else:
                    break
        else:
            raise ValueError(
                "Could not locate an appropriate location to create "
                f"migrations package {migrations_package_name}. Make sure the toplevel "
                "package exists and can be imported."
            )

        final_dir = os.path.join(base_dir, *missing_dirs)
        os.makedirs(final_dir, exist_ok=True)
        for missing_dir in missing_dirs:
            base_dir = os.path.join(base_dir, missing_dir)
            with open(os.path.join(base_dir, "__init__.py"), "w"):
                pass

        return final_dir

    @property
    def filename(self) -> str:
        return f"{self.migration.name}.py"

    @property
    def path(self) -> str:
        return os.path.join(self.basedir, self.filename)

    @classmethod
    def serialize(cls, value: Any) -> tuple[str, set[str]]:
        return serializer_factory(value).serialize()


MIGRATION_HEADER_TEMPLATE = """\
# Generated by Plain %(version)s on %(timestamp)s

"""


MIGRATION_TEMPLATE = """\
%(migration_header)s%(imports)s

class Migration(migrations.Migration):
%(replaces_str)s%(initial_str)s
    dependencies = [
%(dependencies)s\
    ]

    operations = [
%(operations)s\
    ]
"""
