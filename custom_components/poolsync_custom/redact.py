"""Shared redaction helpers for sensitive PoolSync data."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .const import API_RESPONSE_PASSWORD, HEADER_AUTHORIZATION

REDACTED = "<redacted>"

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
