import platform
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import click


class MkcertManager:
    def __init__(self) -> None:
        self.mkcert_bin: str | None = None

    def setup_mkcert(
        self, install_path: Path, *, force_reinstall: bool = False
    ) -> None:
        """Set up mkcert by checking if it's installed or downloading the binary and installing the local CA."""
        if mkcert_path := shutil.which("mkcert"):
            self.mkcert_bin = mkcert_path
            # Run install if CA files don't exist, or if force reinstall
            if force_reinstall or not self._ca_files_exist():
                self.install_ca()
            return

        # mkcert not found system-wide, download to install_path
        install_path.mkdir(parents=True, exist_ok=True)
        binary_path = install_path / "mkcert"

        if force_reinstall and binary_path.exists():
            click.secho("Removing existing mkcert binary...", bold=True)
            binary_path.unlink()

        if not binary_path.exists():
            self._download_mkcert(binary_path)

        self.mkcert_bin = str(binary_path)

        # Run install if CA files don't exist, or if force reinstall
        if force_reinstall or not self._ca_files_exist():
            self.install_ca()

    def _download_mkcert(self, dest: Path) -> None:
        """Download the mkcert binary."""
        system = platform.system()
        machine = platform.machine().lower()

        # Map platform.machine() to mkcert's expected architecture strings
        arch_map = {
            "x86_64": "amd64",
            "amd64": "amd64",
            "arm64": "arm64",
            "aarch64": "arm64",
        }
        arch = arch_map.get(machine, "amd64")

        os_map = {
            "Darwin": "darwin",
            "Linux": "linux",
            "Windows": "windows",
        }
        os_name = os_map.get(system)
        if not os_name:
            click.secho(f"Unsupported OS: {system}", fg="red")
            sys.exit(1)

        mkcert_url = f"https://dl.filippo.io/mkcert/latest?for={os_name}/{arch}"
        click.secho(f"Downloading mkcert from {mkcert_url}...", bold=True)
        urllib.request.urlretrieve(mkcert_url, dest)
        dest.chmod(0o755)

    def _get_ca_root(self) -> Path | None:
        """Get the mkcert CAROOT directory."""
        if not self.mkcert_bin:
            return None
        result = subprocess.run(
            [self.mkcert_bin, "-CAROOT"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
        return None

    def _ca_files_exist(self) -> bool:
        """Check if the CA root files exist."""
        ca_root = self._get_ca_root()
        if not ca_root:
            return False
        return (ca_root / "rootCA.pem").exists() and (
            ca_root / "rootCA-key.pem"
        ).exists()

    def install_ca(self) -> None:
        """Install the mkcert CA into the system trust store.

        Running `mkcert -install` is idempotent - if already installed,
        it just prints a message without prompting for a password.
        """
        if not self.mkcert_bin:
            return

        # Don't capture output so user can see messages and respond to password prompts
        result = subprocess.run([self.mkcert_bin, "-install"])

        if result.returncode != 0:
            click.secho("Failed to install mkcert CA", fg="red")
            raise SystemExit(1)

    def generate_certs(
        self, domain: str, storage_path: Path, *, force_regenerate: bool = False
    ) -> tuple[Path, Path]:
        cert_path = storage_path / f"{domain}-cert.pem"
        key_path = storage_path / f"{domain}-key.pem"
        timestamp_path = storage_path / f"{domain}.timestamp"
        update_interval = 60 * 24 * 3600  # 60 days in seconds

        # Check if the certs exist and if the timestamp is recent enough
        if not force_regenerate:
            if cert_path.exists() and key_path.exists() and timestamp_path.exists():
                last_updated = timestamp_path.stat().st_mtime
                if time.time() - last_updated < update_interval:
                    return cert_path, key_path

        storage_path.mkdir(parents=True, exist_ok=True)

        if not self.mkcert_bin:
            raise RuntimeError("mkcert is not set up. Call setup_mkcert first.")

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
