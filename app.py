"""Extension declaration, secrets, lifecycle hooks.

WHY BYOK (bring-your-own-key), same reasoning as MuleSoft Connector /
DataForSEO Connector / Make.com Connector. Stripe is the user's OWN
payments account -- Imperal cannot and should not broker access to
someone else's money centrally. The user pastes their own Stripe API
key once, Vault-encrypted via `ctx.secrets`, and every call runs
against their own Stripe account and their own usage/fees.

WHY A PLAIN BEARER SECRET KEY, NOT OAUTH2 (unlike MuleSoft/Workato).

Stripe authenticates API requests with a single Bearer API key
(docs.stripe.com/keys, confirmed during Discovery 2026-08-20) -- there is
no client-credentials or authorization-code dance for a user managing
their OWN account (that OAuth flow -- "Connect with Stripe" -- exists
only for *platforms* onboarding *other people's* Stripe accounts, which
is a different, later-scoped product surface). `connect_stripe` therefore
just validates the pasted key against `GET /v1/balance` and stores it.

WHY WE ACCEPT BOTH A SECRET KEY (sk_*) AND A RESTRICTED KEY (rk_*), AND
STEER TOWARD RESTRICTED.

Stripe explicitly recommends Restricted API Keys with only the
permissions actually needed over the unrestricted secret key
(docs.stripe.com/keys, "Restricted API keys" section, confirmed
2026-08-20). Both key shapes work identically over Bearer auth, so the
connector accepts either, but `connect_stripe`'s docstring and the
connect-form help text both point new users at creating a Restricted Key
scoped to what this connector actually touches.

WHY SANDBOX (test mode) IS A PROPERTY OF THE KEY ITSELF, NOT A TOGGLE.

Unlike DataForSEO's Sandbox/Live switch (a separate flag DataForSEO's own
API reads), Stripe's test vs. live mode is baked into the key prefix
(`sk_test_`/`rk_test_` vs `sk_live_`/`rk_live_`) and the two modes are
completely separate object graphs on Stripe's side (confirmed 2026-08-20).
The connector detects and surfaces this from the key prefix rather than
exposing a separate mode toggle that could desync from the real key.

WHY `write_mode="both"`, SAME REASONING AS THE REST OF THE PORTFOLIO.

Declaring `write_mode="user"` would mean only the platform's generic
Secrets screen could write this -- leaving a first-time user with no
in-app screen explaining what a Stripe API key even is or whether what
they pasted actually works. `"both"` keeps the generic Secrets screen as
a fallback while letting `connect_stripe` validate the key against
Stripe's own API *before* writing it.

WHY ONE SECRET HOLDING A JSON ARRAY (multi-account), SAME PRECEDENT AS
MULESOFT CONNECTOR / POWER AUTOMATE CONNECTOR / SLACK CONNECTOR.

Stripe now supports Organizations spanning several separate Stripe
accounts (docs.stripe.com/api, confirmed 2026-08-20) -- a user may
reasonably run more than one business (or a Test + Live pair they want
visible side by side) through this connector. `ctx.secrets` only
supports a fixed, manifest-declared set of NAMES -- there is no "one
secret per connection_id" primitive. `stripe_connections` holds a JSON
array of `{id, label, secret_key, mode}` objects; `schemas.py`'s
`connection_id` parameter on every tool call addresses one specific
entry -- see handlers.py's `_load_connections`/`_save_connections`.

WHY A SEPARATE `stripe_webhook_secrets` SECRET.

Webhook signing secrets (`whsec_*`) are per-endpoint, not per-account,
and are never sent to Stripe -- they are only used LOCALLY to verify an
inbound signature (docs.stripe.com/webhooks/signature, confirmed
2026-08-20). They are stored separately so a webhook secret rotation
never touches the API-key connection record.
"""
from __future__ import annotations

from imperal_sdk import ChatExtension, Extension

ext = Extension(
    "stripe-connector",
    version="0.1.0",
    display_name="Stripe",
    description=(
        "Connect your own Stripe account (via your own secret or "
        "restricted API key) to manage payments from Imperal -- "
        "customers, payment intents, charges, refunds, payment methods, "
        "products, prices, subscriptions, invoices, checkout sessions, "
        "payment links, coupons and promotion codes, balance and payouts, "
        "disputes, Connect accounts and transfers, webhook endpoints, "
        "events, tax rates, setup intents, plus revenue/health rollups "
        "and bulk operations. Nothing is hosted or proxied by Imperal "
        "beyond the request itself -- your key, your account, your fees."
    ),
    icon="icon.svg",
    capabilities=[
        "stripe:read",
        "stripe:write",
    ],
    actions_explicit=True,
    system=False,
)

chat = ChatExtension(
    ext,
    tool_name="stripe",
    description=(
        "Stripe Connector -- connect your own Stripe account via an API "
        "key, then manage customers, payments, subscriptions, invoices, "
        "checkout, Connect accounts, payouts, disputes and webhooks."
    ),
)

ext.secret(
    "stripe_connections",
    (
        "Your connected Stripe accounts -- stored as a JSON array, one "
        "entry per account, each with its own secret/restricted API key. "
        "Managed through connect_stripe / disconnect_stripe -- you "
        "should not need to edit this directly."
    ),
    required=True,
    write_mode="both",
    max_bytes=65536,
    rotation_hint_days=90,
)(lambda: None)

ext.secret(
    "stripe_webhook_secrets",
    (
        "Signing secrets (whsec_*) for webhook endpoints you've registered "
        "through this connector, stored separately from your API keys -- "
        "used only locally to verify an inbound Stripe-Signature header, "
        "never sent to Stripe."
    ),
    required=False,
    write_mode="both",
    max_bytes=16384,
    rotation_hint_days=180,
)(lambda: None)


@ext.health_check
async def health_check(ctx) -> dict:
    """Fast configuration health; no third-party call -- just confirms at
    least one Stripe account connection is stored, same shape as MuleSoft
    Connector's health_check."""
    import json as _json
    raw = await ctx.secrets.get("stripe_connections")
    try:
        count = len(_json.loads(raw)) if raw else 0
    except Exception:
        count = 0
    return {
        "healthy": True,
        "detail": (
            f"{count} Stripe account(s) connected." if count
            else "Not connected yet -- run connect_stripe."
        ),
    }
