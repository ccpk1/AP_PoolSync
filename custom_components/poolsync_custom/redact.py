"""Shared redaction helpers for sensitive PoolSync data."""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping
from typing import Any

from .const import API_RESPONSE_PASSWORD, HEADER_AUTHORIZATION

REDACTED = "<redacted>"

# Values shorter than this would mangle unrelated text when scrubbed by value.
_MIN_SCRUB_LENGTH = 5

# Matches a quoted JSON password value, e.g. "password": "secret".
_PASSWORD_VALUE_RE = re.compile(
    rf'(?i)("{re.escape(API_RESPONSE_PASSWORD)}"\s*:\s*")[^"]*(")'
)


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Return request headers with any authorization values fully redacted."""
    return {
        key: (REDACTED if key == HEADER_AUTHORIZATION and value else value)
        for key, value in headers.items()
    }


def redact_body(body: Any) -> Any:
    """Return a copy of a response body with password values redacted."""
    if isinstance(body, dict):
        return {
            key: (REDACTED if key == API_RESPONSE_PASSWORD else redact_body(value))
            for key, value in body.items()
        }
    if isinstance(body, list):
        return [redact_body(item) for item in body]
    if isinstance(body, str):
        return _PASSWORD_VALUE_RE.sub(rf"\1{REDACTED}\2", body)
    return body


def collect_sensitive_values(data: Any, sensitive_keys: Collection[str]) -> set[str]:
    """Collect string forms of values stored under sensitive keys, at any depth."""
    values: set[str] = set()

    def _collect(node: Any) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                if key in sensitive_keys and isinstance(value, str | int | float):
                    text = str(value)
                    if len(text) >= _MIN_SCRUB_LENGTH:
                        values.add(text)
                else:
                    _collect(value)
        elif isinstance(node, list):
            for item in node:
                _collect(item)

    _collect(data)
    return values


def redact_values(
    data: Any, sensitive_values: Iterable[str], replacement: str = REDACTED
) -> Any:
    """Return a copy of data with known sensitive values removed from all strings.

    Key-based redaction misses identifiers repeated inside free-form strings
    (exception messages, device names, derived sensor values), so known values
    are also scrubbed wherever they appear.
    """
    patterns = sorted(
        {value for value in sensitive_values if len(value) >= _MIN_SCRUB_LENGTH},
        key=len,
        reverse=True,
    )
    if not patterns:
        return data

    matcher = re.compile("|".join(re.escape(value) for value in patterns), re.I)

    def _scrub(node: Any) -> Any:
        if isinstance(node, str):
            return matcher.sub(replacement, node)
        if isinstance(node, Mapping):
            return {key: _scrub(value) for key, value in node.items()}
        if isinstance(node, list):
            return [_scrub(item) for item in node]
        return node

    return _scrub(data)
