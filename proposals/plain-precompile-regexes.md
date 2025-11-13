# Pre-compile regular expressions

## Problem

Many functions compile regular expressions at runtime using `re.match()`, `re.search()`, `re.sub()`, etc. Python's `re` module only caches the 512 most recent patterns, and large projects can easily exceed this, causing unnecessary performance overhead.

Django is standardizing on pre-compiling all regexes (ticket #36729).

## Solution

Pre-compile frequently-used patterns at module level using `_lazy_re_compile()` (already available in `plain.utils.regex_helper`).

## Examples to fix

### High-priority (hot paths)

- `plain.utils.text.slugify()` - compiles 2 patterns per call
- `plain.elements.templates` - compiles 4+ patterns during template preprocessing
- `plain.observer.otel` - compiles patterns in request handling

### Lower-priority

- `plain.redirection.models` - model methods
- `plain.models.otel` - SQL parsing
- Script utilities (`type-coverage`, etc.)

## Guidelines

1. Pre-compile at module level for functions
2. Compile once in `__init__()` for class methods (see `CsrfViewMiddleware` for example)
3. Use `_lazy_re_compile()` for deferred compilation

## Note

Plain already uses this pattern well in many places (`utils.dateparse`, `csrf.middleware`). This is about being consistent everywhere.
