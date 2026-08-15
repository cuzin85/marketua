"""Tests for per-provider enable/disable config."""

from __future__ import annotations

from marketua.config import provider_enabled


def test_providers_are_enabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("MARKETUA_DISABLE_PROVIDERS", raising=False)
    assert provider_enabled("olx")
    assert provider_enabled("hotline")
    assert provider_enabled("prom")


def test_providers_can_be_disabled_explicitly(monkeypatch) -> None:
    monkeypatch.setenv("MARKETUA_DISABLE_PROVIDERS", "olx,prom")
    assert not provider_enabled("olx")
    assert not provider_enabled("prom")
    assert provider_enabled("hotline")
