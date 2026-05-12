"""Shared context for the greeting fixture — designed for byte-identical parity.

The template is written on a single line so there are no inter-tag whitespace
differences between the two renderers. Demonstrates that text-, expression-,
and attribute-level parity is achievable without normalization.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class User:
    name: str
    handle: str


def one() -> dict:
    return {"user": User(name='Ada "the engineer"', handle="ada"), "unread": 1}


def many() -> dict:
    return {"user": User(name="Grace & Hopper", handle="grace"), "unread": 7}


def none() -> dict:
    return {"user": User(name="<anonymous>", handle="anon"), "unread": 0}


SCENARIOS = {"one": one, "many": many, "none": none}
