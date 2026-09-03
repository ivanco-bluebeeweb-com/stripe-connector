"""Panel UI -- connections list/connect form + a recent-activity summary
(customers, payment intents, balance) in the sidebar.

SIDEBAR CONTENT -- NO CARDS ANYWHERE, per ~/UI_INTERFACE_STANDARD.md's
"left sidebar, no decorated cards" rule (same convention as MuleSoft
Connector's / Power Automate Connector's / n8n Connector's panels.py).

Every section (connections, connect form, activity) is a plain ui.Stack,
content stacked vertically and left-aligned, sections separated by
ui.Divider() -- no Card border/background/shadow anywhere in this slot.
Disconnect lives only in the "App settings" screen (panels_settings.py).
The one secondary "App settings" button is always the LAST element at the
bottom of the sidebar.

WHY A SINGLE API-KEY FIELD, NOT A MULTI-FIELD FORM LIKE MuleSoft/Power
Automate/UiPath/Blue Prism/Automation Anywhere.

Stripe authenticates with one Bearer secret key -- see app.py's module
docstring for the full reasoning (no OAuth2 client-credentials dance for
a user managing their own account). The form therefore asks for exactly
one field (the key) plus an optional label, with a help dialog explaining
where to find/create one and why a Restricted Key is recommended.
"""
from __future__ import annotations

from imperal_sdk import ui

import stripe_client as sc
from app import ext
import handlers as h


def _settings_button() -> ui.UINode:
    """The one required secondary entry point into the settings screen --
    always the last element at the bottom of the sidebar."""
    return ui.Button(
        "App settings", variant="secondary", size="sm", icon="settings", on_click=ui.Call("__panel__stripe_settings"),
    )


def _connection_row(c: dict) -> ui.UINode:
    label = c.get("label") or c.get("id", "")
    mode = "Test mode" if c.get("is_test") else "Live mode"
    return ui.Stack(direction="v", gap=1, children=[
        ui.Text(label, variant="body"),
        ui.Text(mode, variant="caption"),
    ])


def _connections_section(connections: list[dict]) -> ui.UINode:
    if not connections:
        return ui.Text("No Stripe accounts connected yet.", variant="caption")
    children: list[ui.UINode] = []
    for i, c in enumerate(connections):
        if i > 0:
            children.append(ui.Divider())
        children.append(_connection_row(c))
    return ui.Stack(direction="v", gap=2, children=children)


def _connect_section() -> ui.UINode:
    """Plain content, no Card wrapper. Stretched full-width per
    UI_INTERFACE_STANDARD.md (2026-08-20). No intro heading/description
    text here -- the API key walkthrough lives ONLY in
    stripe_connect_help's modal (button below opens it); repeating it
    here would duplicate that instruction."""
    return ui.Stack(direction="v", gap=3, align="stretch", children=[
        ui.Button("How do I set this up?", variant="ghost", size="sm",
                  icon="HelpCircle",
                  on_click=ui.Call("__panel__stripe_connect_help")),
        ui.Form(
            action="connect_stripe",
            submit_label="Verify and connect",
            children=[
                ui.Stack(direction="v", gap=1, children=[
                    ui.Text("Stripe Secret or Restricted Key", variant="caption"),
                    ui.Password(param_name="api_key",
                                 placeholder="sk_live_... / rk_live_..."),
                ]),
                ui.Stack(direction="v", gap=1, children=[
                    ui.Text("Label (optional)", variant="caption"),
                    ui.Input(param_name="label", placeholder="e.g. Main account"),
                ]),
            ],
        ),
    ])


@ext.panel("stripe_connect", slot="left", title="Stripe", icon="💳",
           default_width=320, min_width=260, max_width=420)
async def stripe_connect_panel(ctx, **kwargs) -> object:
    connections = await h._get_connections(ctx)
    connected = bool(connections)

    header = ui.Header(text="Stripe", level=2,
                        subtitle="Manage your Stripe payments account from Imperal")

    if not connected:
        return ui.Stack(direction="v", gap=4, align="stretch", children=[
            header,
            _connect_section(),
            ui.Divider(),
            _settings_button(),
        ])

    balance_line = ""
    first = connections[0]
    try:
        data = await sc.get_balance(ctx, first.get("api_key", ""))
        available = data.get("available", [{}])
        if available:
            amt = available[0].get("amount", 0) / 100
            cur = str(available[0].get("currency", "")).upper()
            balance_line = f"{amt:.2f} {cur} available"
    except sc.ClientFail:
        balance_line = ""

    return ui.Stack(direction="v", gap=4, align="stretch", children=[
        header,
        ui.Text("Connected accounts", variant="subtitle"),
        _connections_section(connections),
        ui.Divider(),
        _connect_section(),
        ui.Divider(),
        ui.Text(f"Balance -- {first.get('label') or first.get('id', '')}", variant="subtitle"),
        ui.Text(balance_line or "Unable to load balance.", variant="caption"),
        ui.Divider(),
        ui.Button("View revenue", variant="primary", size="sm", icon="TrendingUp", on_click=ui.Call("__panel__stripe_center")),
        ui.Divider(),
        _settings_button(),
    ])


@ext.panel("stripe_connect_help", slot="center",
           title="How to connect Stripe", center_overlay=True)
async def stripe_connect_help(ctx, **kwargs) -> object:
    content = ui.Stack(direction="v", gap=3, children=[
        ui.Text("1. In the Stripe Dashboard, open Developers > API keys."),
        ui.Text("2. For best security, click \"Create restricted key\" and grant only the permissions you want this connector to use (e.g. Customers, Payment Intents, Subscriptions)."),
        ui.Text("3. Copy the key -- it starts with sk_live_/sk_test_ (Secret key) or rk_live_/rk_test_ (Restricted key)."),
        ui.Text("4. Paste it below. Test mode keys (sk_test_/rk_test_) work against Stripe's separate sandbox data -- nothing real is charged."),
        ui.Divider(),
        ui.Alert(
            title="Your key, your account",
            message=(
                "This key is encrypted and used only to call the Stripe API "
                "on your behalf, against your own Stripe account and your "
                "own fees/quota."
            ),
            type="info",
        ),
        ui.Divider(),
        ui.Link(
            label="Open Stripe's official API keys guide",
            href="https://docs.stripe.com/keys",
        ),
    ])
    return ui.Dialog(
        title="How to connect Stripe",
        content=content,
        confirm_label="",
        cancel_label="Close",
    )


def _customer_row(c) -> dict:
    return {
        "name": c.name or c.email or c.id, "email": c.email or "—",
        "customer_id": c.id,
    }


@ext.panel("stripe_center", slot="center", title="Stripe", icon="💳", center_overlay=True)
async def stripe_center_panel(ctx, customer_id: str = "", **kwargs) -> object:
    """Post-connect main screen: revenue dashboard, or a customer detail
    when `customer_id` is passed (master-detail via the same panel_id, per
    UI_COMPONENT_VOCABULARY.md §3)."""
    connections = await h._get_connections(ctx)
    if not connections:
        return ui.Empty(
            message="Connect a Stripe account from the sidebar to see revenue here.",
            icon="💳",
        )
    if customer_id:
        return await _customer_detail(ctx, customer_id)
    return await _revenue_dashboard(ctx)


async def _revenue_dashboard(ctx) -> ui.UINode:
    report_result = await h.get_revenue_report(ctx, h.RevenueReportParams(days=30))
    stats: list[ui.UINode] = []
    if report_result.success and report_result.data:
        r = report_result.data
        cur = (r.currency or "").upper()
        stats = [
            ui.Stat(label="Gross volume (30d)", value=f"{r.gross_volume / 100:.2f} {cur}"),
            ui.Stat(label="Net volume (30d)", value=f"{r.net_volume / 100:.2f} {cur}"),
            ui.Stat(label="Active subscriptions", value=str(r.active_subscriptions)),
            ui.Stat(label="MRR estimate", value=f"{r.mrr_estimate / 100:.2f} {cur}"),
            ui.Stat(label="Disputes (30d)", value=str(r.disputes_count)),
            ui.Stat(label="Past-due invoices", value=str(r.past_due_invoices)),
        ]

    customers_result = await h.list_customers(ctx, h.ListCustomersParams(limit=50))
    body: list[ui.UINode] = []
    if stats:
        body.append(ui.Stats(children=stats))
    body.append(ui.Divider())
    body.append(ui.Text("Recent customers", variant="heading"))

    if not customers_result.success:
        body.append(ui.Error(message=customers_result.error or "Could not load customers.",
                              retry=ui.Call("__panel__stripe_center")))
        return ui.Stack(direction="v", gap=4, children=body)

    customers = customers_result.data.items if customers_result.data else []
    if not customers:
        body.append(ui.Empty(message="No customers yet.", icon="👤"))
        return ui.Stack(direction="v", gap=4, children=body)

    columns = [
        ui.DataColumn("name", "Customer", sortable=True),
        ui.DataColumn("email", "Email", sortable=True),
    ]
    body.append(ui.DataTable(
        columns=columns,
        rows=[_customer_row(c) for c in customers],
        on_row_click=ui.Call("__panel__stripe_center", customer_id=""),
    ))
    return ui.Stack(direction="v", gap=4, children=body)


async def _customer_detail(ctx, customer_id: str) -> ui.UINode:
    result = await h.get_customer(ctx, h.GetCustomerParams(customer_id=customer_id))
    if not result.success or not result.data:
        return ui.Stack(direction="v", gap=4, children=[
            ui.Button("← Back to dashboard", variant="ghost", size="sm",
                      on_click=ui.Call("__panel__stripe_center")),
            ui.Error(message=result.error or "Customer not found.",
                     retry=ui.Call("__panel__stripe_center", customer_id=customer_id)),
        ])
    c = result.data
    charges_result = await h.list_charges(ctx, h.ListChargesParams(limit=20, extra_params={}))
    charges = charges_result.data.items if charges_result.success and charges_result.data else []
    columns = [
        ui.DataColumn("title", "Charge", sortable=False),
        ui.DataColumn("amount", "Amount", sortable=False),
        ui.DataColumn("status", "Status", sortable=False),
    ]
    rows = [
        {"title": ch.title or ch.id, "amount": f"{ch.amount / 100:.2f} {(ch.currency or '').upper()}",
         "status": ch.status or ("paid" if ch.paid else "failed")}
        for ch in charges if ch.customer_id == customer_id
    ]
    return ui.Stack(direction="v", gap=4, children=[
        ui.Button("← Back to dashboard", variant="ghost", size="sm",
                  on_click=ui.Call("__panel__stripe_center")),
        ui.Header(text=c.name or c.email or c.id, level=2, subtitle=c.email or ""),
        ui.KeyValue(items=[
            {"key": "Email", "value": c.email or "—"},
            {"key": "Customer ID", "value": c.id},
        ]),
        ui.Text("Recent charges", variant="heading"),
        ui.DataTable(columns=columns, rows=rows) if rows
        else ui.Text("No charges found for this customer.", variant="caption"),
    ])
