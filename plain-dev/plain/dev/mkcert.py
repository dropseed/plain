import platform
import shutil
import subprocess
import sys
import time
import urllib.request

import click


class MkcertManager:
    def __init__(self):
        self.mkcert_bin = None

    def setup_mkcert(self, install_path):
        """Set up mkcert by checking if it's installed or downloading the binary and installing the local CA."""
        if mkcert_path := shutil.which("mkcert"):
            # mkcert is already installed somewhere
            self.mkcert_bin = mkcert_path
        else:
            self.mkcert_bin = install_path / "mkcert"
            install_path.mkdir(parents=True, exist_ok=True)
            if not self.mkcert_bin.exists():
                system = platform.system()
                arch = platform.machine()

                # Map platform.machine() to mkcert's expected architecture strings
                arch_map = {
                    "x86_64": "amd64",
                    "amd64": "amd64",
                    "AMD64": "amd64",
                    "arm64": "arm64",
                    "aarch64": "arm64",
                }
                arch = arch_map.get(
                    arch.lower(), "amd64"
                )  # Default to amd64 if unknown

                if system == "Darwin":
                    os_name = "darwin"
                elif system == "Linux":
                    os_name = "linux"
                elif system == "Windows":
                    os_name = "windows"
                else:
                    click.secho("Unsupported OS", fg="red")
                    sys.exit(1)

                mkcert_url = f"https://dl.filippo.io/mkcert/latest?for={os_name}/{arch}"
                click.secho(f"Downloading mkcert from {mkcert_url}...", bold=True)
                urllib.request.urlretrieve(mkcert_url, self.mkcert_bin)
                self.mkcert_bin.chmod(0o755)
            self.mkcert_bin = str(self.mkcert_bin)  # Convert Path object to string

        if not self.is_mkcert_ca_installed():
            click.secho(
                "Installing mkcert local CA. You may be prompted for your password.",
                bold=True,
            )
            subprocess.run([self.mkcert_bin, "-install"], check=True)

    def is_mkcert_ca_installed(self):
        """Check if mkcert local CA is already installed using mkcert -check."""
        try:
            result = subprocess.run([self.mkcert_bin, "-check"], capture_output=True)
            output = result.stdout.decode() + result.stderr.decode()
            if "The local CA is not installed" in output:
                return False
            return True
        except Exception as e:
            click.secho(f"Error checking mkcert CA installation: {e}", fg="red")
            return False

    def generate_certs(self, domain, storage_path):
        cert_path = storage_path / f"{domain}-cert.pem"
        key_path = storage_path / f"{domain}-key.pem"
        timestamp_path = storage_path / f"{domain}.timestamp"
        update_interval = 60 * 24 * 3600  # 60 days in seconds

        # Check if the certs exist and if the timestamp is recent enough
        if cert_path.exists() and key_path.exists() and timestamp_path.exists():
            last_updated = timestamp_path.stat().st_mtime
            if time.time() - last_updated < update_interval:
                return cert_path, key_path

        storage_path.mkdir(parents=True, exist_ok=True)

        click.secho(f"Generating SSL certificates for {domain}...", bold=True)
        subprocess.run(
            [
                self.mkcert_bin,
                "-cert-file",
                str(cert_path),
                "-key-file",
                str(key_path),
                domain,
            ],
            check=True,
        )

        # Update the timestamp file to the current time
        with open(timestamp_path, "w") as f:
            f.write(str(time.time()))

        return cert_path, key_path
