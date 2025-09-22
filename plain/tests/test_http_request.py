import pytest

from plain.http.request import split_domain_port, validate_host


@pytest.mark.parametrize(
    ("host", "expected_domain", "expected_port"),
    [
        # IPv4 addresses
        ("127.0.0.1", "127.0.0.1", ""),
        ("192.168.1.1", "192.168.1.1", ""),
        ("127.0.0.1:8000", "127.0.0.1", "8000"),
        ("192.168.1.1:443", "192.168.1.1", "443"),
        # IPv6 addresses
        ("[::1]", "[::1]", ""),
        ("[2001:db8::1]", "[2001:db8::1]", ""),
        (
            "[2001:0db8:85a3:0000:0000:8a2e:0370:7334]",
            "[2001:0db8:85a3:0000:0000:8a2e:0370:7334]",
            "",
        ),
        ("[::1]:8000", "[::1]", "8000"),
        ("[2001:db8::1]:443", "[2001:db8::1]", "443"),
        # Domain names
        ("example.com", "example.com", ""),
        ("sub.example.com", "sub.example.com", ""),
        ("deep.sub.example.com", "deep.sub.example.com", ""),
        ("example.com:8080", "example.com", "8080"),
        ("sub.example.com:443", "sub.example.com", "443"),
        ("api.example.com:3000", "api.example.com", "3000"),
        # Trailing dot removal
        ("example.com.", "example.com", ""),
        ("sub.example.com.:8080", "sub.example.com", "8080"),
        # Case normalization
        ("EXAMPLE.COM", "example.com", ""),
        ("Example.Com:8080", "example.com", "8080"),
        ("SUB.EXAMPLE.COM:443", "sub.example.com", "443"),
        # Borderline valid cases
        ("invalid..domain", "invalid..domain", ""),
        # Invalid hosts
        ("", "", ""),
        ("::1", "", ""),  # IPv6 without brackets
        ("not a valid host", "", ""),
        ("example$.com", "", ""),
        ("example.com:", "", ""),  # Trailing colon
        ("[::1", "", ""),  # Incomplete brackets
        ("example.com:8080:9000", "", ""),  # Multiple colons
    ],
)
def test_split_domain_port(host, expected_domain, expected_port):
    """Test split_domain_port function with various inputs."""
    domain, port = split_domain_port(host)
    assert domain == expected_domain
    assert port == expected_port


@pytest.mark.parametrize(
    ("host", "allowed_hosts", "expected"),
    [
        # Wildcard matching
        ("example.com", ["*"], True),
        ("sub.example.com", ["*"], True),
        ("127.0.0.1", ["*"], True),
        ("[::1]", ["*"], True),
        ("anything.at.all", ["*"], True),
        # Subdomain pattern matching
        ("example.com", [".example.com"], True),
        ("sub.example.com", [".example.com"], True),
        ("api.example.com", [".example.com"], True),
        ("deep.sub.example.com", [".example.com"], True),
        ("notexample.com", [".example.com"], False),
        ("example.org", [".example.com"], False),
        ("fakeexample.com", [".example.com"], False),
        # Exact domain matching
        ("example.com", ["example.com"], True),
        ("sub.example.com", ["example.com"], False),
        ("api.example.com", ["example.com"], False),
        ("example.org", ["example.com"], False),
        ("notexample.com", ["example.com"], False),
        # Multiple patterns
        ("example.com", ["example.com", ".api.example.com", "127.0.0.1"], True),
        ("api.example.com", ["example.com", ".api.example.com", "127.0.0.1"], True),
        ("v1.api.example.com", ["example.com", ".api.example.com", "127.0.0.1"], True),
        ("127.0.0.1", ["example.com", ".api.example.com", "127.0.0.1"], True),
        ("sub.example.com", ["example.com", ".api.example.com", "127.0.0.1"], False),
        ("other.com", ["example.com", ".api.example.com", "127.0.0.1"], False),
        # Literal asterisk pattern (not treated as wildcard)
        ("*.test.com", ["*.test.com"], True),
        ("anything.test.com", ["*.test.com"], False),
        ("api.test.com", ["*.test.com"], False),
        # IPv4 address matching
        ("127.0.0.1", ["127.0.0.1", "192.168.1.1"], True),
        ("192.168.1.1", ["127.0.0.1", "192.168.1.1"], True),
        ("127.0.0.2", ["127.0.0.1", "192.168.1.1"], False),
        ("10.0.0.1", ["127.0.0.1", "192.168.1.1"], False),
        # IPv6 address matching
        ("[::1]", ["[::1]", "[2001:db8::1]"], True),
        ("[2001:db8::1]", ["[::1]", "[2001:db8::1]"], True),
        ("[::2]", ["[::1]", "[2001:db8::1]"], False),
        ("[2001:db8::2]", ["[::1]", "[2001:db8::1]"], False),
        # Pattern case insensitive matching (host should be lowercase already)
        ("example.com", [".Example.Com"], True),
        ("sub.example.com", [".Example.Com"], True),
        ("api.test.com", ["API.TEST.COM"], True),
        # Empty allowed_hosts
        ("example.com", [], False),
        ("127.0.0.1", [], False),
        ("[::1]", [], False),
        # Empty pattern in allowed_hosts
        ("", ["", "example.com"], False),
        ("anything.com", ["", "example.com"], False),
        ("example.com", ["", "example.com"], True),
        # Complex subdomain patterns
        ("api.example.com", [".api.example.com", ".staging.example.com"], True),
        ("staging.example.com", [".api.example.com", ".staging.example.com"], True),
        ("v1.api.example.com", [".api.example.com", ".staging.example.com"], True),
        (
            "beta.staging.example.com",
            [".api.example.com", ".staging.example.com"],
            True,
        ),
        ("example.com", [".api.example.com", ".staging.example.com"], False),
        ("www.example.com", [".api.example.com", ".staging.example.com"], False),
        # Wildcard overrides other patterns
        (
            "anything.com",
            ["*", "exact.com", ".subdomain.com", "127.0.0.1", "[::1]"],
            True,
        ),
        (
            "random.domain.org",
            ["*", "exact.com", ".subdomain.com", "127.0.0.1", "[::1]"],
            True,
        ),
        (
            "192.168.1.100",
            ["*", "exact.com", ".subdomain.com", "127.0.0.1", "[::1]"],
            True,
        ),
        # Edge cases
        ("", ["example.com"], False),
        ("example .com", ["example.com"], False),
        ("a" * 50 + ".example.com", [".example.com"], True),  # Very long subdomain
    ],
)
def test_validate_host(host, allowed_hosts, expected):
    """Test validate_host function with various inputs."""
    assert validate_host(host, allowed_hosts) is expected
