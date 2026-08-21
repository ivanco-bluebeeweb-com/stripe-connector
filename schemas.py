"""Pydantic params models + SDL entity contracts for Stripe Connector.

All params models are module-scope (V17 federal invariant, same rule as
MuleSoft Connector / DataForSEO Connector's schemas.py).

WHY A GENERIC `StripeObject` ENTITY FOR MOST RESOURCES, NOT ONE HAND-TYPED
CLASS PER STRIPE OBJECT.

Stripe exposes 40+ object types across Payments/Billing/Connect. Hand
writing a fully-typed Entity subclass for every one of them (Customer,
PaymentIntent, Charge, Invoice, Subscription, Price, Product, Coupon,
PromotionCode, Payout, Transfer, Dispute, ConnectedAccount, ...) would
mean ~40 near-duplicate classes that all just mirror Stripe's own JSON
shape back. Instead, high-traffic/central objects (Customer, PaymentIntent,
Charge, Subscription, Invoice, Product, Price) get real typed Entities so
they render well in chat/panels; secondary objects use `StripeObject`, a
thin Entity wrapping the raw dict in `raw`, still SDL-valid (has id/title/
kind) so the kernel can display and cross-reference it.
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from imperal_sdk import sdl


class NoParams(BaseModel):
    """Explicit empty params model -- V17 disallows untyped handlers."""
    pass


# ──────────────────────────────────────────────────────────────────────────
# Connection
# ──────────────────────────────────────────────────────────────────────────


class ConnectStripeParams(BaseModel):
    api_key: str = Field(
        "",
        description="Your Stripe Secret Key (sk_live_.../sk_test_...) or, "
        "preferably, a Restricted Key (rk_live_.../rk_test_...) scoped to "
        "what you want this connector to do. Found in Stripe Dashboard > "
        "Developers > API keys.",
    )
    label: str = Field("", description="Optional friendly name for this Stripe account connection.")


class ProviderConnection(sdl.Entity):
    id: str = ""
    title: str = ""
    connected: bool = False
    mode: str = ""
    detail: str = ""


class ProviderConnectionList(sdl.EntityList[ProviderConnection]):
    pass


class DisconnectStripeParams(BaseModel):
    connection_id: str = Field(..., description="Connection id to disconnect, from list_connections.")


class DeleteResult(BaseModel):
    ok: bool = True
    id: str = ""


# ──────────────────────────────────────────────────────────────────────────
# Balance / generic listing
# ──────────────────────────────────────────────────────────────────────────


class ConnectionScopedParams(BaseModel):
    connection_id: str = Field("", description="Which connected Stripe account to use. Omit to use the only/default one.")


class ListParams(ConnectionScopedParams):
    limit: int = Field(10, ge=1, le=100, description="Max number of objects to return (1-100).")
    starting_after: str = Field("", description="Cursor: object id to start after (pagination).")


class StripeBalance(BaseModel):
    available: list[dict] = Field(default_factory=list)
    pending: list[dict] = Field(default_factory=list)
    connect_reserved: list[dict] = Field(default_factory=list)
    livemode: bool = False


class StripeObject(sdl.Entity):
    """Generic thin wrapper for secondary Stripe resources."""
    id: str = ""
    title: str = ""
    raw: dict = Field(default_factory=dict)


class StripeObjectList(sdl.EntityList[StripeObject]):
    pass


# ──────────────────────────────────────────────────────────────────────────
# Customers
# ──────────────────────────────────────────────────────────────────────────


class ListCustomersParams(ListParams):
    email: str = Field("", description="Filter by exact customer email.")


class CreateCustomerParams(ConnectionScopedParams):
    email: str = Field("", description="Customer's email.")
    name: str = Field("", description="Customer's full name or business name.")
    description: str = Field("", description="Internal description for this customer.")
    phone: str = Field("", description="Customer's phone number.")
    metadata: dict = Field(default_factory=dict, description="Arbitrary key/value metadata.")


class UpdateCustomerParams(ConnectionScopedParams):
    customer_id: str = Field(..., description="Customer id (cus_...).")
    email: str = Field("", description="New email, if changing.")
    name: str = Field("", description="New name, if changing.")
    description: str = Field("", description="New description, if changing.")
    phone: str = Field("", description="New phone, if changing.")
    metadata: dict = Field(default_factory=dict, description="Metadata to merge/overwrite.")


class GetCustomerParams(ConnectionScopedParams):
    customer_id: str = Field(..., description="Customer id (cus_...).")


class DeleteCustomerParams(ConnectionScopedParams):
    customer_id: str = Field(..., description="Customer id (cus_...) to permanently delete.")


class StripeCustomer(sdl.Entity):
    id: str = ""
    title: str = ""
    email: str = ""
    name: str = ""
    phone: str = ""
    balance: int = 0
    currency: str = ""
    delinquent: bool = False
    created: int = 0
    livemode: bool = False


class StripeCustomerList(sdl.EntityList[StripeCustomer]):
    pass


# ──────────────────────────────────────────────────────────────────────────
# Payment Methods
# ──────────────────────────────────────────────────────────────────────────


class ListPaymentMethodsParams(ListParams):
    customer_id: str = Field(..., description="Customer id (cus_...) to list saved payment methods for.")
    type: str = Field("card", description="Payment method type filter, e.g. card, sepa_debit, us_bank_account.")


class AttachPaymentMethodParams(ConnectionScopedParams):
    payment_method_id: str = Field(..., description="Payment method id (pm_...) to attach.")
    customer_id: str = Field(..., description="Customer id (cus_...) to attach it to.")


class DetachPaymentMethodParams(ConnectionScopedParams):
    payment_method_id: str = Field(..., description="Payment method id (pm_...) to detach from its customer.")


class SetDefaultPaymentMethodParams(ConnectionScopedParams):
    customer_id: str = Field(..., description="Customer id (cus_...).")
    payment_method_id: str = Field(..., description="Payment method id (pm_...) to set as default for invoices.")


# ──────────────────────────────────────────────────────────────────────────
# Payment Intents / Charges / Refunds
# ──────────────────────────────────────────────────────────────────────────


class ListPaymentIntentsParams(ListParams):
    customer_id: str = Field("", description="Optionally filter by customer id (cus_...).")


class CreatePaymentIntentParams(ConnectionScopedParams):
    amount: int = Field(..., description="Amount in the smallest currency unit (e.g. cents for USD).")
    currency: str = Field("usd", description="Three-letter ISO currency code.")
    customer_id: str = Field("", description="Optional customer id (cus_...) to attach this payment to.")
    payment_method_id: str = Field("", description="Optional existing payment method id (pm_...) to charge.")
    description: str = Field("", description="Internal description shown in the Dashboard.")
    receipt_email: str = Field("", description="Email to send the receipt to.")
    confirm: bool = Field(False, description="If true, attempt to confirm/charge immediately (needs payment_method_id).")
    off_session: bool = Field(False, description="Set true for a merchant-initiated charge on a saved card, no customer present.")
    metadata: dict = Field(default_factory=dict)


class GetPaymentIntentParams(ConnectionScopedParams):
    payment_intent_id: str = Field(..., description="PaymentIntent id (pi_...).")


class ConfirmPaymentIntentParams(ConnectionScopedParams):
    payment_intent_id: str = Field(..., description="PaymentIntent id (pi_...) to confirm.")
    payment_method_id: str = Field("", description="Payment method id (pm_...) to confirm with, if not already attached.")


class CancelPaymentIntentParams(ConnectionScopedParams):
    payment_intent_id: str = Field(..., description="PaymentIntent id (pi_...) to cancel.")
    cancellation_reason: str = Field("", description="Optional reason: duplicate, fraudulent, requested_by_customer, abandoned.")


class CapturePaymentIntentParams(ConnectionScopedParams):
    payment_intent_id: str = Field(..., description="PaymentIntent id (pi_...) to capture (for manual-capture intents).")
    amount_to_capture: int = Field(0, description="Amount to capture, in smallest currency unit. 0 = capture full authorized amount.")


class StripePaymentIntent(sdl.Entity):
    id: str = ""
    title: str = ""
    amount: int = 0
    currency: str = ""
    status: str | None = None
    customer_id: str | None = None
    created: int = 0
    livemode: bool = False


class StripePaymentIntentList(sdl.EntityList[StripePaymentIntent]):
    pass


class ListChargesParams(ListParams):
    customer_id: str = Field("", description="Optionally filter by customer id (cus_...).")
    payment_intent_id: str = Field("", description="Optionally filter by originating PaymentIntent id (pi_...).")


class GetChargeParams(ConnectionScopedParams):
    charge_id: str = Field(..., description="Charge id (ch_...).")


class StripeCharge(sdl.Entity):
    id: str = ""
    title: str = ""
    amount: int = 0
    currency: str = ""
    status: str | None = None
    paid: bool = False
    refunded: bool = False
    customer_id: str | None = None
    created: int = 0


class StripeChargeList(sdl.EntityList[StripeCharge]):
    pass


class CreateRefundParams(ConnectionScopedParams):
    charge_id: str = Field("", description="Charge id (ch_...) to refund. Provide this OR payment_intent_id.")
    payment_intent_id: str = Field("", description="PaymentIntent id (pi_...) to refund. Provide this OR charge_id.")
    amount: int = Field(0, description="Amount to refund in smallest currency unit. 0 = full refund.")
    reason: str = Field("", description="Optional reason: duplicate, fraudulent, requested_by_customer.")


class ListRefundsParams(ListParams):
    charge_id: str = Field("", description="Optionally filter by charge id (ch_...).")


class StripeRefund(sdl.Entity):
    id: str = ""
    title: str = ""
    amount: int = 0
    currency: str = ""
    status: str | None = None
    reason: str | None = None
    charge_id: str | None = None
    created: int = 0


# ──────────────────────────────────────────────────────────────────────────
# Products / Prices
# ──────────────────────────────────────────────────────────────────────────


class ListProductsParams(ListParams):
    active: bool | None = Field(None, description="Filter by active status. Omit for all.")


class CreateProductParams(ConnectionScopedParams):
    name: str = Field(..., description="Product name shown to customers.")
    description: str = Field("", description="Product description.")
    active: bool = Field(True, description="Whether the product is currently available for purchase.")
    metadata: dict = Field(default_factory=dict)


class UpdateProductParams(ConnectionScopedParams):
    product_id: str = Field(..., description="Product id (prod_...).")
    name: str = Field("", description="New name, if changing.")
    description: str = Field("", description="New description, if changing.")
    active: bool | None = Field(None, description="New active status, if changing.")


class GetProductParams(ConnectionScopedParams):
    product_id: str = Field(..., description="Product id (prod_...).")


class DeleteProductParams(ConnectionScopedParams):
    product_id: str = Field(..., description="Product id (prod_...) to permanently delete. Must have no prices attached that are in use.")


class StripeProduct(sdl.Entity):
    id: str = ""
    title: str = ""
    description: str | None = None
    active: bool = True
    created: int = 0


class StripeProductList(sdl.EntityList[StripeProduct]):
    pass


class ListPricesParams(ListParams):
    product_id: str = Field("", description="Optionally filter by product id (prod_...).")
    active: bool | None = Field(None, description="Filter by active status. Omit for all.")


class CreatePriceParams(ConnectionScopedParams):
    product_id: str = Field(..., description="Product id (prod_...) this price belongs to.")
    unit_amount: int = Field(..., description="Price in the smallest currency unit (e.g. cents).")
    currency: str = Field("usd", description="Three-letter ISO currency code.")
    recurring_interval: str = Field("", description="If recurring: day, week, month, or year. Leave empty for a one-time price.")
    recurring_interval_count: int = Field(1, description="Number of intervals between charges (e.g. 3 with interval=month = quarterly).")
    nickname: str = Field("", description="Internal nickname for this price.")


class UpdatePriceParams(ConnectionScopedParams):
    price_id: str = Field(..., description="Price id (price_...). Note: Stripe prices are otherwise immutable -- only active/nickname/metadata can change.")
    active: bool | None = Field(None, description="New active status, if changing.")
    nickname: str = Field("", description="New nickname, if changing.")


class GetPriceParams(ConnectionScopedParams):
    price_id: str = Field(..., description="Price id (price_...).")


class StripePrice(sdl.Entity):
    id: str = ""
    title: str = ""
    unit_amount: int | None = None
    currency: str = ""
    product_id: str = ""
    recurring_interval: str | None = None
    active: bool = True


class StripePriceList(sdl.EntityList[StripePrice]):
    pass


# ──────────────────────────────────────────────────────────────────────────
# Subscriptions
# ──────────────────────────────────────────────────────────────────────────


class ListSubscriptionsParams(ListParams):
    customer_id: str = Field("", description="Optionally filter by customer id (cus_...).")
    status: str = Field("", description="Optionally filter by status: active, past_due, canceled, trialing, etc.")


class CreateSubscriptionParams(ConnectionScopedParams):
    customer_id: str = Field(..., description="Customer id (cus_...) to subscribe.")
    price_id: str = Field(..., description="Price id (price_...) for the subscription's single item. For multiple items, use price_ids.")
    price_ids: list[str] = Field(default_factory=list, description="Multiple price ids, if the subscription has several line items.")
    trial_period_days: int = Field(0, description="Free trial length in days before the first charge. 0 = no trial.")
    metadata: dict = Field(default_factory=dict)


class UpdateSubscriptionParams(ConnectionScopedParams):
    subscription_id: str = Field(..., description="Subscription id (sub_...).")
    price_id: str = Field("", description="New price id to swap the (first) subscription item to.")
    proration_behavior: str = Field("", description="create_prorations, none, or always_invoice. Leave empty for Stripe's default.")
    cancel_at_period_end: bool | None = Field(None, description="Set True to cancel at period end instead of immediately.")


class CancelSubscriptionParams(ConnectionScopedParams):
    subscription_id: str = Field(..., description="Subscription id (sub_...) to cancel.")
    at_period_end: bool = Field(False, description="If True, cancels at period end instead of immediately.")


class GetSubscriptionParams(ConnectionScopedParams):
    subscription_id: str = Field(..., description="Subscription id (sub_...).")


class StripeSubscription(sdl.Entity):
    id: str = ""
    title: str = ""
    status: str | None = None
    customer_id: str | None = None
    current_period_end: int | None = None
    cancel_at_period_end: bool = False
    created: int = 0


class StripeSubscriptionList(sdl.EntityList[StripeSubscription]):
    pass


# ──────────────────────────────────────────────────────────────────────────
# Invoices
# ──────────────────────────────────────────────────────────────────────────


class ListInvoicesParams(ListParams):
    customer_id: str = Field("", description="Optionally filter by customer id (cus_...).")
    status: str = Field("", description="Optionally filter by status: draft, open, paid, uncollectible, void.")


class CreateInvoiceParams(ConnectionScopedParams):
    customer_id: str = Field(..., description="Customer id (cus_...) to invoice.")
    auto_advance: bool = Field(True, description="If True, Stripe automatically finalizes/attempts payment on schedule.")
    description: str = Field("", description="Description shown on the invoice.")


class GetInvoiceParams(ConnectionScopedParams):
    invoice_id: str = Field(..., description="Invoice id (in_...).")


class FinalizeInvoiceParams(ConnectionScopedParams):
    invoice_id: str = Field(..., description="Invoice id (in_...) to finalize (draft -> open).")


class PayInvoiceParams(ConnectionScopedParams):
    invoice_id: str = Field(..., description="Invoice id (in_...) to attempt payment on immediately.")


class VoidInvoiceParams(ConnectionScopedParams):
    invoice_id: str = Field(..., description="Invoice id (in_...) to void (only draft/open invoices).")


class SendInvoiceParams(ConnectionScopedParams):
    invoice_id: str = Field(..., description="Invoice id (in_...) to email to the customer.")


class StripeInvoice(sdl.Entity):
    id: str = ""
    title: str = ""
    status: str | None = None
    customer_id: str | None = None
    amount_due: int = 0
    amount_paid: int = 0
    currency: str = ""
    created: int = 0
    hosted_invoice_url: str | None = None


class StripeInvoiceList(sdl.EntityList[StripeInvoice]):
    pass


# ──────────────────────────────────────────────────────────────────────────
# Checkout Sessions / Payment Links
# ──────────────────────────────────────────────────────────────────────────


class CreateCheckoutSessionParams(ConnectionScopedParams):
    mode: str = Field("payment", description="Checkout mode: payment, subscription, or setup.")
    success_url: str = Field(..., description="Where to redirect after a successful checkout.")
    cancel_url: str = Field("", description="Where to redirect if the customer cancels.")
    customer_id: str = Field("", description="Optional existing customer id (cus_...) to attach.")
    customer_email: str = Field("", description="Optional email to prefill if no customer_id.")
    price_id: str = Field("", description="A single Price id (price_...) to sell one unit of (simple case).")
    quantity: int = Field(1, ge=1, description="Quantity for price_id, if set.")
    line_items_json: str = Field(
        "", description="Advanced: JSON array of {price, quantity} objects for multiple line items, "
        "overrides price_id/quantity if set.",
    )


class GetCheckoutSessionParams(ConnectionScopedParams):
    session_id: str = Field(..., description="Checkout Session id (cs_...).")


class ListCheckoutSessionsParams(ListParams):
    customer_id: str = Field("", description="Optionally filter by customer id (cus_...).")


class ExpireCheckoutSessionParams(ConnectionScopedParams):
    session_id: str = Field(..., description="Checkout Session id (cs_...) to expire early.")


class StripeCheckoutSession(sdl.Entity):
    id: str = ""
    title: str = ""
    status: str | None = None
    mode: str = ""
    amount_total: int | None = None
    currency: str | None = None
    customer_id: str | None = None
    payment_status: str | None = None
    url: str | None = None


class StripeCheckoutSessionList(sdl.EntityList[StripeCheckoutSession]):
    pass


class CreatePaymentLinkParams(ConnectionScopedParams):
    price_id: str = Field(..., description="Price id (price_...) this link sells.")
    quantity: int = Field(1, ge=1, description="Quantity of the price per purchase.")
    active: bool = Field(True, description="Whether the link is currently usable.")


class ListPaymentLinksParams(ListParams):
    active: bool | None = Field(None, description="Filter by active status. Omit for all.")


class UpdatePaymentLinkParams(ConnectionScopedParams):
    payment_link_id: str = Field(..., description="Payment Link id (plink_...).")
    active: bool | None = Field(None, description="New active status, if changing.")


class StripePaymentLink(sdl.Entity):
    id: str = ""
    title: str = ""
    active: bool = True
    url: str = ""


class StripePaymentLinkList(sdl.EntityList[StripePaymentLink]):
    pass


# ──────────────────────────────────────────────────────────────────────────
# Coupons / Promotion Codes
# ──────────────────────────────────────────────────────────────────────────


class CreateCouponParams(ConnectionScopedParams):
    name: str = Field("", description="Display name for the coupon.")
    percent_off: float | None = Field(None, description="Percentage discount (e.g. 20 for 20%). Mutually exclusive with amount_off.")
    amount_off: int | None = Field(None, description="Fixed discount in the smallest currency unit (e.g. cents). Requires currency.")
    currency: str = Field("", description="Currency for amount_off, e.g. usd.")
    duration: str = Field("once", description="once, repeating, or forever.")
    duration_in_months: int | None = Field(None, description="Required if duration=repeating.")
    max_redemptions: int | None = Field(None, description="Optional maximum total redemptions.")


class ListCouponsParams(ListParams):
    pass


class DeleteCouponParams(ConnectionScopedParams):
    coupon_id: str = Field(..., description="Coupon id to permanently delete.")


class StripeCoupon(sdl.Entity):
    id: str = ""
    title: str = ""
    percent_off: float | None = None
    amount_off: int | None = None
    duration: str = ""
    valid: bool = True


class StripeCouponList(sdl.EntityList[StripeCoupon]):
    pass


class CreatePromotionCodeParams(ConnectionScopedParams):
    coupon_id: str = Field(..., description="Coupon id this promotion code applies.")
    code: str = Field("", description="Customer-facing code, e.g. SUMMER20. Auto-generated if omitted.")
    max_redemptions: int | None = Field(None, description="Optional maximum total redemptions for this code.")
    active: bool = Field(True, description="Whether the code is currently redeemable.")


class ListPromotionCodesParams(ListParams):
    coupon_id: str = Field("", description="Optionally filter by coupon id.")
    active: bool | None = Field(None, description="Filter by active status. Omit for all.")


class UpdatePromotionCodeParams(ConnectionScopedParams):
    promotion_code_id: str = Field(..., description="Promotion code id (promo_...).")
    active: bool | None = Field(None, description="New active status, if changing.")


class StripePromotionCode(sdl.Entity):
    id: str = ""
    title: str = ""
    code: str = ""
    active: bool = True
    times_redeemed: int = 0


class StripePromotionCodeList(sdl.EntityList[StripePromotionCode]):
    pass


# ──────────────────────────────────────────────────────────────────────────
# Disputes
# ──────────────────────────────────────────────────────────────────────────


class ListDisputesParams(ListParams):
    status: str = Field("", description="Optionally filter by status, e.g. needs_response, under_review, won, lost.")


class GetDisputeParams(ConnectionScopedParams):
    dispute_id: str = Field(..., description="Dispute id (dp_...).")


class UpdateDisputeParams(ConnectionScopedParams):
    dispute_id: str = Field(..., description="Dispute id (dp_...) to submit evidence for.")
    evidence_text: str = Field("", description="Free-text evidence/explanation to submit for this dispute.")
    submit: bool = Field(False, description="If True, immediately submits the evidence for review (final -- cannot add more after).")


class StripeDispute(sdl.Entity):
    id: str = ""
    title: str = ""
    status: str = ""
    amount: int = 0
    currency: str = ""
    reason: str = ""
    charge_id: str | None = None
    evidence_due_by: int | None = None


class StripeDisputeList(sdl.EntityList[StripeDispute]):
    pass


# ──────────────────────────────────────────────────────────────────────────
# Payouts / Transfers / Balance transactions
# ──────────────────────────────────────────────────────────────────────────


class ListPayoutsParams(ListParams):
    status: str = Field("", description="Optionally filter by status: pending, paid, in_transit, canceled, failed.")


class GetPayoutParams(ConnectionScopedParams):
    payout_id: str = Field(..., description="Payout id (po_...).")


class CreatePayoutParams(ConnectionScopedParams):
    amount: int = Field(..., description="Amount to pay out, in the smallest currency unit (e.g. cents).")
    currency: str = Field(..., description="Three-letter ISO currency code.")
    description: str = Field("", description="Optional description shown on the payout.")


class CancelPayoutParams(ConnectionScopedParams):
    payout_id: str = Field(..., description="Payout id (po_...) to cancel while still pending.")


class StripePayout(sdl.Entity):
    id: str = ""
    title: str = ""
    amount: int = 0
    currency: str = ""
    status: str = ""
    arrival_date: int | None = None


class StripePayoutList(sdl.EntityList[StripePayout]):
    pass


class ListTransfersParams(ListParams):
    destination_account_id: str = Field("", description="Optionally filter by destination connected account id (acct_...).")


class CreateTransferParams(ConnectionScopedParams):
    amount: int = Field(..., description="Amount to transfer, in the smallest currency unit (e.g. cents).")
    currency: str = Field(..., description="Three-letter ISO currency code.")
    destination_account_id: str = Field(..., description="Destination connected account id (acct_...).")
    description: str = Field("", description="Optional description for this transfer.")


class GetTransferParams(ConnectionScopedParams):
    transfer_id: str = Field(..., description="Transfer id (tr_...).")


class StripeTransfer(sdl.Entity):
    id: str = ""
    title: str = ""
    amount: int = 0
    currency: str = ""
    destination: str = ""
    created: int = 0


class StripeTransferList(sdl.EntityList[StripeTransfer]):
    pass


class ListBalanceTransactionsParams(ListParams):
    txn_type: str = Field("", description="Optionally filter by type, e.g. charge, refund, payout, adjustment.")


class StripeBalanceTransaction(sdl.Entity):
    id: str = ""
    title: str = ""
    amount: int = 0
    net: int = 0
    fee: int = 0
    currency: str = ""
    txn_type: str = ""
    created: int = 0


class StripeBalanceTransactionList(sdl.EntityList[StripeBalanceTransaction]):
    pass


# ──────────────────────────────────────────────────────────────────────────
# Connect (connected accounts)
# ──────────────────────────────────────────────────────────────────────────


class ListConnectedAccountsParams(ListParams):
    pass


class CreateConnectedAccountParams(ConnectionScopedParams):
    account_type: str = Field("standard", description="Connect account type: standard, express, or custom.")
    country: str = Field("US", description="Two-letter country code for the connected account.")
    email: str = Field("", description="Email of the connected account's owner.")


class GetConnectedAccountParams(ConnectionScopedParams):
    account_id: str = Field(..., description="Connected account id (acct_...).")


class DeleteConnectedAccountParams(ConnectionScopedParams):
    account_id: str = Field(..., description="Connected account id (acct_...) to permanently remove (Custom/Express accounts only).")


class CreateAccountLinkParams(ConnectionScopedParams):
    account_id: str = Field(..., description="Connected account id (acct_...) to onboard.")
    refresh_url: str = Field(..., description="Where Stripe redirects if the link expires/fails.")
    return_url: str = Field(..., description="Where Stripe redirects once onboarding is complete.")
    link_type: str = Field("account_onboarding", description="account_onboarding or account_update.")


class StripeConnectedAccount(sdl.Entity):
    id: str = ""
    title: str = ""
    account_type: str = ""
    country: str = ""
    email: str | None = None
    charges_enabled: bool = False
    payouts_enabled: bool = False
    details_submitted: bool = False


class StripeConnectedAccountList(sdl.EntityList[StripeConnectedAccount]):
    pass


class AccountLinkResult(BaseModel):
    url: str = ""
    expires_at: int = 0


# ──────────────────────────────────────────────────────────────────────────
# Setup Intents / Tax Rates
# ──────────────────────────────────────────────────────────────────────────


class CreateSetupIntentParams(ConnectionScopedParams):
    customer_id: str = Field("", description="Optional customer id (cus_...) this setup intent is for.")
    usage: str = Field("off_session", description="off_session or on_session.")


class GetSetupIntentParams(ConnectionScopedParams):
    setup_intent_id: str = Field(..., description="SetupIntent id (seti_...).")


class ListSetupIntentsParams(ListParams):
    customer_id: str = Field("", description="Optionally filter by customer id (cus_...).")


class StripeSetupIntent(sdl.Entity):
    id: str = ""
    title: str = ""
    status: str = ""
    customer_id: str | None = None


class StripeSetupIntentList(sdl.EntityList[StripeSetupIntent]):
    pass


class CreateTaxRateParams(ConnectionScopedParams):
    display_name: str = Field(..., description="Name shown to customers, e.g. VAT.")
    percentage: float = Field(..., description="Tax rate percentage, e.g. 20 for 20%.")
    inclusive: bool = Field(False, description="Whether this rate is included in the price (True) or added on top (False).")
    country: str = Field("", description="Optional two-letter country code this rate applies to.")


class ListTaxRatesParams(ListParams):
    active: bool | None = Field(None, description="Filter by active status. Omit for all.")


class StripeTaxRate(sdl.Entity):
    id: str = ""
    title: str = ""
    percentage: float = 0.0
    inclusive: bool = False
    active: bool = True


class StripeTaxRateList(sdl.EntityList[StripeTaxRate]):
    pass


# ──────────────────────────────────────────────────────────────────────────
# Webhooks (endpoint management) + signature verification
# ──────────────────────────────────────────────────────────────────────────


class ListWebhookEndpointsParams(ListParams):
    pass


class CreateWebhookEndpointParams(ConnectionScopedParams):
    url: str = Field(..., description="HTTPS URL Stripe will POST events to.")
    enabled_events: str = Field(
        "*", description="Comma-separated list of event types to send (e.g. 'invoice.paid,charge.refunded'), or '*' for all.",
    )
    description: str = Field("", description="Optional description for this endpoint.")


class UpdateWebhookEndpointParams(ConnectionScopedParams):
    webhook_endpoint_id: str = Field(..., description="Webhook endpoint id (we_...).")
    url: str = Field("", description="New URL, if changing.")
    enabled_events: str = Field("", description="New comma-separated event list, if changing.")
    disabled: bool | None = Field(None, description="Set True to disable, False to re-enable.")


class DeleteWebhookEndpointParams(ConnectionScopedParams):
    webhook_endpoint_id: str = Field(..., description="Webhook endpoint id (we_...) to permanently delete.")


class StripeWebhookEndpoint(sdl.Entity):
    id: str = ""
    title: str = ""
    url: str = ""
    status: str = ""
    enabled_events: list[str] = Field(default_factory=list)


class StripeWebhookEndpointList(sdl.EntityList[StripeWebhookEndpoint]):
    pass


class VerifyWebhookSignatureParams(BaseModel):
    payload: str = Field(..., description="Raw webhook request body (exact bytes as received), as a string.")
    signature_header: str = Field(..., description="The value of the Stripe-Signature request header.")
    webhook_secret: str = Field(..., description="This endpoint's signing secret (whsec_...) from the Stripe Dashboard webhook settings.")


class WebhookVerifyResult(BaseModel):
    valid: bool = False
    event_type: str = ""
    event_id: str = ""
    reason: str = ""


class ListEventsParams(ListParams):
    event_type: str = Field("", description="Optionally filter by event type, e.g. invoice.paid, charge.refunded.")


class StripeEvent(sdl.Entity):
    id: str = ""
    title: str = ""
    event_type: str = ""
    created: int = 0
    livemode: bool = False


class StripeEventList(sdl.EntityList[StripeEvent]):
    pass


class GetEventParams(ConnectionScopedParams):
    event_id: str = Field(..., description="Event id (evt_...).")


# ──────────────────────────────────────────────────────────────────────────
# Tier 3 value-add: revenue / dunning reporting
# ──────────────────────────────────────────────────────────────────────────


class RevenueReportParams(ConnectionScopedParams):
    days: int = Field(30, ge=1, le=365, description="Look back this many days for charges/invoices.")


class RevenueReportRow(BaseModel):
    metric: str = ""
    value: str = ""


class RevenueReport(BaseModel):
    period_days: int = 0
    currency: str = ""
    gross_volume: int = 0
    refunded_volume: int = 0
    net_volume: int = 0
    successful_charges: int = 0
    failed_charges: int = 0
    disputes_count: int = 0
    active_subscriptions: int = 0
    mrr_estimate: int = 0
    past_due_invoices: int = 0


class DunningReportParams(ConnectionScopedParams):
    pass


class DunningInvoiceRow(BaseModel):
    invoice_id: str = ""
    customer_id: str | None = None
    amount_due: int = 0
    currency: str = ""
    attempt_count: int = 0
    next_payment_attempt: int | None = None


class DunningReport(sdl.EntityList[StripeObject]):
    pass
