import platform
import shutil
import tempfile
from pathlib import Path

from plain.dev import mkcert as mkcert_module
from plain.dev.mkcert import MkcertManager
from plain.testing import patch


def test_windows_binary_gets_exe_extension():
    """On Windows, the downloaded mkcert binary must be named with a .exe
    extension, or CreateProcess can't launch it via subprocess.run."""

    def fake_download(self, dest):
        dest.write_bytes(b"fake binary")

    with (
        tempfile.TemporaryDirectory() as tmp,
        patch(mkcert_module, "PLAIN_CACHE_PATH", Path(tmp)),
        patch(platform, "system", lambda: "Windows"),
        patch(shutil, "which", lambda name: None),
        patch(MkcertManager, "_download_mkcert", fake_download),
        patch(MkcertManager, "install_ca", lambda self: None),
        patch(MkcertManager, "_ca_files_exist", lambda self: True),
    ):
        manager = MkcertManager()
        manager.setup_mkcert()

    assert manager.mkcert_bin is not None
    assert manager.mkcert_bin.endswith(".exe")
