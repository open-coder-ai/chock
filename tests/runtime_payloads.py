"""The runtime payloads and wire denies live in the package (`chock.doctor.payloads`); this keeps the old import path."""

from __future__ import annotations

from chock.doctor.payloads import DENY_ON_THE_WIRE, PAYLOADS

__all__ = ["DENY_ON_THE_WIRE", "PAYLOADS"]
