import os

from bolt.runtime import settings


class StaffToolbar:
    def __init__(self, *, request):
        self.links = settings.STAFFTOOLBAR_LINKS
        self.release = Release()
        self.release.load()


class Release:
    def __init__(self):
        self.summary = "dev"
        self.metadata = {}

    def __str__(self):
        return self.summary

    def load(self):
        self.metadata = {}

        if "HEROKU_RELEASE_VERSION" in os.environ:
            self.metadata["Heroku release"] = os.environ["HEROKU_RELEASE_VERSION"]
            self.summary = os.environ["HEROKU_RELEASE_VERSION"]

        if "DYNO_RAM" in os.environ:
            self.metadata["Dyno RAM"] = os.environ["DYNO_RAM"]

        if "DYNO" in os.environ:
            self.metadata["Dyno"] = os.environ["DYNO"]

        if "HEROKU_SLUG_DESCRIPTION" in os.environ:
            self.metadata["Heroku slug"] = os.environ["HEROKU_SLUG_DESCRIPTION"]

        if "HEROKU_SLUG_COMMIT" in os.environ:
            self.metadata["Commit SHA"] = os.environ["HEROKU_SLUG_COMMIT"]
            self.summary = f"{self.summary} ({os.environ['HEROKU_SLUG_COMMIT'][:7]})"

        if "HEROKU_RELEASE_CREATED_AT" in os.environ:
            self.metadata["Created at"] = os.environ["HEROKU_RELEASE_CREATED_AT"]

        if "HEROKU_APP_NAME" in os.environ:
            self.metadata["App name"] = os.environ["HEROKU_APP_NAME"]

        # Review apps - https://devcenter.heroku.com/articles/github-integration-review-apps#injected-environment-variables
        if "HEROKU_PR_NUMBER" in os.environ:
            self.metadata["PR"] = "#" + os.environ["HEROKU_PR_NUMBER"]
            self.summary = "PR #" + os.environ["HEROKU_PR_NUMBER"] + " " + self.summary

        if "HEROKU_BRANCH" in os.environ:
            self.metadata["Branch"] = os.environ["HEROKU_BRANCH"]
            self.summary = os.environ["HEROKU_BRANCH"] + " " + self.summary

        self.metadata = sorted(self.metadata.items())
