"""Shared fixtures -- mirrors DataForSEO Connector's / Media Studio's ctx fixture."""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def ctx():
    from imperal_sdk.testing import MockContext, MockSecretStore

    mock = MockContext()
    mock.secrets = MockSecretStore({})
    return mock


@pytest.fixture
def ctx_connected(ctx):
    """Same as `ctx` but with a Stripe test-mode connection already saved."""
    from imperal_sdk.testing import MockSecretStore
    connections = [{
        "id": "test-connection-id",
        "label": "Stripe (test mode)",
        "api_key": "sk_test_51ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop",
        "is_test": True,
        "connected_at": "2026-08-20T00:00:00+00:00",
    }]
    ctx.secrets = MockSecretStore({
        "stripe_connections": json.dumps(connections),
    })
    return ctx
