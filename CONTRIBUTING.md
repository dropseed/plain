# Contributing to Plain

First of all, there's more than one way to contribute to Plain. [Sharing the project on social media](https://x.com/plainframework), or [starring it on GitHub](https://github.com/dropseed/plain), are surprisingly helpful things that anyone can do!

For more technical contributions, please [open an issue for well-identified bugs](https://github.com/dropseed/plain/issues), and a [discussion for anything else](https://github.com/dropseed/plain/discussions). Don't waste your time working on a lengthy PR with the _hope_ that it will be merged! Writing the code is often the easy part — deciding how to do something, or whether to do it at all, is harder and more important.

## PlainX Community Packages

There will be a number of things that we don't want to officially maintain and support, especially when it comes to integrations with commercial SaaS services — these are best left to the vendor themselves, or a community member who wants to run with it. When in doubt, just [open a discussion and ask](https://github.com/dropseed/plain/discussions).

If you want to develop your own package that works with Plain, you should use the `plainx` community namespace. Like `plain`, the `plainx` prefix intended to be a [PEP 420 "implicit namespace"](https://peps.python.org/pep-0420/) — this just means that you can put your code in `plainx/{custom}` and it can be imported as `plainx.{custom}`. For this to work, the only thing you really need to know is that you should _not_ have a `plainx/__init__.py` file in your source.

There are also plenty of things that don't warrant an entire package! Copy and paste is encouraged. If you have a single-file solution to a common problem and want to share it, email support@plainframework.com about ways we can help.

## Development Setup

### Database dependencies

PostgreSQL is already included via `psycopg[binary]` in the dev dependencies.
