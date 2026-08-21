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
        "App settings", variant="secondary", size="sm", full_width=True,
        icon="settings", on_click=ui.Call("__panel__stripe_settings"),
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


@ext.panel("stripe_center", slot="center", title="Stripe", icon="💳", center_overlay=True)
async def stripe_center_panel(ctx, **kwargs) -> object:
    """Base center panel -- per UI_INTERFACE_STANDARD.md (2026-08-20).
    This app has no list/detail content of its own to show in the center
    by default (everything lives in the sidebar). MUST carry
    center_overlay=True: per docs.imperal.io/en/concepts/panels, a plain
    slot="center" panel is registered but the Panel app never fetches it
    at session-init without that flag. Text is the shared canonical
    wording -- must stay identical across every app in this situation."""
    return ui.Empty(
        message="Nothing to show here -- this app is managed entirely from the sidebar.",
        icon="👈",
    )
