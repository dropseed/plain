import json
import os
import subprocess
import tempfile


def _esbuild_command() -> list[str]:
    # Use the local binary directly when available — npx adds a few hundred ms
    # of resolution overhead per invocation
    local_bin = os.path.join("node_modules", ".bin", "esbuild")
    if os.path.exists(local_bin):
        return [local_bin]
    return ["npx", "esbuild"]


def esbuild(
    input_path: str, output_path: str, *, minify: bool = True
) -> set[str] | None:
    """Bundle an entry, returning the set of bundled input paths (None if the build failed)."""
    # Ensure the directory for the output file exists
    output_dir = os.path.dirname(output_path)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    print(f"Building {os.path.relpath(input_path)}")

    metafile_fd, metafile_path = tempfile.mkstemp(suffix=".json")
    os.close(metafile_fd)

    cmd = [
        *_esbuild_command(),
        input_path,
        "--bundle",
        f"--outfile={output_path}",
        f"--metafile={metafile_path}",
        "--sourcemap",
        "--platform=browser",
        "--jsx=automatic",
    ]

    if minify:
        cmd.append("--minify")

    try:
        if subprocess.run(cmd).returncode != 0:
            return None

        with open(metafile_path) as f:
            inputs = json.load(f)["inputs"]
    finally:
        os.unlink(metafile_path)

    # Resolve symlinks so these paths match watched-file paths by string equality
    return {os.path.realpath(path) for path in inputs}


# File extensions that esbuild compiles to a .js output
JS_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")


def get_esbuilt_path(input_path: str) -> str:
    # Rename .esbuild. to .esbuilt. in the output filename
    base_name = os.path.basename(input_path)
    base_name = base_name.replace(".esbuild.", ".esbuilt.")

    # JS-family entries (.ts, .tsx, .jsx, etc.) all compile to .js
    root, ext = os.path.splitext(base_name)
    if ext in JS_EXTENSIONS:
        base_name = root + ".js"

    return os.path.join(os.path.dirname(input_path), base_name)
