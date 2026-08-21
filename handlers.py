"""Chat functions for Stripe Connector: connection management, balance,
customers, payment methods, payment intents, charges, refunds, products,
prices, subscriptions, invoices, checkout sessions, payment links,
coupons/promotion codes, disputes, payouts, transfers, balance
transactions, Connect accounts, setup intents, tax rates, webhook
endpoints + signature verification, events, and Tier-3 value-add
(revenue/dunning reporting). Built on stripe_client.py / schemas.py,
following the same shape as MuleSoft Connector's / DataForSEO Connector's
handlers.py.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

from imperal_sdk import ActionResult, sdl

import stripe_client as sc
from app import ext, chat
from schemas import (
    NoParams, ConnectionScopedParams,
    ConnectStripeParams, ProviderConnection, ProviderConnectionList,
    DisconnectStripeParams, DeleteResult,
    StripeBalance, StripeObject, StripeObjectList,
    ListCustomersParams, CreateCustomerParams, UpdateCustomerParams,
    GetCustomerParams, DeleteCustomerParams, StripeCustomer, StripeCustomerList,
    ListPaymentMethodsParams, AttachPaymentMethodParams, DetachPaymentMethodParams,
    SetDefaultPaymentMethodParams,
    ListPaymentIntentsParams, CreatePaymentIntentParams, GetPaymentIntentParams,
    ConfirmPaymentIntentParams, CancelPaymentIntentParams, CapturePaymentIntentParams,
    StripePaymentIntent, StripePaymentIntentList,
    ListChargesParams, GetChargeParams, StripeCharge, StripeChargeList,
    CreateRefundParams, ListRefundsParams, StripeRefund,
    ListProductsParams, CreateProductParams, UpdateProductParams,
    GetProductParams, DeleteProductParams, StripeProduct, StripeProductList,
    ListPricesParams, CreatePriceParams, UpdatePriceParams, GetPriceParams,
    StripePrice, StripePriceList,
    ListSubscriptionsParams, CreateSubscriptionParams, UpdateSubscriptionParams,
    CancelSubscriptionParams, GetSubscriptionParams, StripeSubscription,
    StripeSubscriptionList,
    ListInvoicesParams, CreateInvoiceParams, GetInvoiceParams, FinalizeInvoiceParams,
    PayInvoiceParams, VoidInvoiceParams, SendInvoiceParams, StripeInvoice,
    StripeInvoiceList,
    CreateCheckoutSessionParams, GetCheckoutSessionParams, ListCheckoutSessionsParams,
    ExpireCheckoutSessionParams, StripeCheckoutSession, StripeCheckoutSessionList,
    CreatePaymentLinkParams, ListPaymentLinksParams, UpdatePaymentLinkParams,
    StripePaymentLink, StripePaymentLinkList,
    CreateCouponParams, ListCouponsParams, DeleteCouponParams, StripeCoupon,
    StripeCouponList,
    CreatePromotionCodeParams, ListPromotionCodesParams, UpdatePromotionCodeParams,
    StripePromotionCode, StripePromotionCodeList,
    ListDisputesParams, GetDisputeParams, UpdateDisputeParams, StripeDispute,
    StripeDisputeList,
    ListPayoutsParams, GetPayoutParams, CreatePayoutParams, CancelPayoutParams,
    StripePayout, StripePayoutList,
    ListTransfersParams, CreateTransferParams, GetTransferParams, StripeTransfer,
    StripeTransferList,
    ListBalanceTransactionsParams, StripeBalanceTransaction, StripeBalanceTransactionList,
    ListConnectedAccountsParams, CreateConnectedAccountParams, GetConnectedAccountParams,
    DeleteConnectedAccountParams, CreateAccountLinkParams, StripeConnectedAccount,
    StripeConnectedAccountList, AccountLinkResult,
    CreateSetupIntentParams, GetSetupIntentParams, ListSetupIntentsParams,
    StripeSetupIntent, StripeSetupIntentList,
    CreateTaxRateParams, ListTaxRatesParams, StripeTaxRate, StripeTaxRateList,
    ListWebhookEndpointsParams, CreateWebhookEndpointParams, UpdateWebhookEndpointParams,
    DeleteWebhookEndpointParams, StripeWebhookEndpoint, StripeWebhookEndpointList,
    VerifyWebhookSignatureParams, WebhookVerifyResult,
    ListEventsParams, StripeEvent, StripeEventList, GetEventParams,
    RevenueReportParams, RevenueReportRow, RevenueReport,
    DunningReportParams, DunningInvoiceRow, DunningReport,
)

_SECRET_NAME = "stripe_connections"


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


async def _get_connections(ctx) -> list[dict]:
    raw = await ctx.secrets.get(_SECRET_NAME)
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return []
    return data if isinstance(data, list) else []


async def _save_connections(ctx, connections: list[dict]) -> None:
    await ctx.secrets.set(_SECRET_NAME, json.dumps(connections))


async def _resolve_key(ctx, connection_id: str = "") -> tuple[str, dict] | None:
    """Resolve a connection_id (or the sole/first connection) to its api_key.
    Returns (api_key, connection_dict) or None if not found."""
    connections = await _get_connections(ctx)
    if not connections:
        return None
    if connection_id:
        for c in connections:
            if c.get("id") == connection_id:
                return c.get("api_key", ""), c
        return None
    return connections[0].get("api_key", ""), connections[0]


def _err(e: sc.ClientFail) -> ActionResult:
    payload = e.payload
    return ActionResult.error(
        payload.get("error", str(e)),
        payload.get("retryable", False),
        code=payload.get("error_code", "UNKNOWN"),
    )


# ──────────────────────────────────────────────────────────────────────────
# Connection
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "connect_stripe",
    "Connect your own Stripe account by saving your Secret Key or Restricted Key, after checking it actually works. Get a key from Stripe Dashboard > Developers > API keys. A Restricted Key scoped to just what you need is recommended over the full Secret Key.",
    action_type="write",
    effects=["stripe.provider.connected"],
    event="stripe-connector.connect_stripe",
    data_model=ProviderConnection,
)
async def connect_stripe(ctx, params: ConnectStripeParams) -> ActionResult:
    """Connect your own Stripe account by saving your Secret Key or
    Restricted Key, after checking it actually works. Get a key from
    Stripe Dashboard > Developers > API keys. A Restricted Key scoped to
    just what you need is recommended over the full Secret Key."""
    if not sc.is_valid_key_shape(params.api_key):
        return ActionResult.error(
            "That doesn't look like a Stripe key. Expected it to start with sk_test_, sk_live_, rk_test_, or rk_live_.",
            code="VALIDATION_MISSING_FIELD",
        )
    try:
        result = await sc.check_key(ctx, params.api_key)
    except sc.ClientFail as e:
        return _err(e)

    connections = await _get_connections(ctx)
    is_test = sc.is_test_key(params.api_key)
    label = params.label or ("Stripe (test mode)" if is_test else "Stripe (live mode)")
    conn = {
        "id": str(uuid.uuid4()),
        "label": label,
        "api_key": params.api_key,
        "is_test": is_test,
        "connected_at": _now_iso(),
    }
    connections.append(conn)
    await _save_connections(ctx, connections)
    return ActionResult.success(
        data=ProviderConnection(id=conn["id"], title=label, connected=True, detail="Test mode" if is_test else "Live mode"),
        summary=f"Connected {label}.",
        refresh_panels=["sidebar"],
    )


@chat.function(
    "disconnect_stripe",
    "Disconnect and remove a saved Stripe connection.",
    action_type="destructive",
    effects=["stripe.provider.disconnected"],
    event="stripe-connector.disconnect_stripe",
    data_model=DeleteResult,
)
async def disconnect_stripe(ctx, params: DisconnectStripeParams) -> ActionResult:
    """Disconnect and remove a saved Stripe connection."""
    connections = await _get_connections(ctx)
    remaining = [c for c in connections if c.get("id") != params.connection_id]
    if len(remaining) == len(connections):
        return ActionResult.error("Connection not found.", code="NOT_FOUND")
    await _save_connections(ctx, remaining)
    return ActionResult.success(
        data=DeleteResult(deleted=True, id=params.connection_id).model_dump(),
        summary="Disconnected Stripe account.",
        refresh_panels=["sidebar", "settings"],
    )


@chat.function(
    "list_stripe_connections",
    "List all connected Stripe accounts (sandbox/live shown per connection).",
    action_type="read",
    data_model=ProviderConnectionList,
)
async def list_stripe_connections(ctx, params: NoParams) -> ActionResult:
    """List all connected Stripe accounts (sandbox/live shown per connection)."""
    connections = await _get_connections(ctx)
    items = [
        ProviderConnection(
            id=c.get("id", ""), title=c.get("label") or c.get("id", ""),
            connected=True, detail=("test mode" if c.get("is_test") else "live mode"),
        )
        for c in connections
    ]
    return ActionResult.success(
        data=ProviderConnectionList(items=items, total=len(items)).model_dump(),
        summary=f"{len(items)} Stripe connection(s).",
    )


@chat.function(
    "get_balance",
    "Get the current Stripe account balance (available + pending, per currency).",
    action_type="read",
    data_model=StripeBalance,
)
async def get_balance(ctx, params: ConnectionScopedParams) -> ActionResult:
    """Get the current Stripe account balance (available + pending, per currency)."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.get_balance(ctx, api_key)
    except sc.ClientFail as e:
        return _err(e)
    available = data.get("available", [{}])
    pending = data.get("pending", [{}])
    bal = StripeBalance(
        available_amount=available[0].get("amount", 0) if available else 0,
        available_currency=available[0].get("currency", "") if available else "",
        pending_amount=pending[0].get("amount", 0) if pending else 0,
        pending_currency=pending[0].get("currency", "") if pending else "",
    )
    return ActionResult.success(data=bal.model_dump(), summary=f"Available: {bal.available_amount/100:.2f} {bal.available_currency.upper()}")


# ──────────────────────────────────────────────────────────────────────────
# Customers
# ──────────────────────────────────────────────────────────────────────────


def _to_customer(o: dict) -> StripeCustomer:
    return StripeCustomer(
        id=o.get("id", ""), title=o.get("name") or o.get("email") or o.get("id", ""),
        email=o.get("email") or "", name=o.get("name") or "", phone=o.get("phone") or "",
        balance=o.get("balance", 0), currency=o.get("currency") or "",
        delinquent=bool(o.get("delinquent")), created=o.get("created", 0),
        livemode=bool(o.get("livemode")),
    )


@chat.function(
    "list_customers",
    "List customers in your Stripe account, optionally filtered by email.",
    action_type="read",
    data_model=StripeCustomerList,
)
async def list_customers(ctx, params: ListCustomersParams) -> ActionResult:
    """List customers in your Stripe account, optionally filtered by email."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.list_objects(ctx, api_key, "customers", limit=params.limit, starting_after=params.starting_after, extra={"email": params.email} if params.email else None)
    except sc.ClientFail as e:
        return _err(e)
    items = [_to_customer(o) for o in data.get("data", [])]
    return ActionResult.success(
        data=StripeCustomerList(items=items, total=len(items), has_more=data.get("has_more", False)).model_dump(),
        summary=f"{len(items)} customer(s).",
    )


@chat.function(
    "create_customer",
    "Create a new customer in Stripe.",
    action_type="write",
    effects=["stripe.customer.created"],
    event="stripe-connector.create_customer",
    data_model=StripeCustomer,
)
async def create_customer(ctx, params: CreateCustomerParams) -> ActionResult:
    """Create a new customer in Stripe."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {"email": params.email, "name": params.name, "description": params.description, "phone": params.phone, "metadata": params.metadata}
    try:
        data = await sc.create_object(ctx, api_key, "customers", body)
    except sc.ClientFail as e:
        return _err(e)
    c = _to_customer(data)
    return ActionResult.success(data=c.model_dump(), summary=f"Created customer {c.title}.", refresh_panels=["sidebar"])


@chat.function(
    "update_customer",
    "Update an existing customer's email, name, description, phone or metadata.",
    action_type="write",
    effects=["stripe.customer.updated"],
    event="stripe-connector.update_customer",
    data_model=StripeCustomer,
)
async def update_customer(ctx, params: UpdateCustomerParams) -> ActionResult:
    """Update an existing customer's email, name, description, phone or metadata."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {k: v for k, v in {
        "email": params.email, "name": params.name, "description": params.description,
        "phone": params.phone, "metadata": params.metadata or None,
    }.items() if v}
    try:
        data = await sc.update_object(ctx, api_key, "customers", params.customer_id, body)
    except sc.ClientFail as e:
        return _err(e)
    c = _to_customer(data)
    return ActionResult.success(data=c.model_dump(), summary=f"Updated customer {c.title}.", refresh_panels=["sidebar"])


@chat.function(
    "get_customer",
    "Get a single customer by id.",
    action_type="read",
    data_model=StripeCustomer,
)
async def get_customer(ctx, params: GetCustomerParams) -> ActionResult:
    """Get a single customer by id."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.get_object(ctx, api_key, "customers", params.customer_id)
    except sc.ClientFail as e:
        return _err(e)
    c = _to_customer(data)
    return ActionResult.success(data=c.model_dump(), summary=f"Customer {c.title}.")


@chat.function(
    "delete_customer",
    "Permanently delete a customer. This cannot be undone.",
    action_type="destructive",
    effects=["stripe.customer.deleted"],
    event="stripe-connector.delete_customer",
    data_model=DeleteResult,
)
async def delete_customer(ctx, params: DeleteCustomerParams) -> ActionResult:
    """Permanently delete a customer. This cannot be undone."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        await sc.delete_object(ctx, api_key, "customers", params.customer_id)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=DeleteResult(deleted=True, id=params.customer_id).model_dump(), summary="Customer deleted.", refresh_panels=["sidebar"])


# ──────────────────────────────────────────────────────────────────────────
# Payment Methods
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "list_payment_methods",
    "List saved payment methods for a customer (requires customer_id via extra params on the client side; pass through query).",
    action_type="read",
    data_model=StripeObjectList,
)
async def list_payment_methods(ctx, params: ListPaymentMethodsParams) -> ActionResult:
    """List saved payment methods for a customer (requires customer_id via extra params on the client side; pass through query)."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.list_objects(ctx, api_key, "payment_methods", limit=params.limit, starting_after=params.starting_after)
    except sc.ClientFail as e:
        return _err(e)
    items = [StripeObject(id=o.get("id", ""), title=o.get("type", o.get("id", "")), raw=o) for o in data.get("data", [])]
    return ActionResult.success(data=StripeObjectList(items=items, total=len(items), has_more=data.get("has_more", False)).model_dump(), summary=f"{len(items)} payment method(s).")


@chat.function(
    "attach_payment_method",
    "Attach a payment method to a customer.",
    action_type="write",
    effects=["stripe.payment_method.attached"],
    event="stripe-connector.attach_payment_method",
    data_model=StripeObject,
)
async def attach_payment_method(ctx, params: AttachPaymentMethodParams) -> ActionResult:
    """Attach a payment method to a customer."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.create_object(ctx, api_key, f"payment_methods/{params.payment_method_id}/attach", {"customer": params.customer_id})
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=StripeObject(id=data.get("id", ""), title=data.get("type", ""), raw=data).model_dump(), summary="Payment method attached.")


@chat.function(
    "detach_payment_method",
    "Detach a payment method from its customer.",
    action_type="write",
    effects=["stripe.payment_method.detached"],
    event="stripe-connector.detach_payment_method",
    data_model=StripeObject,
)
async def detach_payment_method(ctx, params: DetachPaymentMethodParams) -> ActionResult:
    """Detach a payment method from its customer."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.create_object(ctx, api_key, f"payment_methods/{params.payment_method_id}/detach", {})
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=StripeObject(id=data.get("id", ""), title=data.get("type", ""), raw=data).model_dump(), summary="Payment method detached.")


@chat.function(
    "set_default_payment_method",
    "Set a customer's default payment method for invoices/subscriptions.",
    action_type="write",
    effects=["stripe.payment_method.set_default"],
    event="stripe-connector.set_default_payment_method",
    data_model=StripeCustomer,
)
async def set_default_payment_method(ctx, params: SetDefaultPaymentMethodParams) -> ActionResult:
    """Set a customer's default payment method for invoices/subscriptions."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.update_object(ctx, api_key, "customers", params.customer_id, {"invoice_settings[default_payment_method]": params.payment_method_id})
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_customer(data).model_dump(), summary="Default payment method set.")


# ──────────────────────────────────────────────────────────────────────────
# Payment Intents
# ──────────────────────────────────────────────────────────────────────────


def _to_pi(o: dict) -> StripePaymentIntent:
    return StripePaymentIntent(
        id=o.get("id", ""), title=f"{(o.get('amount', 0) or 0)/100:.2f} {str(o.get('currency', '')).upper()}",
        status=o.get("status"), amount=o.get("amount", 0), currency=o.get("currency", ""),
        customer_id=o.get("customer"), created=o.get("created", 0),
        client_secret=o.get("client_secret"),
    )


@chat.function(
    "list_payment_intents",
    "List payment intents, optionally filtered by customer.",
    action_type="read",
    data_model=StripePaymentIntentList,
)
async def list_payment_intents(ctx, params: ListPaymentIntentsParams) -> ActionResult:
    """List payment intents, optionally filtered by customer."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.list_objects(ctx, api_key, "payment_intents", limit=params.limit, starting_after=params.starting_after, extra={"customer": params.customer_id} if params.customer_id else None)
    except sc.ClientFail as e:
        return _err(e)
    items = [_to_pi(o) for o in data.get("data", [])]
    return ActionResult.success(data=StripePaymentIntentList(items=items, total=len(items), has_more=data.get("has_more", False)).model_dump(), summary=f"{len(items)} payment intent(s).")


@chat.function(
    "create_payment_intent",
    "Create a payment intent -- the core object for collecting a one-time payment.",
    action_type="write",
    effects=["stripe.payment_intent.created"],
    event="stripe-connector.create_payment_intent",
    data_model=StripePaymentIntent,
)
async def create_payment_intent(ctx, params: CreatePaymentIntentParams) -> ActionResult:
    """Create a payment intent -- the core object for collecting a one-time payment."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {
        "amount": params.amount, "currency": params.currency,
        "customer": params.customer_id or None,
        "description": params.description or None,
        "payment_method": params.payment_method_id or None,
        "confirm": params.confirm,
        "metadata": params.metadata,
    }
    try:
        data = await sc.create_object(ctx, api_key, "payment_intents", body)
    except sc.ClientFail as e:
        return _err(e)
    pi = _to_pi(data)
    return ActionResult.success(data=pi.model_dump(), summary=f"Created payment intent for {pi.title} (status: {pi.status}).", refresh_panels=["sidebar"])


@chat.function(
    "get_payment_intent",
    "Get a single payment intent by id.",
    action_type="read",
    data_model=StripePaymentIntent,
)
async def get_payment_intent(ctx, params: GetPaymentIntentParams) -> ActionResult:
    """Get a single payment intent by id."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.get_object(ctx, api_key, "payment_intents", params.payment_intent_id)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_pi(data).model_dump(), summary=f"Payment intent status: {data.get('status')}.")


@chat.function(
    "confirm_payment_intent",
    "Confirm a payment intent to attempt the actual charge.",
    action_type="write",
    effects=["stripe.payment_intent.confirmed"],
    event="stripe-connector.confirm_payment_intent",
    data_model=StripePaymentIntent,
)
async def confirm_payment_intent(ctx, params: ConfirmPaymentIntentParams) -> ActionResult:
    """Confirm a payment intent to attempt the actual charge."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {"payment_method": params.payment_method_id} if params.payment_method_id else {}
    try:
        data = await sc.create_object(ctx, api_key, f"payment_intents/{params.payment_intent_id}/confirm", body)
    except sc.ClientFail as e:
        return _err(e)
    pi = _to_pi(data)
    return ActionResult.success(data=pi.model_dump(), summary=f"Payment intent confirmed (status: {pi.status}).", refresh_panels=["sidebar"])


@chat.function(
    "cancel_payment_intent",
    "Cancel a payment intent that hasn't succeeded yet.",
    action_type="write",
    effects=["stripe.payment_intent.canceled"],
    event="stripe-connector.cancel_payment_intent",
    data_model=StripePaymentIntent,
)
async def cancel_payment_intent(ctx, params: CancelPaymentIntentParams) -> ActionResult:
    """Cancel a payment intent that hasn't succeeded yet."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.create_object(ctx, api_key, f"payment_intents/{params.payment_intent_id}/cancel", {})
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_pi(data).model_dump(), summary="Payment intent cancelled.", refresh_panels=["sidebar"])


@chat.function(
    "capture_payment_intent",
    "Capture funds for a payment intent previously authorized with manual capture.",
    action_type="write",
    effects=["stripe.payment_intent.captured"],
    event="stripe-connector.capture_payment_intent",
    data_model=StripePaymentIntent,
)
async def capture_payment_intent(ctx, params: CapturePaymentIntentParams) -> ActionResult:
    """Capture funds for a payment intent previously authorized with manual capture."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {"amount_to_capture": params.amount_to_capture} if params.amount_to_capture else {}
    try:
        data = await sc.create_object(ctx, api_key, f"payment_intents/{params.payment_intent_id}/capture", body)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_pi(data).model_dump(), summary="Payment captured.", refresh_panels=["sidebar"])


# ──────────────────────────────────────────────────────────────────────────
# Charges / Refunds
# ──────────────────────────────────────────────────────────────────────────


def _to_charge(o: dict) -> StripeCharge:
    return StripeCharge(
        id=o.get("id", ""), title=f"{(o.get('amount', 0) or 0)/100:.2f} {str(o.get('currency', '')).upper()}",
        amount=o.get("amount", 0), currency=o.get("currency", ""), status=o.get("status"),
        paid=bool(o.get("paid")), refunded=bool(o.get("refunded")),
        customer_id=o.get("customer"), created=o.get("created", 0),
        receipt_url=o.get("receipt_url"),
    )


@chat.function(
    "list_charges",
    "List charges, optionally filtered by customer.",
    action_type="read",
    data_model=StripeChargeList,
)
async def list_charges(ctx, params: ListChargesParams) -> ActionResult:
    """List charges, optionally filtered by customer."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.list_objects(ctx, api_key, "charges", limit=params.limit, starting_after=params.starting_after, extra={"customer": params.customer_id} if params.customer_id else None)
    except sc.ClientFail as e:
        return _err(e)
    items = [_to_charge(o) for o in data.get("data", [])]
    return ActionResult.success(data=StripeChargeList(items=items, total=len(items), has_more=data.get("has_more", False)).model_dump(), summary=f"{len(items)} charge(s).")


@chat.function(
    "get_charge",
    "Get a single charge by id.",
    action_type="read",
    data_model=StripeCharge,
)
async def get_charge(ctx, params: GetChargeParams) -> ActionResult:
    """Get a single charge by id."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.get_object(ctx, api_key, "charges", params.charge_id)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_charge(data).model_dump(), summary=f"Charge status: {data.get('status')}.")


@chat.function(
    "create_refund",
    "Refund a charge or payment intent, fully or partially.",
    action_type="write",
    effects=["stripe.refund.created"],
    event="stripe-connector.create_refund",
    data_model=StripeRefund,
)
async def create_refund(ctx, params: CreateRefundParams) -> ActionResult:
    """Refund a charge or payment intent, fully or partially."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {}
    if params.charge_id:
        body["charge"] = params.charge_id
    if params.payment_intent_id:
        body["payment_intent"] = params.payment_intent_id
    if params.amount:
        body["amount"] = params.amount
    if params.reason:
        body["reason"] = params.reason
    try:
        data = await sc.create_object(ctx, api_key, "refunds", body)
    except sc.ClientFail as e:
        return _err(e)
    r = StripeRefund(id=data.get("id", ""), title=f"{(data.get('amount', 0) or 0)/100:.2f} {str(data.get('currency', '')).upper()}", amount=data.get("amount", 0), currency=data.get("currency", ""), status=data.get("status"), charge_id=data.get("charge"), created=data.get("created", 0))
    return ActionResult.success(data=r.model_dump(), summary=f"Refund created (status: {r.status}).", refresh_panels=["sidebar"])


@chat.function(
    "list_refunds",
    "List refunds on this Stripe account, optionally paginated with limit/starting_after.",
    action_type="read",
    data_model=StripeRefund,
)
async def list_refunds(ctx, params: ListRefundsParams) -> ActionResult:
    """List refunds."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.list_objects(ctx, api_key, "refunds", limit=params.limit, starting_after=params.starting_after)
    except sc.ClientFail as e:
        return _err(e)
    items = [StripeRefund(id=o.get("id", ""), title=f"{(o.get('amount', 0) or 0)/100:.2f} {str(o.get('currency', '')).upper()}", amount=o.get("amount", 0), currency=o.get("currency", ""), status=o.get("status"), charge_id=o.get("charge"), created=o.get("created", 0)) for o in data.get("data", [])]
    return ActionResult.success(data={"items": [i.model_dump() for i in items], "total": len(items)}, summary=f"{len(items)} refund(s).")


# ──────────────────────────────────────────────────────────────────────────
# Products
# ──────────────────────────────────────────────────────────────────────────


def _to_product(o: dict) -> StripeProduct:
    return StripeProduct(id=o.get("id", ""), title=o.get("name", o.get("id", "")), description=o.get("description"), active=bool(o.get("active", True)), created=o.get("created", 0))


@chat.function(
    "list_products",
    "List products in your Stripe catalog.",
    action_type="read",
    data_model=StripeProductList,
)
async def list_products(ctx, params: ListProductsParams) -> ActionResult:
    """List products in your Stripe catalog."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    extra = {}
    if params.active is not None:
        extra["active"] = "true" if params.active else "false"
    try:
        data = await sc.list_objects(ctx, api_key, "products", limit=params.limit, starting_after=params.starting_after, extra=extra or None)
    except sc.ClientFail as e:
        return _err(e)
    items = [_to_product(o) for o in data.get("data", [])]
    return ActionResult.success(data=StripeProductList(items=items, total=len(items), has_more=data.get("has_more", False)).model_dump(), summary=f"{len(items)} product(s).")


@chat.function(
    "create_product",
    "Create a new product in your Stripe catalog.",
    action_type="write",
    effects=["stripe.product.created"],
    event="stripe-connector.create_product",
    data_model=StripeProduct,
)
async def create_product(ctx, params: CreateProductParams) -> ActionResult:
    """Create a new product in your Stripe catalog."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {"name": params.name, "description": params.description or None, "active": params.active, "metadata": params.metadata}
    try:
        data = await sc.create_object(ctx, api_key, "products", body)
    except sc.ClientFail as e:
        return _err(e)
    p = _to_product(data)
    return ActionResult.success(data=p.model_dump(), summary=f"Created product {p.title}.", refresh_panels=["sidebar"])


@chat.function(
    "update_product",
    "Update a product's name, description, or active status.",
    action_type="write",
    effects=["stripe.product.updated"],
    event="stripe-connector.update_product",
    data_model=StripeProduct,
)
async def update_product(ctx, params: UpdateProductParams) -> ActionResult:
    """Update a product's name, description, or active status."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {}
    if params.name:
        body["name"] = params.name
    if params.description:
        body["description"] = params.description
    if params.active is not None:
        body["active"] = params.active
    try:
        data = await sc.update_object(ctx, api_key, "products", params.product_id, body)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_product(data).model_dump(), summary="Product updated.", refresh_panels=["sidebar"])


@chat.function(
    "get_product",
    "Get a single product by id.",
    action_type="read",
    data_model=StripeProduct,
)
async def get_product(ctx, params: GetProductParams) -> ActionResult:
    """Get a single product by id."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.get_object(ctx, api_key, "products", params.product_id)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_product(data).model_dump(), summary=f"Product: {data.get('name')}.")


@chat.function(
    "delete_product",
    "Permanently delete a product (must have no active prices).",
    action_type="destructive",
    effects=["stripe.product.deleted"],
    event="stripe-connector.delete_product",
    data_model=DeleteResult,
)
async def delete_product(ctx, params: DeleteProductParams) -> ActionResult:
    """Permanently delete a product (must have no active prices)."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        await sc.delete_object(ctx, api_key, "products", params.product_id)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=DeleteResult(deleted=True, id=params.product_id).model_dump(), summary="Product deleted.", refresh_panels=["sidebar"])


# ──────────────────────────────────────────────────────────────────────────
# Prices
# ──────────────────────────────────────────────────────────────────────────


def _to_price(o: dict) -> StripePrice:
    recurring = o.get("recurring") or {}
    return StripePrice(
        id=o.get("id", ""), title=f"{(o.get('unit_amount', 0) or 0)/100:.2f} {str(o.get('currency', '')).upper()}",
        product_id=o.get("product", ""), unit_amount=o.get("unit_amount"), currency=o.get("currency", ""),
        active=bool(o.get("active", True)), recurring_interval=recurring.get("interval"),
        created=o.get("created", 0),
    )


@chat.function(
    "list_prices",
    "List prices, optionally filtered by product or active status.",
    action_type="read",
    data_model=StripePriceList,
)
async def list_prices(ctx, params: ListPricesParams) -> ActionResult:
    """List prices, optionally filtered by product or active status."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    extra = {}
    if params.product_id:
        extra["product"] = params.product_id
    if params.active is not None:
        extra["active"] = "true" if params.active else "false"
    try:
        data = await sc.list_objects(ctx, api_key, "prices", limit=params.limit, starting_after=params.starting_after, extra=extra or None)
    except sc.ClientFail as e:
        return _err(e)
    items = [_to_price(o) for o in data.get("data", [])]
    return ActionResult.success(data=StripePriceList(items=items, total=len(items), has_more=data.get("has_more", False)).model_dump(), summary=f"{len(items)} price(s).")


@chat.function(
    "create_price",
    "Create a new price for a product -- one-time or recurring (subscription).",
    action_type="write",
    effects=["stripe.price.created"],
    event="stripe-connector.create_price",
    data_model=StripePrice,
)
async def create_price(ctx, params: CreatePriceParams) -> ActionResult:
    """Create a new price for a product -- one-time or recurring (subscription)."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {"product": params.product_id, "unit_amount": params.unit_amount, "currency": params.currency}
    if params.recurring_interval:
        body["recurring[interval]"] = params.recurring_interval
    try:
        data = await sc.create_object(ctx, api_key, "prices", body)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_price(data).model_dump(), summary="Price created.", refresh_panels=["sidebar"])


@chat.function(
    "update_price",
    "Update a price's active status or metadata. Note: unit_amount cannot be changed on an existing price -- create a new one instead.",
    action_type="write",
    effects=["stripe.price.updated"],
    event="stripe-connector.update_price",
    data_model=StripePrice,
)
async def update_price(ctx, params: UpdatePriceParams) -> ActionResult:
    """Update a price's active status or metadata. Note: unit_amount cannot be changed on an existing price -- create a new one instead."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {}
    if params.active is not None:
        body["active"] = params.active
    try:
        data = await sc.update_object(ctx, api_key, "prices", params.price_id, body)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_price(data).model_dump(), summary="Price updated.", refresh_panels=["sidebar"])


@chat.function(
    "get_price",
    "Get a single price by id.",
    action_type="read",
    data_model=StripePrice,
)
async def get_price(ctx, params: GetPriceParams) -> ActionResult:
    """Get a single price by id."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.get_object(ctx, api_key, "prices", params.price_id)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_price(data).model_dump(), summary="Price details.")


# ──────────────────────────────────────────────────────────────────────────
# Subscriptions
# ──────────────────────────────────────────────────────────────────────────


def _to_subscription(o: dict) -> StripeSubscription:
    items = (o.get("items") or {}).get("data") or []
    price_id = items[0].get("price", {}).get("id", "") if items else ""
    return StripeSubscription(
        id=o.get("id", ""), title=f"Subscription {o.get('id', '')}",
        status=o.get("status"), customer_id=o.get("customer"),
        price_id=price_id, current_period_end=o.get("current_period_end"),
        cancel_at_period_end=bool(o.get("cancel_at_period_end")),
        created=o.get("created", 0),
    )


@chat.function(
    "list_subscriptions",
    "List subscriptions, optionally filtered by customer or status.",
    action_type="read",
    data_model=StripeSubscriptionList,
)
async def list_subscriptions(ctx, params: ListSubscriptionsParams) -> ActionResult:
    """List subscriptions, optionally filtered by customer or status."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    extra = {}
    if params.customer_id:
        extra["customer"] = params.customer_id
    if params.status:
        extra["status"] = params.status
    try:
        data = await sc.list_objects(ctx, api_key, "subscriptions", limit=params.limit, starting_after=params.starting_after, extra=extra or None)
    except sc.ClientFail as e:
        return _err(e)
    items = [_to_subscription(o) for o in data.get("data", [])]
    return ActionResult.success(data=StripeSubscriptionList(items=items, total=len(items), has_more=data.get("has_more", False)).model_dump(), summary=f"{len(items)} subscription(s).")


@chat.function(
    "create_subscription",
    "Create a new subscription for a customer on a given price.",
    action_type="write",
    effects=["stripe.subscription.created"],
    event="stripe-connector.create_subscription",
    data_model=StripeSubscription,
)
async def create_subscription(ctx, params: CreateSubscriptionParams) -> ActionResult:
    """Create a new subscription for a customer on a given price."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {"customer": params.customer_id, "items[0][price]": params.price_id}
    if params.trial_period_days:
        body["trial_period_days"] = params.trial_period_days
    try:
        data = await sc.create_object(ctx, api_key, "subscriptions", body)
    except sc.ClientFail as e:
        return _err(e)
    sub = _to_subscription(data)
    return ActionResult.success(data=sub.model_dump(), summary=f"Created subscription (status: {sub.status}).", refresh_panels=["sidebar"])


@chat.function(
    "update_subscription",
    "Change an existing subscription's price (upgrade/downgrade) or cancel-at-period-end flag.",
    action_type="write",
    effects=["stripe.subscription.updated"],
    event="stripe-connector.update_subscription",
    data_model=StripeSubscription,
)
async def update_subscription(ctx, params: UpdateSubscriptionParams) -> ActionResult:
    """Change an existing subscription's price (upgrade/downgrade) or cancel-at-period-end flag."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {}
    if params.price_id:
        try:
            current = await sc.get_object(ctx, api_key, "subscriptions", params.subscription_id)
        except sc.ClientFail as e:
            return _err(e)
        items = (current.get("items") or {}).get("data") or []
        if items:
            body["items[0][id]"] = items[0].get("id", "")
            body["items[0][price]"] = params.price_id
    if params.cancel_at_period_end is not None:
        body["cancel_at_period_end"] = params.cancel_at_period_end
    try:
        data = await sc.update_object(ctx, api_key, "subscriptions", params.subscription_id, body)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_subscription(data).model_dump(), summary="Subscription updated.", refresh_panels=["sidebar"])


@chat.function(
    "cancel_subscription",
    "Cancel a subscription immediately (or let it lapse -- use update_subscription's cancel_at_period_end for that instead).",
    action_type="write",
    effects=["stripe.subscription.canceled"],
    event="stripe-connector.cancel_subscription",
    data_model=StripeSubscription,
)
async def cancel_subscription(ctx, params: CancelSubscriptionParams) -> ActionResult:
    """Cancel a subscription immediately (or let it lapse -- use update_subscription's cancel_at_period_end for that instead)."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.delete_object(ctx, api_key, "subscriptions", params.subscription_id)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_subscription(data).model_dump(), summary="Subscription cancelled.", refresh_panels=["sidebar"])


@chat.function(
    "get_subscription",
    "Get a single subscription by id.",
    action_type="read",
    data_model=StripeSubscription,
)
async def get_subscription(ctx, params: GetSubscriptionParams) -> ActionResult:
    """Get a single subscription by id."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.get_object(ctx, api_key, "subscriptions", params.subscription_id)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_subscription(data).model_dump(), summary=f"Subscription status: {data.get('status')}.")


# ──────────────────────────────────────────────────────────────────────────
# Invoices
# ──────────────────────────────────────────────────────────────────────────


def _to_invoice(o: dict) -> StripeInvoice:
    return StripeInvoice(
        id=o.get("id", ""), title=f"Invoice {o.get('number') or o.get('id', '')}",
        status=o.get("status"), customer_id=o.get("customer", ""),
        amount_due=o.get("amount_due", 0), amount_paid=o.get("amount_paid", 0),
        currency=o.get("currency", ""), created=o.get("created", 0),
        hosted_invoice_url=o.get("hosted_invoice_url"),
    )


@chat.function(
    "list_invoices",
    "List invoices, optionally filtered by customer or status.",
    action_type="read",
    data_model=StripeInvoiceList,
)
async def list_invoices(ctx, params: ListInvoicesParams) -> ActionResult:
    """List invoices, optionally filtered by customer or status."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    extra = {}
    if params.customer_id:
        extra["customer"] = params.customer_id
    if params.status:
        extra["status"] = params.status
    try:
        data = await sc.list_objects(ctx, api_key, "invoices", limit=params.limit, starting_after=params.starting_after, extra=extra or None)
    except sc.ClientFail as e:
        return _err(e)
    items = [_to_invoice(o) for o in data.get("data", [])]
    return ActionResult.success(data=StripeInvoiceList(items=items, total=len(items), has_more=data.get("has_more", False)).model_dump(), summary=f"{len(items)} invoice(s).")


@chat.function(
    "create_invoice",
    "Create a draft invoice for a customer. Add invoice items separately, then finalize/pay.",
    action_type="write",
    effects=["stripe.invoice.created"],
    event="stripe-connector.create_invoice",
    data_model=StripeInvoice,
)
async def create_invoice(ctx, params: CreateInvoiceParams) -> ActionResult:
    """Create a draft invoice for a customer. Add invoice items separately, then finalize/pay."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {"customer": params.customer_id, "auto_advance": params.auto_advance, "description": params.description or None}
    try:
        data = await sc.create_object(ctx, api_key, "invoices", body)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_invoice(data).model_dump(), summary="Draft invoice created.", refresh_panels=["sidebar"])


@chat.function(
    "get_invoice",
    "Get a single invoice by id.",
    action_type="read",
    data_model=StripeInvoice,
)
async def get_invoice(ctx, params: GetInvoiceParams) -> ActionResult:
    """Get a single invoice by id."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.get_object(ctx, api_key, "invoices", params.invoice_id)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_invoice(data).model_dump(), summary=f"Invoice status: {data.get('status')}.")


@chat.function(
    "finalize_invoice",
    "Finalize a draft invoice, moving it from draft to open (ready to be paid).",
    action_type="write",
    effects=["stripe.invoice.finalized"],
    event="stripe-connector.finalize_invoice",
    data_model=StripeInvoice,
)
async def finalize_invoice(ctx, params: FinalizeInvoiceParams) -> ActionResult:
    """Finalize a draft invoice, moving it from draft to open (ready to be paid)."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.create_object(ctx, api_key, f"invoices/{params.invoice_id}/finalize", {})
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_invoice(data).model_dump(), summary="Invoice finalized.", refresh_panels=["sidebar"])


@chat.function(
    "pay_invoice",
    "Attempt to collect payment on an open invoice right now.",
    action_type="write",
    effects=["stripe.invoice.paid"],
    event="stripe-connector.pay_invoice",
    data_model=StripeInvoice,
)
async def pay_invoice(ctx, params: PayInvoiceParams) -> ActionResult:
    """Attempt to collect payment on an open invoice right now."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.create_object(ctx, api_key, f"invoices/{params.invoice_id}/pay", {})
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_invoice(data).model_dump(), summary=f"Invoice payment attempted (status: {data.get('status')}).", refresh_panels=["sidebar"])


@chat.function(
    "void_invoice",
    "Void an invoice (draft or open) -- it will never be paid.",
    action_type="write",
    effects=["stripe.invoice.voided"],
    event="stripe-connector.void_invoice",
    data_model=StripeInvoice,
)
async def void_invoice(ctx, params: VoidInvoiceParams) -> ActionResult:
    """Void an invoice (draft or open) -- it will never be paid."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.create_object(ctx, api_key, f"invoices/{params.invoice_id}/void", {})
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_invoice(data).model_dump(), summary="Invoice voided.", refresh_panels=["sidebar"])


@chat.function(
    "send_invoice",
    "Email an open invoice to its customer.",
    action_type="write",
    effects=["stripe.invoice.sent"],
    event="stripe-connector.send_invoice",
    data_model=StripeInvoice,
)
async def send_invoice(ctx, params: SendInvoiceParams) -> ActionResult:
    """Email an open invoice to its customer."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.create_object(ctx, api_key, f"invoices/{params.invoice_id}/send", {})
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_invoice(data).model_dump(), summary="Invoice emailed to customer.")


# ──────────────────────────────────────────────────────────────────────────
# Checkout Sessions
# ──────────────────────────────────────────────────────────────────────────


def _to_checkout(o: dict) -> StripeCheckoutSession:
    return StripeCheckoutSession(
        id=o.get("id", ""), title=f"Checkout {o.get('id', '')}",
        status=o.get("status"), mode=o.get("mode", ""),
        amount_total=o.get("amount_total"), currency=o.get("currency"),
        customer_id=o.get("customer"), payment_status=o.get("payment_status"),
        url=o.get("url"),
    )


@chat.function(
    "create_checkout_session",
    "Create a Stripe Checkout Session -- a hosted payment page URL to send a customer to.",
    action_type="write",
    effects=["stripe.checkout_session.created"],
    event="stripe-connector.create_checkout_session",
    data_model=StripeCheckoutSession,
)
async def create_checkout_session(ctx, params: CreateCheckoutSessionParams) -> ActionResult:
    """Create a Stripe Checkout Session -- a hosted payment page URL to send a customer to."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {
        "mode": params.mode, "success_url": params.success_url,
        "cancel_url": params.cancel_url or None,
        "customer": params.customer_id or None,
        "customer_email": params.customer_email or None,
    }
    if params.line_items_json:
        try:
            items = json.loads(params.line_items_json)
        except Exception:
            return ActionResult.error("line_items_json is not valid JSON.", code="VALIDATION_ERROR")
        for i, li in enumerate(items):
            body[f"line_items[{i}][price]"] = li.get("price")
            body[f"line_items[{i}][quantity]"] = li.get("quantity", 1)
    elif params.price_id:
        body["line_items[0][price]"] = params.price_id
        body["line_items[0][quantity]"] = params.quantity
    try:
        data = await sc.create_object(ctx, api_key, "checkout/sessions", body)
    except sc.ClientFail as e:
        return _err(e)
    cs = _to_checkout(data)
    return ActionResult.success(data=cs.model_dump(), summary=f"Checkout session created: {cs.url}", refresh_panels=["sidebar"])


@chat.function(
    "get_checkout_session",
    "Get a single checkout session by id.",
    action_type="read",
    data_model=StripeCheckoutSession,
)
async def get_checkout_session(ctx, params: GetCheckoutSessionParams) -> ActionResult:
    """Get a single checkout session by id."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.get_object(ctx, api_key, "checkout/sessions", params.session_id)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_checkout(data).model_dump(), summary=f"Checkout status: {data.get('status')}.")


@chat.function(
    "list_checkout_sessions",
    "List checkout sessions, optionally filtered by customer.",
    action_type="read",
    data_model=StripeCheckoutSessionList,
)
async def list_checkout_sessions(ctx, params: ListCheckoutSessionsParams) -> ActionResult:
    """List checkout sessions, optionally filtered by customer."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    extra = {"customer": params.customer_id} if params.customer_id else None
    try:
        data = await sc.list_objects(ctx, api_key, "checkout/sessions", limit=params.limit, starting_after=params.starting_after, extra=extra)
    except sc.ClientFail as e:
        return _err(e)
    items = [_to_checkout(o) for o in data.get("data", [])]
    return ActionResult.success(data=StripeCheckoutSessionList(items=items, total=len(items), has_more=data.get("has_more", False)).model_dump(), summary=f"{len(items)} checkout session(s).")


@chat.function(
    "expire_checkout_session",
    "Expire a checkout session early so its URL stops working.",
    action_type="write",
    effects=["stripe.checkout_session.expired"],
    event="stripe-connector.expire_checkout_session",
    data_model=StripeCheckoutSession,
)
async def expire_checkout_session(ctx, params: ExpireCheckoutSessionParams) -> ActionResult:
    """Expire a checkout session early so its URL stops working."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.create_object(ctx, api_key, f"checkout/sessions/{params.session_id}/expire", {})
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_checkout(data).model_dump(), summary="Checkout session expired.")


# ──────────────────────────────────────────────────────────────────────────
# Payment Links
# ──────────────────────────────────────────────────────────────────────────


def _to_payment_link(o: dict) -> StripePaymentLink:
    return StripePaymentLink(id=o.get("id", ""), title=f"Payment Link {o.get('id', '')}", url=o.get("url", ""), active=bool(o.get("active", True)))


@chat.function(
    "create_payment_link",
    "Create a reusable Stripe Payment Link -- a shareable URL that sells a fixed price.",
    action_type="write",
    effects=["stripe.payment_link.created"],
    event="stripe-connector.create_payment_link",
    data_model=StripePaymentLink,
)
async def create_payment_link(ctx, params: CreatePaymentLinkParams) -> ActionResult:
    """Create a reusable Stripe Payment Link -- a shareable URL that sells a fixed price."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {"line_items[0][price]": params.price_id, "line_items[0][quantity]": params.quantity}
    try:
        data = await sc.create_object(ctx, api_key, "payment_links", body)
    except sc.ClientFail as e:
        return _err(e)
    pl = _to_payment_link(data)
    return ActionResult.success(data=pl.model_dump(), summary=f"Payment link created: {pl.url}", refresh_panels=["sidebar"])


@chat.function(
    "list_payment_links",
    "List payment links configured on this Stripe account, with their URLs and status.",
    action_type="read",
    data_model=StripePaymentLinkList,
)
async def list_payment_links(ctx, params: ListPaymentLinksParams) -> ActionResult:
    """List payment links."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.list_objects(ctx, api_key, "payment_links", limit=params.limit, starting_after=params.starting_after)
    except sc.ClientFail as e:
        return _err(e)
    items = [_to_payment_link(o) for o in data.get("data", [])]
    return ActionResult.success(data=StripePaymentLinkList(items=items, total=len(items), has_more=data.get("has_more", False)).model_dump(), summary=f"{len(items)} payment link(s).")


@chat.function(
    "update_payment_link",
    "Activate or deactivate a payment link.",
    action_type="write",
    effects=["stripe.payment_link.updated"],
    event="stripe-connector.update_payment_link",
    data_model=StripePaymentLink,
)
async def update_payment_link(ctx, params: UpdatePaymentLinkParams) -> ActionResult:
    """Activate or deactivate a payment link."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {}
    if params.active is not None:
        body["active"] = "true" if params.active else "false"
    try:
        data = await sc.update_object(ctx, api_key, "payment_links", params.payment_link_id, body)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_payment_link(data).model_dump(), summary="Payment link updated.", refresh_panels=["sidebar"])


# ──────────────────────────────────────────────────────────────────────────
# Coupons / Promotion Codes
# ──────────────────────────────────────────────────────────────────────────


def _to_coupon(o: dict) -> StripeCoupon:
    return StripeCoupon(
        id=o.get("id", ""), title=o.get("name") or o.get("id", ""),
        percent_off=o.get("percent_off"), amount_off=o.get("amount_off"),
        currency=o.get("currency"), duration=o.get("duration", ""), valid=bool(o.get("valid", True)),
    )


@chat.function(
    "create_coupon",
    "Create a discount coupon -- percent off or a fixed amount off.",
    action_type="write",
    effects=["stripe.coupon.created"],
    event="stripe-connector.create_coupon",
    data_model=StripeCoupon,
)
async def create_coupon(ctx, params: CreateCouponParams) -> ActionResult:
    """Create a discount coupon -- percent off or a fixed amount off."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {"duration": params.duration, "name": params.name or None}
    if params.percent_off:
        body["percent_off"] = params.percent_off
    if params.amount_off:
        body["amount_off"] = params.amount_off
        body["currency"] = params.currency
    if params.duration == "repeating" and params.duration_in_months:
        body["duration_in_months"] = params.duration_in_months
    try:
        data = await sc.create_object(ctx, api_key, "coupons", body)
    except sc.ClientFail as e:
        return _err(e)
    c = _to_coupon(data)
    return ActionResult.success(data=c.model_dump(), summary=f"Coupon {c.title} created.", refresh_panels=["sidebar"])


@chat.function(
    "list_coupons",
    "List discount coupons.",
    action_type="read",
    data_model=StripeCouponList,
)
async def list_coupons(ctx, params: ListCouponsParams) -> ActionResult:
    """List discount coupons."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.list_objects(ctx, api_key, "coupons", limit=params.limit, starting_after=params.starting_after)
    except sc.ClientFail as e:
        return _err(e)
    items = [_to_coupon(o) for o in data.get("data", [])]
    return ActionResult.success(data=StripeCouponList(items=items, total=len(items), has_more=data.get("has_more", False)).model_dump(), summary=f"{len(items)} coupon(s).")


@chat.function(
    "delete_coupon",
    "Permanently delete a coupon.",
    action_type="destructive",
    effects=["stripe.coupon.deleted"],
    event="stripe-connector.delete_coupon",
    data_model=DeleteResult,
)
async def delete_coupon(ctx, params: DeleteCouponParams) -> ActionResult:
    """Permanently delete a coupon."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        await sc.delete_object(ctx, api_key, "coupons", params.coupon_id)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=DeleteResult(deleted=True, id=params.coupon_id).model_dump(), summary="Coupon deleted.", refresh_panels=["sidebar"])


def _to_promo_code(o: dict) -> StripePromotionCode:
    return StripePromotionCode(id=o.get("id", ""), title=o.get("code", o.get("id", "")), active=bool(o.get("active", True)), coupon_id=(o.get("coupon") or {}).get("id", ""))


@chat.function(
    "create_promotion_code",
    "Create a customer-facing promo code (e.g. SAVE20) linked to an existing coupon.",
    action_type="write",
    effects=["stripe.promotion_code.created"],
    event="stripe-connector.create_promotion_code",
    data_model=StripePromotionCode,
)
async def create_promotion_code(ctx, params: CreatePromotionCodeParams) -> ActionResult:
    """Create a customer-facing promo code (e.g. SAVE20) linked to an existing coupon."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {"coupon": params.coupon_id, "code": params.code or None}
    try:
        data = await sc.create_object(ctx, api_key, "promotion_codes", body)
    except sc.ClientFail as e:
        return _err(e)
    pc = _to_promo_code(data)
    return ActionResult.success(data=pc.model_dump(), summary=f"Promo code {pc.title} created.", refresh_panels=["sidebar"])


@chat.function(
    "list_promotion_codes",
    "List promotion codes.",
    action_type="read",
    data_model=StripePromotionCodeList,
)
async def list_promotion_codes(ctx, params: ListPromotionCodesParams) -> ActionResult:
    """List promotion codes."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.list_objects(ctx, api_key, "promotion_codes", limit=params.limit, starting_after=params.starting_after)
    except sc.ClientFail as e:
        return _err(e)
    items = [_to_promo_code(o) for o in data.get("data", [])]
    return ActionResult.success(data=StripePromotionCodeList(items=items, total=len(items), has_more=data.get("has_more", False)).model_dump(), summary=f"{len(items)} promotion code(s).")


@chat.function(
    "update_promotion_code",
    "Activate or deactivate a promotion code.",
    action_type="write",
    effects=["stripe.promotion_code.updated"],
    event="stripe-connector.update_promotion_code",
    data_model=StripePromotionCode,
)
async def update_promotion_code(ctx, params: UpdatePromotionCodeParams) -> ActionResult:
    """Activate or deactivate a promotion code."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {}
    if params.active is not None:
        body["active"] = "true" if params.active else "false"
    try:
        data = await sc.update_object(ctx, api_key, "promotion_codes", params.promotion_code_id, body)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_promo_code(data).model_dump(), summary="Promotion code updated.", refresh_panels=["sidebar"])


# ──────────────────────────────────────────────────────────────────────────
# Disputes
# ──────────────────────────────────────────────────────────────────────────


def _to_dispute(o: dict) -> StripeDispute:
    return StripeDispute(
        id=o.get("id", ""), title=f"Dispute {o.get('id', '')}",
        amount=o.get("amount", 0), currency=o.get("currency", ""),
        reason=o.get("reason", ""), status=o.get("status", ""),
        charge_id=o.get("charge", ""), created=o.get("created", 0),
    )


@chat.function(
    "list_disputes",
    "List payment disputes (chargebacks).",
    action_type="read",
    data_model=StripeDisputeList,
)
async def list_disputes(ctx, params: ListDisputesParams) -> ActionResult:
    """List payment disputes (chargebacks)."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.list_objects(ctx, api_key, "disputes", limit=params.limit, starting_after=params.starting_after)
    except sc.ClientFail as e:
        return _err(e)
    items = [_to_dispute(o) for o in data.get("data", [])]
    return ActionResult.success(data=StripeDisputeList(items=items, total=len(items), has_more=data.get("has_more", False)).model_dump(), summary=f"{len(items)} dispute(s).")


@chat.function(
    "get_dispute",
    "Get a single dispute by id.",
    action_type="read",
    data_model=StripeDispute,
)
async def get_dispute(ctx, params: GetDisputeParams) -> ActionResult:
    """Get a single dispute by id."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.get_object(ctx, api_key, "disputes", params.dispute_id)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_dispute(data).model_dump(), summary=f"Dispute status: {data.get('status')}.")


@chat.function(
    "update_dispute",
    "Submit evidence for a dispute (free-text evidence field), or submit=True to finalize submission.",
    action_type="write",
    effects=["stripe.dispute.updated"],
    event="stripe-connector.update_dispute",
    data_model=StripeDispute,
)
async def update_dispute(ctx, params: UpdateDisputeParams) -> ActionResult:
    """Submit evidence for a dispute (free-text evidence field), or submit=True to finalize submission."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {}
    if params.evidence_text:
        body["evidence[uncategorized_text]"] = params.evidence_text
    if params.submit:
        body["submit"] = "true"
    try:
        data = await sc.update_object(ctx, api_key, "disputes", params.dispute_id, body)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_dispute(data).model_dump(), summary="Dispute updated.", refresh_panels=["sidebar"])


# ──────────────────────────────────────────────────────────────────────────
# Payouts / Transfers / Balance Transactions
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "list_payouts",
    "List payouts -- transfers of your Stripe balance to your bank account.",
    action_type="read",
    data_model=StripeObjectList,
)
async def list_payouts(ctx, params: ListPayoutsParams) -> ActionResult:
    """List payouts -- transfers of your Stripe balance to your bank account."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.list_objects(ctx, api_key, "payouts", limit=params.limit, starting_after=params.starting_after)
    except sc.ClientFail as e:
        return _err(e)
    items = [StripeObject(id=o.get("id", ""), title=f"{(o.get('amount', 0) or 0)/100:.2f} {str(o.get('currency','')).upper()} ({o.get('status')})", raw=o) for o in data.get("data", [])]
    return ActionResult.success(data=StripeObjectList(items=items, total=len(items), has_more=data.get("has_more", False)).model_dump(), summary=f"{len(items)} payout(s).")


@chat.function(
    "get_payout",
    "Get a single payout by id.",
    action_type="read",
    data_model=StripeObject,
)
async def get_payout(ctx, params: GetPayoutParams) -> ActionResult:
    """Get a single payout by id."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.get_object(ctx, api_key, "payouts", params.payout_id)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=StripeObject(id=data.get("id", ""), title=f"Payout {data.get('id','')}", raw=data).model_dump(), summary=f"Payout status: {data.get('status')}.")


@chat.function(
    "create_payout",
    "Manually trigger a payout of your available balance to your bank account (if manual payouts are enabled).",
    action_type="write",
    effects=["stripe.payout.created"],
    event="stripe-connector.create_payout",
    data_model=StripeObject,
)
async def create_payout(ctx, params: CreatePayoutParams) -> ActionResult:
    """Manually trigger a payout of your available balance to your bank account (if manual payouts are enabled)."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {"amount": params.amount, "currency": params.currency}
    try:
        data = await sc.create_object(ctx, api_key, "payouts", body)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=StripeObject(id=data.get("id", ""), title=f"Payout {data.get('id','')}", raw=data).model_dump(), summary="Payout created.", refresh_panels=["sidebar"])


@chat.function(
    "list_transfers",
    "List transfers to Connect accounts (funds moved to connected/managed accounts).",
    action_type="read",
    data_model=StripeObjectList,
)
async def list_transfers(ctx, params: ListTransfersParams) -> ActionResult:
    """List transfers to Connect accounts (funds moved to connected/managed accounts)."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.list_objects(ctx, api_key, "transfers", limit=params.limit, starting_after=params.starting_after)
    except sc.ClientFail as e:
        return _err(e)
    items = [StripeObject(id=o.get("id", ""), title=f"{(o.get('amount', 0) or 0)/100:.2f} {str(o.get('currency','')).upper()} -> {o.get('destination')}", raw=o) for o in data.get("data", [])]
    return ActionResult.success(data=StripeObjectList(items=items, total=len(items), has_more=data.get("has_more", False)).model_dump(), summary=f"{len(items)} transfer(s).")


@chat.function(
    "create_transfer",
    "Transfer funds from your platform balance to a connected Stripe account.",
    action_type="write",
    effects=["stripe.transfer.created"],
    event="stripe-connector.create_transfer",
    data_model=StripeObject,
)
async def create_transfer(ctx, params: CreateTransferParams) -> ActionResult:
    """Transfer funds from your platform balance to a connected Stripe account."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {"amount": params.amount, "currency": params.currency, "destination": params.destination_account_id}
    try:
        data = await sc.create_object(ctx, api_key, "transfers", body)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=StripeObject(id=data.get("id", ""), title=f"Transfer {data.get('id','')}", raw=data).model_dump(), summary="Transfer created.", refresh_panels=["sidebar"])


@chat.function(
    "list_balance_transactions",
    "List balance transactions -- every credit/debit event affecting your Stripe balance (charges, refunds, fees, payouts).",
    action_type="read",
    data_model=StripeObjectList,
)
async def list_balance_transactions(ctx, params: ListBalanceTransactionsParams) -> ActionResult:
    """List balance transactions -- every credit/debit event affecting your Stripe balance (charges, refunds, fees, payouts)."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.list_objects(ctx, api_key, "balance_transactions", limit=params.limit, starting_after=params.starting_after)
    except sc.ClientFail as e:
        return _err(e)
    items = [StripeObject(id=o.get("id", ""), title=f"{(o.get('amount', 0) or 0)/100:.2f} {str(o.get('currency','')).upper()} ({o.get('type')})", raw=o) for o in data.get("data", [])]
    return ActionResult.success(data=StripeObjectList(items=items, total=len(items), has_more=data.get("has_more", False)).model_dump(), summary=f"{len(items)} balance transaction(s).")


# ──────────────────────────────────────────────────────────────────────────
# Connect Accounts
# ──────────────────────────────────────────────────────────────────────────


def _to_account(o: dict) -> StripeConnectedAccount:
    return StripeConnectedAccount(
        id=o.get("id", ""), title=o.get("email") or o.get("id", ""),
        account_type=o.get("type", ""), country=o.get("country", ""),
        email=o.get("email"), charges_enabled=bool(o.get("charges_enabled")),
        payouts_enabled=bool(o.get("payouts_enabled")), details_submitted=bool(o.get("details_submitted")),
    )


@chat.function(
    "list_connected_accounts",
    "List connected accounts under your Stripe Connect platform.",
    action_type="read",
    data_model=StripeConnectedAccountList,
)
async def list_connected_accounts(ctx, params: ListConnectedAccountsParams) -> ActionResult:
    """List connected accounts under your Stripe Connect platform."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.list_objects(ctx, api_key, "accounts", limit=params.limit, starting_after=params.starting_after)
    except sc.ClientFail as e:
        return _err(e)
    items = [_to_account(o) for o in data.get("data", [])]
    return ActionResult.success(data=StripeConnectedAccountList(items=items, total=len(items), has_more=data.get("has_more", False)).model_dump(), summary=f"{len(items)} connected account(s).")


@chat.function(
    "create_connected_account",
    "Create a new Stripe Connect account (Standard, Express, or Custom) for a payments platform use case.",
    action_type="write",
    effects=["stripe.connected_account.created"],
    event="stripe-connector.create_connected_account",
    data_model=StripeConnectedAccount,
)
async def create_connected_account(ctx, params: CreateConnectedAccountParams) -> ActionResult:
    """Create a new Stripe Connect account (Standard, Express, or Custom) for a payments platform use case."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {"type": params.account_type, "country": params.country, "email": params.email or None}
    try:
        data = await sc.create_object(ctx, api_key, "accounts", body)
    except sc.ClientFail as e:
        return _err(e)
    acc = _to_account(data)
    return ActionResult.success(data=acc.model_dump(), summary=f"Created {acc.account_type} connected account.", refresh_panels=["sidebar"])


@chat.function(
    "get_connected_account",
    "Get a single connected account by id.",
    action_type="read",
    data_model=StripeConnectedAccount,
)
async def get_connected_account(ctx, params: GetConnectedAccountParams) -> ActionResult:
    """Get a single connected account by id."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.get_object(ctx, api_key, "accounts", params.account_id)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_account(data).model_dump(), summary=f"Account {params.account_id}: charges_enabled={data.get('charges_enabled')}.")


@chat.function(
    "delete_connected_account",
    "Permanently remove a Custom or Express connected account. Cannot be undone.",
    action_type="destructive",
    effects=["stripe.connected_account.deleted"],
    event="stripe-connector.delete_connected_account",
    data_model=DeleteResult,
)
async def delete_connected_account(ctx, params: DeleteConnectedAccountParams) -> ActionResult:
    """Permanently remove a Custom or Express connected account. Cannot be undone."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        await sc.delete_object(ctx, api_key, "accounts", params.account_id)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=DeleteResult(deleted=True, id=params.account_id).model_dump(), summary="Connected account removed.", refresh_panels=["sidebar"])


@chat.function(
    "create_account_link",
    "Create a one-time onboarding/update link URL for a connected account -- send the user there to complete Stripe's own KYC flow.",
    action_type="write",
    effects=["stripe.account_link.created"],
    event="stripe-connector.create_account_link",
    data_model=AccountLinkResult,
)
async def create_account_link(ctx, params: CreateAccountLinkParams) -> ActionResult:
    """Create a one-time onboarding/update link URL for a connected account -- send the user there to complete Stripe's own KYC flow."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {"account": params.account_id, "refresh_url": params.refresh_url, "return_url": params.return_url, "type": params.link_type}
    try:
        data = await sc.create_object(ctx, api_key, "account_links", body)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=AccountLinkResult(url=data.get("url", ""), expires_at=data.get("expires_at", 0)).model_dump(), summary="Onboarding link created.")


# ──────────────────────────────────────────────────────────────────────────
# Setup Intents / Tax Rates
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "create_setup_intent",
    "Create a SetupIntent -- collects and saves a payment method for future off-session charges, without charging now.",
    action_type="write",
    effects=["stripe.setup_intent.created"],
    event="stripe-connector.create_setup_intent",
    data_model=StripeSetupIntent,
)
async def create_setup_intent(ctx, params: CreateSetupIntentParams) -> ActionResult:
    """Create a SetupIntent -- collects and saves a payment method for future off-session charges, without charging now."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {"customer": params.customer_id or None}
    try:
        data = await sc.create_object(ctx, api_key, "setup_intents", body)
    except sc.ClientFail as e:
        return _err(e)
    si = StripeSetupIntent(id=data.get("id", ""), title=f"SetupIntent {data.get('id','')}", status=data.get("status"), customer_id=data.get("customer"), client_secret=data.get("client_secret"))
    return ActionResult.success(data=si.model_dump(), summary=f"SetupIntent created (status: {si.status}).", refresh_panels=["sidebar"])


@chat.function(
    "get_setup_intent",
    "Get a single SetupIntent by id.",
    action_type="read",
    data_model=StripeSetupIntent,
)
async def get_setup_intent(ctx, params: GetSetupIntentParams) -> ActionResult:
    """Get a single SetupIntent by id."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.get_object(ctx, api_key, "setup_intents", params.setup_intent_id)
    except sc.ClientFail as e:
        return _err(e)
    si = StripeSetupIntent(id=data.get("id", ""), title=f"SetupIntent {data.get('id','')}", status=data.get("status"), customer_id=data.get("customer"), client_secret=data.get("client_secret"))
    return ActionResult.success(data=si.model_dump(), summary=f"SetupIntent status: {si.status}.")


@chat.function(
    "list_setup_intents",
    "List SetupIntents, optionally filtered by customer.",
    action_type="read",
    data_model=StripeSetupIntentList,
)
async def list_setup_intents(ctx, params: ListSetupIntentsParams) -> ActionResult:
    """List SetupIntents, optionally filtered by customer."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    extra = {"customer": params.customer_id} if params.customer_id else None
    try:
        data = await sc.list_objects(ctx, api_key, "setup_intents", limit=params.limit, starting_after=params.starting_after, extra=extra)
    except sc.ClientFail as e:
        return _err(e)
    items = [StripeSetupIntent(id=o.get("id",""), title=f"SetupIntent {o.get('id','')}", status=o.get("status"), customer_id=o.get("customer"), client_secret=o.get("client_secret")) for o in data.get("data", [])]
    return ActionResult.success(data=StripeSetupIntentList(items=items, total=len(items), has_more=data.get("has_more", False)).model_dump(), summary=f"{len(items)} setup intent(s).")


@chat.function(
    "create_tax_rate",
    "Create a tax rate to apply to invoices/subscriptions/checkout line items.",
    action_type="write",
    effects=["stripe.tax_rate.created"],
    event="stripe-connector.create_tax_rate",
    data_model=StripeTaxRate,
)
async def create_tax_rate(ctx, params: CreateTaxRateParams) -> ActionResult:
    """Create a tax rate to apply to invoices/subscriptions/checkout line items."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {"display_name": params.display_name, "percentage": params.percentage, "inclusive": params.inclusive, "country": params.country or None, "jurisdiction": params.jurisdiction or None}
    try:
        data = await sc.create_object(ctx, api_key, "tax_rates", body)
    except sc.ClientFail as e:
        return _err(e)
    tr = StripeTaxRate(id=data.get("id", ""), title=data.get("display_name", ""), percentage=data.get("percentage", 0.0), inclusive=bool(data.get("inclusive")), active=bool(data.get("active", True)))
    return ActionResult.success(data=tr.model_dump(), summary=f"Tax rate {tr.title} ({tr.percentage}%) created.", refresh_panels=["sidebar"])


@chat.function(
    "list_tax_rates",
    "List configured tax rates.",
    action_type="read",
    data_model=StripeTaxRateList,
)
async def list_tax_rates(ctx, params: ListTaxRatesParams) -> ActionResult:
    """List configured tax rates."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.list_objects(ctx, api_key, "tax_rates", limit=params.limit, starting_after=params.starting_after)
    except sc.ClientFail as e:
        return _err(e)
    items = [StripeTaxRate(id=o.get("id",""), title=o.get("display_name",""), percentage=o.get("percentage", 0.0), inclusive=bool(o.get("inclusive")), active=bool(o.get("active", True))) for o in data.get("data", [])]
    return ActionResult.success(data=StripeTaxRateList(items=items, total=len(items), has_more=data.get("has_more", False)).model_dump(), summary=f"{len(items)} tax rate(s).")


# ──────────────────────────────────────────────────────────────────────────
# Webhook Endpoints / Signature Verification / Events
# ──────────────────────────────────────────────────────────────────────────


def _to_webhook(o: dict) -> StripeWebhookEndpoint:
    return StripeWebhookEndpoint(
        id=o.get("id", ""), title=o.get("url", o.get("id", "")),
        url=o.get("url", ""), status=o.get("status", ""),
        enabled_events=o.get("enabled_events", []),
    )


@chat.function(
    "list_webhook_endpoints",
    "List webhook endpoints configured on your Stripe account.",
    action_type="read",
    data_model=StripeWebhookEndpointList,
)
async def list_webhook_endpoints(ctx, params: ListWebhookEndpointsParams) -> ActionResult:
    """List webhook endpoints configured on your Stripe account."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.list_objects(ctx, api_key, "webhook_endpoints", limit=params.limit, starting_after=params.starting_after)
    except sc.ClientFail as e:
        return _err(e)
    items = [_to_webhook(o) for o in data.get("data", [])]
    return ActionResult.success(data=StripeWebhookEndpointList(items=items, total=len(items), has_more=data.get("has_more", False)).model_dump(), summary=f"{len(items)} webhook endpoint(s).")


@chat.function(
    "create_webhook_endpoint",
    "Register a new webhook endpoint URL with Stripe for the given event types.",
    action_type="write",
    effects=["stripe.webhook_endpoint.created"],
    event="stripe-connector.create_webhook_endpoint",
    data_model=StripeWebhookEndpoint,
)
async def create_webhook_endpoint(ctx, params: CreateWebhookEndpointParams) -> ActionResult:
    """Register a new webhook endpoint URL with Stripe for the given event types."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    events = [e.strip() for e in params.enabled_events.split(",") if e.strip()] or ["*"]
    body = {"url": params.url, "description": params.description or None}
    for i, ev in enumerate(events):
        body[f"enabled_events[{i}]"] = ev
    try:
        data = await sc.create_object(ctx, api_key, "webhook_endpoints", body)
    except sc.ClientFail as e:
        return _err(e)
    wh = _to_webhook(data)
    return ActionResult.success(data=wh.model_dump(), summary=f"Webhook endpoint created: {wh.url}", refresh_panels=["sidebar"])


@chat.function(
    "update_webhook_endpoint",
    "Update a webhook endpoint's URL, enabled events, or disabled status.",
    action_type="write",
    effects=["stripe.webhook_endpoint.updated"],
    event="stripe-connector.update_webhook_endpoint",
    data_model=StripeWebhookEndpoint,
)
async def update_webhook_endpoint(ctx, params: UpdateWebhookEndpointParams) -> ActionResult:
    """Update a webhook endpoint's URL, enabled events, or disabled status."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    body = {}
    if params.url:
        body["url"] = params.url
    if params.enabled_events:
        events = [e.strip() for e in params.enabled_events.split(",") if e.strip()]
        for i, ev in enumerate(events):
            body[f"enabled_events[{i}]"] = ev
    if params.disabled is not None:
        body["disabled"] = params.disabled
    try:
        data = await sc.update_object(ctx, api_key, "webhook_endpoints", params.webhook_id, body)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=_to_webhook(data).model_dump(), summary="Webhook endpoint updated.", refresh_panels=["sidebar"])


@chat.function(
    "delete_webhook_endpoint",
    "Permanently remove a webhook endpoint.",
    action_type="destructive",
    effects=["stripe.webhook_endpoint.deleted"],
    event="stripe-connector.delete_webhook_endpoint",
    data_model=DeleteResult,
)
async def delete_webhook_endpoint(ctx, params: DeleteWebhookEndpointParams) -> ActionResult:
    """Permanently remove a webhook endpoint."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        await sc.delete_object(ctx, api_key, "webhook_endpoints", params.webhook_id)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=DeleteResult(deleted=True, id=params.webhook_id).model_dump(), summary="Webhook endpoint deleted.", refresh_panels=["sidebar"])


@chat.function(
    "verify_webhook_signature",
    "Verify a Stripe webhook's Stripe-Signature header against its signing secret -- confirms the payload really came from Stripe and was not tampered with.",
    action_type="write",
    effects=["stripe.webhook.verified"],
    event="stripe-connector.verify_webhook_signature",
    data_model=WebhookVerifyResult,
)
async def verify_webhook_signature(ctx, params: VerifyWebhookSignatureParams) -> ActionResult:
    """Verify a Stripe webhook's Stripe-Signature header against its signing secret -- confirms the payload really came from Stripe and was not tampered with."""
    try:
        parts = dict(kv.split("=", 1) for kv in params.signature_header.split(",") if "=" in kv)
        timestamp = parts.get("t", "")
        v1_sig = parts.get("v1", "")
        signed_payload = f"{timestamp}.{params.payload}"
        expected_sig = hmac.new(params.webhook_secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
        valid = hmac.compare_digest(expected_sig, v1_sig)
    except Exception:
        valid = False
    reason = "" if valid else "Signature mismatch or malformed header -- payload may be forged, or the wrong signing secret was used."
    event_type, event_id = "", ""
    if valid:
        try:
            evt = json.loads(params.payload)
            event_type = evt.get("type", "")
            event_id = evt.get("id", "")
        except Exception:
            pass
    result = WebhookVerifyResult(valid=valid, event_type=event_type, event_id=event_id, reason=reason)
    return ActionResult.success(data=result.model_dump(), summary=("Signature valid." if valid else f"Signature INVALID: {reason}"))


@chat.function(
    "list_events",
    "List recent events on your Stripe account -- the same events your webhooks receive.",
    action_type="read",
    data_model=StripeEventList,
)
async def list_events(ctx, params: ListEventsParams) -> ActionResult:
    """List recent events on your Stripe account -- the same events your webhooks receive."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    extra = {"type": params.event_type} if params.event_type else None
    try:
        data = await sc.list_objects(ctx, api_key, "events", limit=params.limit, starting_after=params.starting_after, extra=extra)
    except sc.ClientFail as e:
        return _err(e)
    items = [StripeEvent(id=o.get("id",""), title=o.get("type",""), event_type=o.get("type",""), created=o.get("created", 0), livemode=bool(o.get("livemode"))) for o in data.get("data", [])]
    return ActionResult.success(data=StripeEventList(items=items, total=len(items), has_more=data.get("has_more", False)).model_dump(), summary=f"{len(items)} event(s).")


@chat.function(
    "get_event",
    "Get one Stripe event in full, including its full data payload.",
    action_type="read",
    data_model=StripeObject,
)
async def get_event(ctx, params: GetEventParams) -> ActionResult:
    """Get one Stripe event in full, including its full data payload."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.get_object(ctx, api_key, "events", params.event_id)
    except sc.ClientFail as e:
        return _err(e)
    return ActionResult.success(data=StripeObject(id=data.get("id",""), title=data.get("type",""), raw=data).model_dump(), summary=f"Event type: {data.get('type')}.")


# ──────────────────────────────────────────────────────────────────────────
# Tier 3 value-add: revenue / dunning reporting
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "get_revenue_report",
    "Build a revenue snapshot over the last N days: gross/net volume, refunds, success/fail rates, disputes, active subscriptions and a rough MRR estimate. Value-add: Stripe's own API has no single endpoint for this -- it aggregates charges + subscriptions + disputes client-side, same pattern as MuleSoft Connector's audit_cloudhub_environment.",
    action_type="read",
    data_model=RevenueReport,
)
async def get_revenue_report(ctx, params: RevenueReportParams) -> ActionResult:
    """Build a revenue snapshot over the last N days: gross/net volume, refunds,
    success/fail rates, disputes, active subscriptions and a rough MRR estimate.
    Value-add: Stripe's own API has no single endpoint for this -- it aggregates
    charges + subscriptions + disputes client-side, same pattern as MuleSoft
    Connector's audit_cloudhub_environment."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    since = int(time.time()) - params.days * 86400
    try:
        charges = await sc.list_objects(ctx, api_key, "charges", limit=100, extra={"created[gte]": since})
        subs = await sc.list_objects(ctx, api_key, "subscriptions", limit=100, extra={"status": "active"})
        disputes = await sc.list_objects(ctx, api_key, "disputes", limit=100, extra={"created[gte]": since})
        invoices_past_due = await sc.list_objects(ctx, api_key, "invoices", limit=100, extra={"status": "open"})
    except sc.ClientFail as e:
        return _err(e)
    gross = 0
    refunded = 0
    ok_count = 0
    fail_count = 0
    currency = ""
    for c in charges.get("data", []):
        currency = currency or c.get("currency", "")
        if c.get("paid"):
            gross += c.get("amount", 0)
            ok_count += 1
        else:
            fail_count += 1
        refunded += c.get("amount_refunded", 0)
    mrr = 0
    for s in subs.get("data", []):
        items = (s.get("items") or {}).get("data") or []
        for it in items:
            price = it.get("price") or {}
            recurring = price.get("recurring") or {}
            unit_amount = price.get("unit_amount", 0) or 0
            interval = recurring.get("interval", "month")
            qty = it.get("quantity", 1)
            monthly = unit_amount * qty
            if interval == "year":
                monthly = monthly / 12
            elif interval == "week":
                monthly = monthly * 4.33
            elif interval == "day":
                monthly = monthly * 30
            mrr += monthly
    report = RevenueReport(
        period_days=params.days, currency=currency,
        gross_volume=gross, refunded_volume=refunded, net_volume=gross - refunded,
        successful_charges=ok_count, failed_charges=fail_count,
        disputes_count=len(disputes.get("data", [])),
        active_subscriptions=len(subs.get("data", [])),
        mrr_estimate=int(mrr),
        past_due_invoices=len(invoices_past_due.get("data", [])),
    )
    return ActionResult.success(
        data=report.model_dump(),
        summary=(
            f"Last {params.days}d: {report.net_volume/100:.2f} {currency.upper()} net "
            f"({report.successful_charges} ok / {report.failed_charges} failed), "
            f"MRR ~{report.mrr_estimate/100:.2f} {currency.upper()}, "
            f"{report.disputes_count} dispute(s), {report.past_due_invoices} past-due invoice(s)."
        ),
    )


@chat.function(
    "get_dunning_report",
    "List open/past-due invoices that are stuck in Stripe's Smart Retries (dunning) cycle -- customers whose card failed and are being re-attempted. Value-add: surfaces revenue-at-risk that would otherwise require manually filtering the Dashboard's invoice list by status + attempt_count.",
    action_type="read",
    data_model=DunningReport,
)
async def get_dunning_report(ctx, params: DunningReportParams) -> ActionResult:
    """List open/past-due invoices that are stuck in Stripe's Smart Retries
    (dunning) cycle -- customers whose card failed and are being re-attempted.
    Value-add: surfaces revenue-at-risk that would otherwise require manually
    filtering the Dashboard's invoice list by status + attempt_count."""
    resolved = await _resolve_key(ctx, params.connection_id)
    if not resolved:
        return ActionResult.error("No Stripe account connected.", code="NOT_CONNECTED")
    api_key, _ = resolved
    try:
        data = await sc.list_objects(ctx, api_key, "invoices", limit=100, extra={"status": "open"})
    except sc.ClientFail as e:
        return _err(e)
    rows = []
    for inv in data.get("data", []):
        if inv.get("attempt_count", 0) > 0:
            rows.append(StripeObject(
                id=inv.get("id", ""), title=f"{inv.get('customer','')}: {(inv.get('amount_due',0) or 0)/100:.2f} {str(inv.get('currency','')).upper()} (attempt {inv.get('attempt_count')})",
                raw=inv,
            ))
    return ActionResult.success(
        data=DunningReport(items=rows, total=len(rows)).model_dump(),
        summary=f"{len(rows)} invoice(s) currently in dunning retry.",
    )
