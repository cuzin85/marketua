"""Tests for the package version exposed via serverInfo."""

from __future__ import annotations

import re

import marketua


def test_version_is_read_from_installed_package() -> None:
    # Version must come from the installed package metadata (pyproject.toml),
    # not a hardcoded value, so serverInfo.version never drifts.
    assert re.fullmatch(r"\d+\.\d+\.\d+.*", marketua.__version__)
