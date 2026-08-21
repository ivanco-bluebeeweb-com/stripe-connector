"""Tests for handlers.py -- connection lifecycle, customers, payment
intents, refunds, webhook signature verification, and the Tier-3
revenue report. Mirrors DataForSEO Connector's test_handlers.py shape."""
from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

import handlers as h
from schemas import (
    ConnectStripeParams, DisconnectStripeParams, NoParams,
    ListCustomersParams, CreateCustomerParams, GetCustomerParams,
    UpdateCustomerParams, DeleteCustomerParams,
    CreatePaymentIntentParams, GetPaymentIntentParams,
    CreateRefundParams,
    VerifyWebhookSignatureParams,
    RevenueReportParams,
)


# ── connection lifecycle ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_connect_stripe_rejects_bad_key_shape(ctx):
    result = await h.connect_stripe(ctx, ConnectStripeParams(api_key="not-a-real-key"))
    assert result.error is not None


@pytest.mark.asyncio
async def test_connect_stripe_validates_before_saving(ctx):
    ctx.http.mock_get("/v1/balance", {"error": {"message": "Invalid API Key"}}, status=401)
    result = await h.connect_stripe(ctx, ConnectStripeParams(api_key="sk_test_51ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop"))
    assert result.error is not None
    assert result.error_code == "TOKEN_REJECTED"
    saved = await ctx.secrets.get("stripe_connections")
    assert not saved


@pytest.mark.asyncio
async def test_connect_stripe_saves_on_success(ctx):
    ctx.http.mock_get("/v1/balance", {"object": "balance", "available": [], "pending": []}, status=200)
    result = await h.connect_stripe(ctx, ConnectStripeParams(api_key="sk_test_51ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop", label="My Test Account"))
    assert result.error is None
    saved = json.loads(await ctx.secrets.get("stripe_connections"))
    assert len(saved) == 1
    assert saved[0]["label"] == "My Test Account"
    assert saved[0]["is_test"] is True
    assert saved[0]["api_key"].startswith("sk_test_")


@pytest.mark.asyncio
async def test_list_stripe_connections_empty(ctx):
    result = await h.list_stripe_connections(ctx, NoParams())
    assert result.error is None
    assert result.data["items"] == []


@pytest.mark.asyncio
async def test_list_stripe_connections_shows_connected(ctx_connected):
    result = await h.list_stripe_connections(ctx_connected, NoParams())
    assert result.error is None
    assert len(result.data["items"]) == 1
    assert result.data["items"][0]["detail"] == "test mode"


@pytest.mark.asyncio
async def test_disconnect_stripe_removes_connection(ctx_connected):
    result = await h.disconnect_stripe(ctx_connected, DisconnectStripeParams(connection_id="test-connection-id"))
    assert result.error is None
    remaining = json.loads(await ctx_connected.secrets.get("stripe_connections"))
    assert remaining == []


@pytest.mark.asyncio
async def test_disconnect_stripe_not_found(ctx_connected):
    result = await h.disconnect_stripe(ctx_connected, DisconnectStripeParams(connection_id="nope"))
    assert result.error is not None
    assert result.error_code == "NOT_FOUND"


# ── requires a connection ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_customers_requires_connection(ctx):
    result = await h.list_customers(ctx, ListCustomersParams())
    assert result.error is not None
    assert result.error_code == "NOT_CONNECTED"


# ── customers ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_customer(ctx_connected):
    ctx_connected.http.mock_post("/v1/customers", {
        "id": "cus_ABC123", "object": "customer",
        "email": "jane@example.com", "name": "Jane Doe",
    }, status=200)
    result = await h.create_customer(ctx_connected, CreateCustomerParams(email="jane@example.com", name="Jane Doe"))
    assert result.error is None
    assert result.data["id"] == "cus_ABC123"


@pytest.mark.asyncio
async def test_get_customer(ctx_connected):
    ctx_connected.http.mock_get("/v1/customers/cus_ABC123", {
        "id": "cus_ABC123", "object": "customer", "email": "jane@example.com",
    }, status=200)
    result = await h.get_customer(ctx_connected, GetCustomerParams(customer_id="cus_ABC123"))
    assert result.error is None
    assert result.data["email"] == "jane@example.com"


@pytest.mark.asyncio
async def test_get_customer_not_found(ctx_connected):
    ctx_connected.http.mock_get("/v1/customers/cus_MISSING", {"error": {"message": "No such customer"}}, status=404)
    result = await h.get_customer(ctx_connected, GetCustomerParams(customer_id="cus_MISSING"))
    assert result.error is not None
    assert result.error_code == "NOT_FOUND"


@pytest.mark.asyncio
async def test_delete_customer(ctx_connected):
    ctx_connected.http.mock_post("/v1/customers/cus_ABC123", {"id": "cus_ABC123", "deleted": False}, status=200)
    # delete_customer uses DELETE method
    ctx_connected.http._mocks.append(("DELETE", "/v1/customers/cus_ABC123", {"id": "cus_ABC123", "deleted": True}, 200, {}))
    result = await h.delete_customer(ctx_connected, DeleteCustomerParams(customer_id="cus_ABC123"))
    assert result.error is None


# ── payment intents ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_payment_intent(ctx_connected):
    ctx_connected.http.mock_post("/v1/payment_intents", {
        "id": "pi_ABC123", "object": "payment_intent",
        "amount": 2000, "currency": "usd", "status": "requires_payment_method",
    }, status=200)
    result = await h.create_payment_intent(ctx_connected, CreatePaymentIntentParams(amount=2000, currency="usd"))
    assert result.error is None
    assert result.data["id"] == "pi_ABC123"
    assert result.data["amount"] == 2000


@pytest.mark.asyncio
async def test_create_payment_intent_card_declined(ctx_connected):
    ctx_connected.http.mock_post("/v1/payment_intents", {
        "error": {"message": "Your card was declined.", "code": "card_declined"}
    }, status=402)
    result = await h.create_payment_intent(ctx_connected, CreatePaymentIntentParams(amount=2000, currency="usd"))
    assert result.error is not None
    assert result.error_code == "CARD_DECLINED"


@pytest.mark.asyncio
async def test_get_payment_intent(ctx_connected):
    ctx_connected.http.mock_get("/v1/payment_intents/pi_ABC123", {
        "id": "pi_ABC123", "object": "payment_intent", "amount": 2000,
        "currency": "usd", "status": "succeeded",
    }, status=200)
    result = await h.get_payment_intent(ctx_connected, GetPaymentIntentParams(payment_intent_id="pi_ABC123"))
    assert result.error is None
    assert "succeeded" in result.summary


# ── refunds ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_refund_requires_charge_or_intent(ctx_connected):
    ctx_connected.http.mock_post("/v1/refunds", {
        "id": "re_ABC123", "object": "refund", "amount": 2000, "currency": "usd", "status": "succeeded",
    }, status=200)
    result = await h.create_refund(ctx_connected, CreateRefundParams(charge_id="ch_ABC123"))
    assert result.error is None


# ── webhook signature verification ──────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_webhook_signature_valid(ctx):
    secret = "whsec_test_secret"
    payload = json.dumps({"id": "evt_ABC123", "type": "payment_intent.succeeded"})
    timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.{payload}"
    sig = hmac.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
    header = f"t={timestamp},v1={sig}"

    result = await h.verify_webhook_signature(ctx, VerifyWebhookSignatureParams(
        payload=payload, signature_header=header, webhook_secret=secret,
    ))
    assert result.error is None
    assert result.data["valid"] is True
    assert result.data["event_type"] == "payment_intent.succeeded"


@pytest.mark.asyncio
async def test_verify_webhook_signature_invalid(ctx):
    result = await h.verify_webhook_signature(ctx, VerifyWebhookSignatureParams(
        payload='{"id": "evt_1"}', signature_header="t=123,v1=deadbeef", webhook_secret="whsec_wrong",
    ))
    assert result.error is None  # verification itself always succeeds; validity is in the data
    assert result.data["valid"] is False


@pytest.mark.asyncio
async def test_verify_webhook_signature_malformed_header(ctx):
    result = await h.verify_webhook_signature(ctx, VerifyWebhookSignatureParams(
        payload='{"id": "evt_1"}', signature_header="garbage-not-kv-pairs", webhook_secret="whsec_x",
    ))
    assert result.data["valid"] is False


# ── Tier-3 revenue report ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_revenue_report(ctx_connected):
    ctx_connected.http.mock_get("/v1/charges", {
        "object": "list", "has_more": False,
        "data": [
            {"id": "ch_1", "amount": 5000, "currency": "usd", "paid": True, "amount_refunded": 0},
            {"id": "ch_2", "amount": 3000, "currency": "usd", "paid": False, "amount_refunded": 0},
        ],
    }, status=200)
    ctx_connected.http.mock_get("/v1/subscriptions", {
        "object": "list", "has_more": False,
        "data": [{"id": "sub_1", "items": {"data": [{"price": {"id": "price_1", "unit_amount": 999, "recurring": {"interval": "month"}}}]}}],
    }, status=200)
    ctx_connected.http.mock_get("/v1/disputes", {"object": "list", "has_more": False, "data": []}, status=200)
    ctx_connected.http.mock_get("/v1/invoices", {"object": "list", "has_more": False, "data": []}, status=200)

    result = await h.get_revenue_report(ctx_connected, RevenueReportParams(days=30))
    assert result.error is None
    assert result.data["gross_volume"] == 5000
    assert result.data["successful_charges"] == 1
    assert result.data["failed_charges"] == 1
    assert result.data["active_subscriptions"] == 1
