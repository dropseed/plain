import os
import subprocess


def esbuild(input_path, output_path, *, minify=True):
    # Ensure the directory for the output file exists
    output_dir = os.path.dirname(output_path)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    print(f"Building {os.path.relpath(input_path)}")

    cmd = [
        "npx",
        "esbuild",
        input_path,
        "--bundle",
        f"--outfile={output_path}",
        "--sourcemap",
        "--platform=browser",
    ]

    if minify:
        cmd.append("--minify")

    result = subprocess.run(cmd)

    return result.returncode == 0


def get_esbuilt_path(input_path):
    # Rename .esbuild. to .esbuilt. in the output filename
    base_name = os.path.basename(input_path)
    base_name = base_name.replace(".esbuild.", ".esbuilt.")
    return os.path.join(os.path.dirname(input_path), base_name)
