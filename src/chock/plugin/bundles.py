"""Bundles: named policy sets packaged as one plugin. A bundle is a selection (`chock install --selection`)."""

from __future__ import annotations


class BundleError(ValueError):
    """A bundle that cannot be packaged: its members collide."""


def bundle_description(purpose: str, members: list[tuple[str, str]]) -> str:
    """The bundle's claim, member by member; the posture suffix is added by the client's own manifest."""
    return f"{purpose.strip()} Members: " + "; ".join(f"{name}: {what}" for name, what in members) + "."
