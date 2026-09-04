import platform

from plain.dev.mkcert import MkcertManager


def test_windows_binary_gets_exe_extension(tmp_path, monkeypatch):
    """On Windows, the downloaded mkcert binary must be named with a .exe
    extension, or CreateProcess can't launch it via subprocess.run."""
    monkeypatch.setattr("plain.dev.mkcert.PLAIN_CACHE_PATH", tmp_path)
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr("plain.dev.mkcert.shutil.which", lambda name: None)

    def fake_download(self, dest):
        dest.write_bytes(b"fake binary")

    monkeypatch.setattr(MkcertManager, "_download_mkcert", fake_download)
    monkeypatch.setattr(MkcertManager, "install_ca", lambda self: None)
    monkeypatch.setattr(MkcertManager, "_ca_files_exist", lambda self: True)

    manager = MkcertManager()
    manager.setup_mkcert()

    assert manager.mkcert_bin.endswith(".exe")
