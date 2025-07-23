# plain-elements changelog

## [0.8.0](https://github.com/dropseed/plain/releases/plain-elements@0.8.0) (2025-07-23)

### What's changed

- The `Element` function parameter changed from `name` to `_element_name` to prevent naming conflicts with element attributes ([1e98317](https://github.com/dropseed/plain/commit/1e9831797ce699f429a188b3265d334cf2cbd3f3))
- Improved regex pattern for parsing self-closing icon elements ([f7e2c9a](https://github.com/dropseed/plain/commit/f7e2c9adbaf9c8d8846c7bfaf281404a33dcd97d))
- Enhanced error messages for unmatched capitalized tags to show the specific tag found ([f7e2c9a](https://github.com/dropseed/plain/commit/f7e2c9adbaf9c8d8846c7bfaf281404a33dcd97d))

### Upgrade instructions

- No changes required - the `_element_name` parameter change is internal to the `Element` function and does not affect template usage

## [0.7.2](https://github.com/dropseed/plain/releases/plain-elements@0.7.2) (2025-06-26)

### What's changed

- Added an initial `CHANGELOG.md` file to start tracking package changes ([82710c3](https://github.com/dropseed/plain/commit/82710c3))

### Upgrade instructions

- No changes required
