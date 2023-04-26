import logging

import requests

logger = logging.getLogger(__name__)


class ImportmapGeneratorError(Exception):
    pass


class ImportmapGenerator:
    def __init__(self, targets, development=False, provider="jspm"):
        self.targets = targets
        self.development = development
        self.provider = provider

    @classmethod
    def from_config(cls, config, *args, **kwargs):
        targets = []

        for map in config["packages"]:
            targets.append(map["source"])

        return cls(targets, *args, **kwargs)

    def get_env(self):
        if self.development:
            return ["browser", "module", "development"]
        else:
            return ["browser", "module"]

    def generate(self):
        response = requests.post(
            "https://api.jspm.io/generate",
            json={
                "install": [self.targets],
                "env": self.get_env(),
                "provider": self.provider,
            },
        )
        logger.info(response)

        if "error" in response.json():
            raise ImportmapGeneratorError(response.json()["error"])

        response.raise_for_status()

        return response.json()["map"]
