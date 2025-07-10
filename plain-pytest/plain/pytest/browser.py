import datetime
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from plain.test import Client

if TYPE_CHECKING:
    from playwright.sync_api import Browser


class TestBrowser:
    def __init__(self, browser: "Browser", database_url: str):
        self.browser = browser

        self.database_url = database_url
        self.wsgi = "plain.wsgi:app"
        self.protocol = "https"
        self.host = "localhost"
        self.port = _get_available_port()
        self.base_url = f"{self.protocol}://{self.host}:{self.port}"
        self.server_process = None
        self.tmpdir = tempfile.TemporaryDirectory()

        # Set the initial browser context
        self.reset_context()

    def force_login(self, user):
        # Make sure existing session cookies are cleared
        self.context.clear_cookies()

        client = Client()
        client.force_login(user)

        cookies = []

        for morsel in client.cookies.values():
            cookie = {
                "name": morsel.key,
                "value": morsel.value,
                # Set this by default because playwright needs url or domain/path pair
                # (Plain does this in response, but this isn't going through a response)
                "domain": self.host,
            }
            # These fields are all optional
            if url := morsel.get("url"):
                cookie["url"] = url
            if domain := morsel.get("domain"):
                cookie["domain"] = domain
            if path := morsel.get("path"):
                cookie["path"] = path
            if expires := morsel.get("expires"):
                cookie["expires"] = expires
            if httponly := morsel.get("httponly"):
                cookie["httpOnly"] = httponly
            if secure := morsel.get("secure"):
                cookie["secure"] = secure
            if samesite := morsel.get("samesite"):
                cookie["sameSite"] = samesite

            cookies.append(cookie)

        self.context.add_cookies(cookies)

    def logout(self):
        self.context.clear_cookies()

    def reset_context(self):
        """Create a new browser context with the base URL and ignore HTTPS errors."""
        self.context = self.browser.new_context(
            base_url=self.base_url,
            ignore_https_errors=True,
        )

    def new_page(self):
        """Create a new page in the current context."""
        return self.context.new_page()

    def discover_urls(self, urls: list[str]) -> list[str]:
        """Recursively discover all URLs on the page and related pages until we don't see anything new"""

        def relative_url(url: str) -> str:
            """Convert a URL to a relative URL based on the base URL."""
            if url.startswith(self.base_url):
                return url[len(self.base_url) :]
            return url

        # Start with the initial URLs
        to_visit = {relative_url(url) for url in urls}
        visited = set()

        # Create a new page to use for all crawling
        page = self.context.new_page()

        while to_visit:
            # Move the url from to_visit to visited
            url = to_visit.pop()

            response = page.goto(url)

            visited.add(url)

            # Don't process links that aren't on our site
            if not response.url.startswith(self.base_url):
                continue

            # Find all <a> links on the page
            for link in page.query_selector_all("a"):
                if href := link.get_attribute("href"):
                    # Remove fragments
                    href = href.split("#")[0]
                    if not href:
                        # Empty URL, skip it
                        continue

                    parsed = urlparse(href)
                    # Skip non-http(s) links (mailto:, tel:, javascript:, etc.)
                    if parsed.scheme and parsed.scheme not in ("http", "https"):
                        continue

                    # Skip external HTTP links
                    if parsed.scheme in ("http", "https") and not href.startswith(
                        self.base_url
                    ):
                        continue

                    visit_url = relative_url(href)
                    if visit_url not in visited:
                        to_visit.add(visit_url)

        page.close()

        return list(visited)

    def generate_certificates(self):
        """Generate self-signed certificates for HTTPS."""

        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        # Create certificate
        subject = issuer = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, self.host),
            ]
        )

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(datetime.UTC))
            .not_valid_after(
                datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=365)
            )
            .add_extension(
                x509.SubjectAlternativeName(
                    [
                        x509.DNSName(self.host),
                    ]
                ),
                critical=False,
            )
            .sign(private_key, hashes.SHA256())
        )

        # Write certificate and key to files
        cert_file = pathlib.Path(self.tmpdir.name) / "cert.pem"
        key_file = pathlib.Path(self.tmpdir.name) / "key.pem"

        with open(cert_file, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        with open(key_file, "wb") as f:
            f.write(
                private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )

        return str(cert_file), str(key_file)

    def run_server(self):
        cert_file, key_file = self.generate_certificates()

        env = os.environ.copy()

        if self.database_url:
            env["DATABASE_URL"] = self.database_url

        gunicorn = pathlib.Path(sys.executable).with_name("gunicorn")

        self.server_process = subprocess.Popen(
            [
                str(gunicorn),
                self.wsgi,
                "--bind",
                f"{self.host}:{self.port}",
                "--certfile",
                cert_file,
                "--keyfile",
                key_file,
                "--workers",
                "2",
                "--timeout",
                "10",
                "--log-level",
                "warning",
            ],
            env=env,
        )

        time.sleep(0.7)  # quick grace period

    def cleanup_server(self):
        if self.server_process:
            self.server_process.terminate()
            self.server_process.wait()
            self.server_process = None

        self.tmpdir.cleanup()


def _get_available_port() -> int:
    """Get a randomly available port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port
