# bolt-format

A unified, opinionated code formatting command for Django projects.

Uses [black](https://github.com/psf/black) and [ruff](https://github.com/charliermarsh/ruff/) to format Python code.


## Installation

First, install `bolt-format` from [PyPI](https://pypi.org/project/bolt-format/):

```sh
pip install bolt-format
```

Now you will have access to the `format` command:

```sh
bolt format
```

Note that if you're using black + ruff for the first time,
a common issue is to get a bunch of `E501 Line too long` errors on code comments.
This is because black doesn't fix line lengths on comments!
If there are more than you want to fix, just add this to your `pyproject.toml`:

```toml
[tool.ruff]
# Never enforce `E501` (line length violations).
ignore = ["E501"]
```
