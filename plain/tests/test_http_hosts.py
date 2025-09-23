import pytest

from plain.internal.middleware.hosts import split_domain_port, validate_host


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
        # Literal asterisk pattern (treated as literal string, not wildcard)
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
        # Edge cases
        ("", ["example.com"], False),
        ("example .com", ["example.com"], False),
        ("a" * 50 + ".example.com", [".example.com"], True),  # Very long subdomain
    ],
)
def test_validate_host(host, allowed_hosts, expected):
    """Test validate_host function with various inputs."""
    assert validate_host(host, allowed_hosts) is expected


@pytest.mark.parametrize(
    ("host", "allowed_hosts", "expected"),
    [
        # IPv4 CIDR tests
        ("192.168.1.100", ["192.168.1.0/24"], True),
        ("192.168.1.1", ["192.168.1.0/24"], True),
        ("192.168.1.254", ["192.168.1.0/24"], True),
        ("192.168.2.100", ["192.168.1.0/24"], False),
        ("10.0.5.1", ["10.0.0.0/8"], True),
        ("172.16.0.1", ["10.0.0.0/8"], False),
        # IPv4 single IP as CIDR
        ("192.168.1.1", ["192.168.1.1/32"], True),
        ("192.168.1.2", ["192.168.1.1/32"], False),
        # IPv4 larger networks
        ("172.16.5.10", ["172.16.0.0/12"], True),
        ("172.32.5.10", ["172.16.0.0/12"], False),
        ("127.0.0.1", ["127.0.0.0/8"], True),
        # IPv6 CIDR tests
        ("[2001:db8::1]", ["[2001:db8::]/32"], True),
        ("[2001:db8:1::1]", ["[2001:db8::]/32"], True),
        ("[2001:db9::1]", ["[2001:db8::]/32"], False),
        ("[::1]", ["[::]/0"], True),  # Match everything IPv6
        ("[2001:db8::1]", ["[fe80::]/10"], False),
        # IPv6 without brackets in pattern (should still work)
        ("[2001:db8::1]", ["2001:db8::/32"], True),
        ("[2001:db9::1]", ["2001:db8::/32"], False),
        # IPv6 single address as CIDR
        ("[::1]", ["[::1]/128"], True),
        ("[::2]", ["[::1]/128"], False),
        # Mixed CIDR and domain patterns
        ("192.168.1.50", ["192.168.1.0/24", ".example.com"], True),
        ("sub.example.com", ["192.168.1.0/24", ".example.com"], True),
        ("192.168.2.50", ["192.168.1.0/24", ".example.com"], False),
        ("other.com", ["192.168.1.0/24", ".example.com"], False),
        # Multiple CIDR patterns
        ("192.168.1.50", ["10.0.0.0/8", "192.168.0.0/16"], True),
        ("10.5.0.1", ["10.0.0.0/8", "192.168.0.0/16"], True),
        ("172.16.0.1", ["10.0.0.0/8", "192.168.0.0/16"], False),
        # Domain names should not match CIDR patterns
        ("example.com", ["192.168.1.0/24"], False),
        ("192.168.1.com", ["192.168.1.0/24"], False),
        # Non-IP strings should not match CIDR
        ("not-an-ip", ["192.168.1.0/24"], False),
        ("192.168.1", ["192.168.1.0/24"], False),  # Incomplete IP
        # Invalid CIDR patterns should be ignored (treated as literal)
        ("192.168.1.0/24", ["192.168.1.0/24"], False),  # Literal match of CIDR string
        ("192.168.1.100", ["192.168.1.0/999"], False),  # Invalid CIDR
        ("192.168.1.100", ["192.168.1.0/"], False),  # Invalid CIDR
        # Edge cases
        ("0.0.0.0", ["0.0.0.0/0"], True),  # Match all IPv4
        ("255.255.255.255", ["0.0.0.0/0"], True),
        (
            "[ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff]",
            ["[::]/0"],
            True,
        ),  # Match all IPv6
    ],
)
def test_validate_host_cidr(host, allowed_hosts, expected):
    """Test validate_host function with CIDR notation patterns."""
    assert validate_host(host, allowed_hosts) is expected
