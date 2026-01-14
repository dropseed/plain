# plain.esbuild

**Build and bundle JavaScript files using esbuild.**

- [Overview](#overview)
- [CLI commands](#cli-commands)
    - [Build](#build)
    - [Dev](#dev)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

Plain esbuild provides a simple way to bundle JavaScript files using [esbuild](https://esbuild.github.io/). Any asset file with `.esbuild.` in its name will be automatically bundled into a corresponding `.esbuilt.` file.

For example, if you have `app/assets/js/app.esbuild.js`, running the build command will create `app/assets/js/app.esbuilt.js` alongside it.

```javascript
// app/assets/js/app.esbuild.js
import { someFunction } from "./utils.js";

someFunction();
```

After building, you can reference the bundled file in your templates:

```html
<script src="{{ asset('js/app.esbuilt.js') }}"></script>
```

The bundler automatically:

- Bundles all imports into a single file
- Generates source maps
- Minifies the output (in production builds)
- Targets the browser platform

## CLI commands

### Build

Build all `.esbuild.` files in your asset directories:

```bash
plain esbuild build
```

This command finds all files containing `.esbuild.` in your asset directories and bundles them using esbuild. The output files are minified by default.

### Dev

Watch for changes and rebuild automatically:

```bash
plain esbuild dev
```

The dev command performs an initial build (without minification) and then watches for file changes. When you modify a `.esbuild.` file, it will automatically rebuild. If you delete a source file, the corresponding `.esbuilt.` output file is also removed.

## FAQs

#### What files should I gitignore?

Add this pattern to your `.gitignore` to exclude the generated bundle files:

```
**/assets/**/*.esbuilt.*
```

#### Do I need to install esbuild separately?

Yes, esbuild must be available via `npx`. Make sure you have a `package.json` in your project with esbuild as a dependency:

```bash
npm install --save-dev esbuild
```

#### How do I use this with plain build?

The esbuild commands integrate with the Plain build system through [entrypoints](./entrypoints.py). When you run `plain build`, it will automatically run esbuild first if you have configured it in your build pipeline.

#### Can I customize esbuild options?

The [`esbuild`](./core.py#esbuild) function accepts a `minify` option. For more advanced customization, you can call the function directly in your own build scripts.

## Installation

Install the `plain.esbuild` package from [PyPI](https://pypi.org/project/plain.esbuild/):

```bash
uv add plain.esbuild
```

Make sure you have esbuild available in your project:

```bash
npm install --save-dev esbuild
```

Create a JavaScript file with `.esbuild.` in the name:

```javascript
// app/assets/js/app.esbuild.js
console.log("Hello from esbuild!");
```

Run the build command:

```bash
plain esbuild build
```

Add the generated files to your `.gitignore`:

```
**/assets/**/*.esbuilt.*
```
