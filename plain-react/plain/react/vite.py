from __future__ import annotations

import json
import os
import shutil
import subprocess

from plain.runtime import APP_PATH


def get_react_root() -> str:
    """Get the root directory for React source files (where vite.config.js lives)."""
    # The React root is the directory containing pyproject.toml (project root),
    # which is one level up from the app/ directory
    return str(APP_PATH.parent)


def get_vite_config_path() -> str:
    return os.path.join(get_react_root(), "vite.config.js")


def get_package_json_path() -> str:
    return os.path.join(get_react_root(), "package.json")


def npx_available() -> bool:
    return shutil.which("npx") is not None


def run_vite_dev() -> None:
    """Start the Vite dev server for React HMR."""
    root = get_react_root()

    if not os.path.exists(get_package_json_path()):
        print("No package.json found. Run 'plain react init' first.")
        return

    if not npx_available():
        print("npx not found. Install Node.js to use the React dev server.")
        return

    print("Starting Vite dev server...")
    subprocess.run(
        ["npx", "vite"],
        cwd=root,
        check=False,
    )


def run_vite_build() -> None:
    """Build React assets for production."""
    root = get_react_root()

    if not os.path.exists(get_package_json_path()):
        print("No package.json found. Run 'plain react init' first.")
        return

    if not npx_available():
        print("npx not found. Install Node.js to build React assets.")
        return

    print("Building React assets...")
    result = subprocess.run(
        ["npx", "vite", "build"],
        cwd=root,
        check=False,
    )

    if result.returncode != 0:
        print("Vite build failed!")
        exit(result.returncode)

    # Copy the built manifest so we can resolve asset paths
    manifest_path = os.path.join(
        root, "app", "assets", "react", ".vite", "manifest.json"
    )
    if os.path.exists(manifest_path):
        print(f"Build manifest: {manifest_path}")

    print("React build complete.")


def create_vite_config(root: str) -> None:
    """Create a default vite.config.js for a Plain React project."""
    config = """\
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  root: ".",
  build: {
    outDir: "app/assets/react",
    manifest: true,
    rollupOptions: {
      input: "app/react/main.jsx",
    },
  },
  server: {
    origin: "http://localhost:5173",
  },
});
"""
    path = os.path.join(root, "vite.config.js")
    with open(path, "w") as f:
        f.write(config)
    print(f"Created {os.path.relpath(path)}")


def create_package_json(root: str) -> None:
    """Create a default package.json for a Plain React project."""
    data = {
        "private": True,
        "type": "module",
        "scripts": {
            "dev": "vite",
            "build": "vite build",
        },
        "dependencies": {
            "react": "^19.0.0",
            "react-dom": "^19.0.0",
        },
        "devDependencies": {
            "@vitejs/plugin-react": "^4.0.0",
            "vite": "^6.0.0",
        },
    }
    path = os.path.join(root, "package.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print(f"Created {os.path.relpath(path)}")


def create_react_entrypoint(root: str) -> None:
    """Create the React app entry point and example page component."""
    react_dir = os.path.join(root, "app", "react")
    pages_dir = os.path.join(react_dir, "pages")
    os.makedirs(pages_dir, exist_ok=True)

    # Main entry point
    main_jsx = """\
import { createPlainApp } from "./plain-react";

createPlainApp({
  // Eagerly import all page components from the pages/ directory
  resolve: (name) => {
    const pages = import.meta.glob("./pages/**/*.jsx", { eager: true });
    const page = pages[`./pages/${name}.jsx`];
    if (!page) {
      throw new Error(`Page component "${name}" not found.`);
    }
    return page;
  },
});
"""
    main_path = os.path.join(react_dir, "main.jsx")
    with open(main_path, "w") as f:
        f.write(main_jsx)
    print(f"Created {os.path.relpath(main_path)}")

    # Example page component
    index_jsx = """\
export default function Index({ greeting }) {
  return (
    <div>
      <h1>{greeting || "Welcome to Plain + React"}</h1>
      <p>Edit this component in app/react/pages/Index.jsx</p>
    </div>
  );
}
"""
    index_path = os.path.join(pages_dir, "Index.jsx")
    with open(index_path, "w") as f:
        f.write(index_jsx)
    print(f"Created {os.path.relpath(index_path)}")
