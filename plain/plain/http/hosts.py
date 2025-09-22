"""
Host validation utilities for ALLOWED_HOSTS functionality.

This module provides functions for validating hosts against allowed patterns,
including domain patterns, wildcards, and CIDR notation for IP ranges.
"""

import ipaddress

from plain.utils.regex_helper import _lazy_re_compile

host_validation_re = _lazy_re_compile(
    r"^([a-z0-9.-]+|\[[a-f0-9]*:[a-f0-9\.:]+\])(:[0-9]+)?$"
)


def split_domain_port(host: str) -> tuple[str, str]:
    """
    Return a (domain, port) tuple from a given host.

    Returned domain is lowercased. If the host is invalid, the domain will be
    empty.
    """
    host = host.lower()

    if not host_validation_re.match(host):
        return "", ""

    if host[-1] == "]":
        # It's an IPv6 address without a port.
        return host, ""
    bits = host.rsplit(":", 1)
    domain, port = bits if len(bits) == 2 else (bits[0], "")
    # Remove a trailing dot (if present) from the domain.
    domain = domain.removesuffix(".")
    return domain, port


def _is_same_domain(host: str, pattern: str) -> bool:
    """
    Return ``True`` if the host is either an exact match or a match
    to the wildcard pattern.

    Any pattern beginning with a period matches a domain and all of its
    subdomains. (e.g. ``.example.com`` matches ``example.com`` and
    ``foo.example.com``). Anything else is an exact string match.
    """
    if not pattern:
        return False

    pattern = pattern.lower()
    return (
        pattern[0] == "."
        and (host.endswith(pattern) or host == pattern[1:])
        or pattern == host
    )


def _parse_ip_address(
    host: str,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """
    Parse a host string as an IP address (IPv4 or IPv6).

    Returns the ipaddress.ip_address object if valid, None otherwise.
    Handles both bracketed and non-bracketed IPv6 addresses.
    """
    # Remove brackets from IPv6 addresses
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]

    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _parse_cidr_pattern(
    pattern: str,
) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    """
    Parse a CIDR pattern and return the network object if valid.

    Returns the ipaddress.ip_network object if valid CIDR notation, None otherwise.
    """
    # Check if it contains a slash (required for CIDR)
    if "/" not in pattern:
        return None

    # Remove brackets from IPv6 CIDR patterns
    test_pattern = pattern
    if pattern.startswith("[") and "]/" in pattern:
        # Handle format like [2001:db8::]/32
        bracket_end = pattern.find("]/")
        if bracket_end != -1:
            ip_part = pattern[1:bracket_end]
            cidr_part = pattern[bracket_end + 2 :]
            test_pattern = f"{ip_part}/{cidr_part}"
    elif pattern.startswith("[") and pattern.endswith("]") and "/" in pattern:
        # Handle format like [2001:db8::/32] (slash inside brackets)
        test_pattern = pattern[1:-1]

    try:
        return ipaddress.ip_network(test_pattern, strict=False)
    except ValueError:
        return None


def validate_host(host: str, allowed_hosts: list[str]) -> bool:
    """
    Validate the given host for this site.

    Check that the host looks valid and matches a host or host pattern in the
    given list of ``allowed_hosts``. Supported patterns:

    - ``*`` matches anything
    - ``.example.com`` matches a domain and all its subdomains
      (e.g. ``example.com`` and ``sub.example.com``)
    - ``example.com`` matches exactly that domain
    - ``192.168.1.0/24`` matches IP addresses in that CIDR range
    - ``[2001:db8::]/32`` matches IPv6 addresses in that CIDR range
    - ``192.168.1.1`` matches that exact IP address

    Note: This function assumes that the given host is lowercased and has
    already had the port, if any, stripped off.

    Return ``True`` for a valid host, ``False`` otherwise.
    """
    # Parse the host as an IP address if possible
    host_ip = _parse_ip_address(host)

    for pattern in allowed_hosts:
        # Wildcard matches everything
        if pattern == "*":
            return True

        # Check CIDR notation patterns using walrus operator
        if network := _parse_cidr_pattern(pattern):
            if host_ip and host_ip in network:
                return True
            continue

        # For non-CIDR patterns, use existing domain matching logic
        if _is_same_domain(host, pattern):
            return True

    return False
