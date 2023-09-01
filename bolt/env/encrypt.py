import difflib
import os

from cryptography.fernet import Fernet

from bolt.exceptions import ValidationError


class Env:
    def __init__(self, path):
        self.env_file = EnvFile(path)
        self.key_file = EnvKeyFile(path + ".key")
        self.encrypted_file = EncryptedEnvFile(path + ".encrypted", self.key_file)

    @staticmethod
    def find_files(path) -> list[str]:
        # These may or may not exist, but these
        # the ones we expect should exist
        env_paths = set()

        for f in os.listdir(path):
            if f.endswith(".example"):
                continue
            if f.startswith(".env"):
                if f.endswith(".encrypted"):
                    f = f[: -len(".encrypted")]
                if f.endswith(".key"):
                    f = f[: -len(".key")]
                env_paths.add(f)

        return list(env_paths)

    def check(self) -> None:
        if self.encrypted_file.exists() and not self.key_file.exists():
            raise ValidationError(
                f'File "{self.path}" is already encrypted, but no key exists. You need a copy of {self.key_path}.'
            )

    def diff(self, reverse=False) -> str:
        if reverse:
            diff_lines = difflib.unified_diff(
                self.encrypted_file.decrypted_contents.splitlines(),
                self.env_file.content.splitlines(),
                fromfile=self.env_file.path,
                tofile=self.encrypted_file.path,
            )
        else:
            diff_lines = difflib.unified_diff(
                self.env_file.content.splitlines(),
                self.encrypted_file.decrypted_contents.splitlines(),
                fromfile=self.encrypted_file.path,
                tofile=self.env_file.path,
            )
        return "\n".join(diff_lines)

    def encrypt(self) -> None:
        if not self.key_file.exists():
            self.key_file.generate_key()

        self.encrypted_file.save(self.env_file.content)

    def decrypt(self) -> None:
        self.env_file.save(self.encrypted_file.decrypted_contents)


class EnvFile:
    def __init__(self, path):
        self.path = path

    def __str__(self) -> str:
        return f"Env {self.path}"

    def exists(self) -> bool:
        return os.path.exists(self.path)

    @property
    def content(self) -> str:
        with open(self.path) as f:
            return f.read()

    def save(self, content) -> None:
        if not content.endswith("\n"):
            content += "\n"  # Always add a trailing newline

        with open(self.path, "w") as f:
            f.write(content)


class EncryptedEnvFile:
    def __init__(self, path, key_file):
        self.path = path
        self.key_file = key_file

    def __str__(self) -> str:
        return f"Encrypted env {self.path}"

    def exists(self) -> bool:
        return os.path.exists(self.path)

    @property
    def content(self) -> str:
        with open(self.path) as f:
            return f.read()

    @property
    def decrypted_contents(self) -> str:
        return self.key_file.decrypt(self.content)

    def save(self, decrypted_content) -> None:
        encrypted_content = self.key_file.encrypt(decrypted_content)
        with open(self.path, "w") as f:
            f.write(encrypted_content)


class EnvKeyFile:
    def __init__(self, path):
        self.path = path

    def __str__(self) -> str:
        return f"Env key {self.path}"

    @property
    def key(self) -> str:
        with open(self.path) as f:
            return f.read()

    def exists(self) -> bool:
        return os.path.exists(self.path)

    def generate_key(self) -> None:
        key = Fernet.generate_key().decode()
        with open(self.path, "w") as f:
            f.write(key)

    def encrypt(self, content) -> str:
        fernet = Fernet(self.key.encode())
        return fernet.encrypt(content.encode()).decode()

    def decrypt(self, content) -> str:
        fernet = Fernet(self.key.encode())
        return fernet.decrypt(content.encode()).decode()
