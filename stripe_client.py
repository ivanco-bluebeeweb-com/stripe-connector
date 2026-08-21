"""Stripe REST API client -- Bearer secret-key auth against the user's own
Stripe account, thin wrappers over the Core Resources (Payments, Checkout,
Billing, Connect) that this connector exposes as chat functions.

WHY A SINGLE SHARED REQUEST HELPER, SAME SHAPE AS mulesoft_client.py /
dfs_client.py's fail()/ClientFail pattern.

Every wrapper below funnels through `_request()` so auth, API-version
pinning, idempotency-key injection on writes, and error-code mapping are
handled in exactly one place instead of being repeated 60+ times.

WHY `Stripe-Version` IS PINNED EXPLICITLY ON EVERY REQUEST.

Stripe's API is versioned by date (docs.stripe.com/api/versioning,
confirmed 2026-08-20): a request without an explicit `Stripe-Version`
header uses whatever version is configured as the *account's default* in
the Dashboard, which can silently change the response shape if the user
(or someone with Dashboard access) ever updates it. Pinning a fixed,
known-good version here means this connector's parsing code never breaks
under the user's feet from an unrelated Dashboard change.

WHY IDEMPOTENCY KEYS ON EVERY WRITE (POST/DELETE), SAME PRINCIPLE STRIPE
ITSELF RECOMMENDS.

Stripe's idempotent-requests docs (docs.stripe.com/api/idempotent_requests,
confirmed 2026-08-20) recommend a fresh `Idempotency-Key` header on every
POST so a network retry (timeout, connection drop) can never double-charge
a card or double-create a subscription. Every write call below generates
one UUID per logical call.

WHY 401 vs 402 vs 403 vs 404 ARE HANDLED DIFFERENTLY.

Per Stripe's own error-codes doc: 401 means the API key itself is not
accepted (wrong/revoked key); 402 means the request was well-formed but
the *card itself* was declined (a normal, expected outcome the caller
must see verbatim, not a connector bug); 403 means the key is valid but
lacks permission for this action (very common with Restricted Keys, which
this connector actively encourages -- see app.py); 404 is a genuinely
missing object id. Collapsing these into one generic "failed" message
would hide exactly the distinction a user needs to fix their own key's
scopes or understand why a customer's card didn't work.
"""
from __future__ import annotations

import uuid
from typing import Any

API_BASE = "https://api.stripe.com/v1"
API_VERSION = "2026-03-25.dahlia"  # confirmed current pinned version, 2026-08-20

TOKEN_REJECTED = "TOKEN_REJECTED"
PERMISSION_DENIED = "PERMISSION_DENIED"
CARD_DECLINED = "CARD_DECLINED"
NOT_FOUND = "NOT_FOUND"
INVALID_REQUEST = "INVALID_REQUEST"
UNREACHABLE = "UNREACHABLE"
RATE_LIMITED = "RATE_LIMITED"
BACKEND_5XX = "BACKEND_5XX"
BACKEND_TIMEOUT = "BACKEND_TIMEOUT"

_MESSAGES = {
    TOKEN_REJECTED: "Stripe rejected this API key. Check it hasn't been revoked or mistyped.",
    PERMISSION_DENIED: "This API key doesn't have permission for that action. If it's a Restricted Key, add the missing scope in the Stripe Dashboard.",
    CARD_DECLINED: "The card was declined.",
    NOT_FOUND: "That Stripe object was not found.",
    INVALID_REQUEST: "Stripe rejected the request as invalid.",
    UNREACHABLE: "Could not reach Stripe.",
    RATE_LIMITED: "Stripe is rate-limiting requests; try again shortly.",
    BACKEND_5XX: "Stripe returned a server error; try again shortly.",
    BACKEND_TIMEOUT: "Stripe took too long to respond; try again shortly.",
}
_RETRYABLE = {RATE_LIMITED, BACKEND_5XX, BACKEND_TIMEOUT}


def fail(code: str, detail: str = "") -> dict:
    message = _MESSAGES.get(code, code)
    if detail:
        message = f"{message} ({detail})"
    return {"ok": False, "error_code": code, "error": message, "retryable": code in _RETRYABLE}


class ClientFail(Exception):
    def __init__(self, payload: dict):
        super().__init__(payload.get("error", "Stripe request failed"))
        self.payload = payload


def is_valid_key_shape(key: str) -> bool:
    """Stripe secret/restricted keys always start with sk_ or rk_, each
    followed by either 'test_' or 'live_' (docs.stripe.com/keys,
    confirmed 2026-08-20)."""
    return bool(key) and key.startswith(("sk_test_", "sk_live_", "rk_test_", "rk_live_"))


def is_test_key(key: str) -> bool:
    return "_test_" in key


def _headers(api_key: str, idempotency_key: str | None = None) -> dict:
    h = {
        "Authorization": f"Bearer {api_key}",
        "Stripe-Version": API_VERSION,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if idempotency_key:
        h["Idempotency-Key"] = idempotency_key
    return h


def _flatten(data: dict, prefix: str = "") -> dict:
    """Stripe's API takes application/x-www-form-urlencoded bodies with
    bracket-notation for nested objects/arrays (e.g. metadata[foo]=bar,
    items[0][price]=price_x) -- not JSON. Recursively flattens a Python
    dict/list into that wire format."""
    out: dict[str, Any] = {}
    for k, v in data.items():
        key = f"{prefix}[{k}]" if prefix else str(k)
        if v is None:
            continue
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        elif isinstance(v, (list, tuple)):
            for i, item in enumerate(v):
                idx_key = f"{key}[{i}]"
                if isinstance(item, dict):
                    out.update(_flatten(item, idx_key))
                else:
                    out[idx_key] = item
        elif isinstance(v, bool):
            out[key] = "true" if v else "false"
        else:
            out[key] = v
    return out


async def _request(ctx, method: str, api_key: str, path: str,
                    params: dict | None = None, write: bool = False) -> dict:
    """Core request helper. Returns the parsed JSON body on 2xx, or raises
    ClientFail with a fail()-shaped payload on any error."""
    url = f"{API_BASE}{path}"
    idem = str(uuid.uuid4()) if write else None
    headers = _headers(api_key, idem)
    body = _flatten(params or {})

    try:
        if method == "GET":
            resp = await ctx.http.get(url, params=body, headers=headers)
        elif method == "POST":
            resp = await ctx.http.post(url, data=body, headers=headers)
        elif method == "DELETE":
            resp = await ctx.http.delete(url, params=body, headers=headers)
        else:
            raise ValueError(f"Unsupported method {method}")
    except Exception as e:  # noqa: BLE001 -- network-level failure, not a Stripe error
        raise ClientFail(fail(UNREACHABLE, str(e))) from e

    status = resp.status_code
    try:
        payload = resp.json()
    except Exception:  # noqa: BLE001
        payload = {}

    if status == 401:
        raise ClientFail(fail(TOKEN_REJECTED))
    if status == 402:
        err = (payload.get("error") or {})
        raise ClientFail(fail(CARD_DECLINED, err.get("message", "")))
    if status == 403:
        raise ClientFail(fail(PERMISSION_DENIED))
    if status == 404:
        raise ClientFail(fail(NOT_FOUND))
    if status == 429:
        raise ClientFail(fail(RATE_LIMITED))
    if status == 400 or status == 422:
        err = (payload.get("error") or {})
        raise ClientFail(fail(INVALID_REQUEST, err.get("message", "")))
    if status >= 500:
        raise ClientFail(fail(BACKEND_5XX))
    if status not in (200, 201):
        raise ClientFail(fail(BACKEND_5XX, f"unexpected status {status}"))

    return payload


# ── Connection check ────────────────────────────────────────────────────

async def check_key(ctx, api_key: str) -> dict:
    """Validates a key by reading the account's own balance -- the
    lightest read-only call that requires real auth (docs.stripe.com/
    api/balance, confirmed 2026-08-20)."""
    data = await _request(ctx, "GET", api_key, "/balance")
    return {"ok": True, "data": data}


async def get_account(ctx, api_key: str) -> dict:
    return await _request(ctx, "GET", api_key, "/account")


# ── Generic CRUD helpers reused by every resource wrapper below ────────

async def list_resource(ctx, api_key: str, resource: str, params: dict | None = None) -> dict:
    return await _request(ctx, "GET", api_key, f"/{resource}", params or {})


async def get_resource(ctx, api_key: str, resource: str, obj_id: str, params: dict | None = None) -> dict:
    return await _request(ctx, "GET", api_key, f"/{resource}/{obj_id}", params or {})


async def create_resource(ctx, api_key: str, resource: str, params: dict) -> dict:
    return await _request(ctx, "POST", api_key, f"/{resource}", params, write=True)


async def update_resource(ctx, api_key: str, resource: str, obj_id: str, params: dict) -> dict:
    return await _request(ctx, "POST", api_key, f"/{resource}/{obj_id}", params, write=True)


async def delete_resource(ctx, api_key: str, resource: str, obj_id: str) -> dict:
    return await _request(ctx, "DELETE", api_key, f"/{resource}/{obj_id}", write=True)


async def action_resource(ctx, api_key: str, resource: str, obj_id: str, action: str, params: dict | None = None) -> dict:
    """POST /v1/{resource}/{id}/{action} -- e.g. /charges/{id}/capture,
    /subscriptions/{id}/cancel-shaped sub-resource actions."""
    return await _request(ctx, "POST", api_key, f"/{resource}/{obj_id}/{action}", params or {}, write=True)


# ── Named wrappers matching handlers.py's call sites ────────────────────
#
# WHY THESE EXIST ON TOP OF list_resource/get_resource/create_resource/
# update_resource/delete_resource, INSTEAD OF MERGING THEM.
#
# The generic *_resource() helpers above take one bag-of-params dict per
# call. handlers.py's ~85 functions were written against a slightly
# richer, more explicit surface (limit / starting_after / extra kwargs
# for listing; a bare `resource` path segment that can itself contain a
# sub-action like "payment_methods/{id}/attach" for POST-only actions).
# Rather than rewrite 85 call sites, these wrappers adapt the explicit
# surface handlers.py expects onto the generic primitives already tested
# above -- one seam, zero behavioural duplication.


async def list_objects(ctx, api_key: str, resource: str, limit: int = 20,
                        starting_after: str = "", extra: dict | None = None) -> dict:
    params: dict = {"limit": limit}
    if starting_after:
        params["starting_after"] = starting_after
    if extra:
        params.update(extra)
    return await list_resource(ctx, api_key, resource, params)


async def get_object(ctx, api_key: str, resource: str, obj_id: str) -> dict:
    return await get_resource(ctx, api_key, resource, obj_id)


async def create_object(ctx, api_key: str, resource: str, body: dict | None = None) -> dict:
    """`resource` may be a bare collection ('customers') for a true create,
    or a path with a sub-action ('payment_intents/{id}/confirm') for an
    action-style POST -- Stripe uses POST for both shapes identically."""
    return await create_resource(ctx, api_key, resource, body or {})


async def update_object(ctx, api_key: str, resource: str, obj_id: str, body: dict) -> dict:
    return await update_resource(ctx, api_key, resource, obj_id, body)


async def delete_object(ctx, api_key: str, resource: str, obj_id: str) -> dict:
    return await delete_resource(ctx, api_key, resource, obj_id)


async def get_balance(ctx, api_key: str) -> dict:
    return await _request(ctx, "GET", api_key, "/balance")
