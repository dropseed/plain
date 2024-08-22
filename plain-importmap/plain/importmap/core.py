import hashlib
import json
import logging
import os

import tomli
from marshmallow import Schema, fields

from .generator import ImportmapGenerator

logger = logging.getLogger(__name__)


DEFAULT_CONFIG_FILENAME = "importmap.toml"
DEFAULT_LOCK_FILENAME = "importmap.lock"


class PackageSchema(Schema):
    name = fields.String(required=True)
    source = fields.String(required=True)
    # preload
    # vendor, or vendor all is one option?


class ConfigSchema(Schema):
    packages = fields.List(fields.Nested(PackageSchema), required=True)


class LockfileSchema(Schema):
    config_hash = fields.String(required=True)
    importmap = fields.Dict(required=True)
    importmap_dev = fields.Dict(required=True)


def hash_for_data(data):
    return hashlib.md5(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()


class Importmap:
    def __init__(
        self,
        config_filename=DEFAULT_CONFIG_FILENAME,
        lock_filename=DEFAULT_LOCK_FILENAME,
    ):
        self.config_filename = config_filename
        self.lock_filename = lock_filename
        self.config = {}
        self.map = {}
        self.map_dev = {}

    def load(self):
        # TODO preflight check to compare lock and config hash

        self.config = self.load_config()

        if not self.config:
            # No config = no map and no lockfile
            self.map = {}
            self.map_dev = {}
            self.delete_lockfile()
            return

        config_hash = hash_for_data(self.config)
        lockfile = self.load_lockfile()

        if not lockfile or lockfile["config_hash"] != config_hash:
            # Generate both maps now, tag will choose which to use at runtime
            self.map = self.generate_map()
            self.map_dev = self.generate_map(development=True)

            lockfile["config_hash"] = config_hash
            lockfile["importmap"] = self.map
            lockfile["importmap_dev"] = self.map_dev
            self.save_lockfile(lockfile)

        elif lockfile:
            # Use map from up-to-date lockfile
            self.map = lockfile["importmap"]
            self.map_dev = lockfile["importmap_dev"]

    def load_config(self):
        # TODO raise custom exceptions

        if not os.path.exists(self.config_filename):
            logger.warning(f"{self.config_filename} not found")
            return {}

        with open(self.config_filename) as f:
            # why doesn't tomli.load(f) work?
            toml_data = tomli.loads(f.read())

        return ConfigSchema().load(toml_data)

    def load_lockfile(self):
        if not os.path.exists(self.lock_filename):
            return {}

        with open(self.lock_filename) as f:
            json_data = json.load(f)

        return LockfileSchema().load(json_data)

    def save_lockfile(self, lockfile):
        with open(self.lock_filename, "w+") as f:
            json.dump(lockfile, f, indent=2, sort_keys=True)

    def delete_lockfile(self):
        if os.path.exists(self.lock_filename):
            os.remove(self.lock_filename)

    def generate_map(self, *args, **kwargs):
        return ImportmapGenerator.from_config(self.config, *args, **kwargs).generate()
