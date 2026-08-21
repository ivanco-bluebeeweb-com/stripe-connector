# Pricing History — Stripe Connector

Обязательный журнал: каждое выставление или изменение цен на функции этого
приложения фиксируется здесь — что изменилось, почему, и на основании
чего. Не переписывать прошлые записи — только дописывать новые сверху.

---

## 2026-08-21 — первый прайсинг, по образцу MuleSoft Connector

**Контекст:** пользователь явно попросил повторить для Stripe тот же
подход, что уже применялся к MuleSoft Connector. Прайсинг выполняется
ПОСЛЕ прохождения чистого `imperal validate` (0 ошибок, 0 предупреждений,
только 1 info о необязательном `@ext.on_install`) и ДО `submit_for_review`,
строго по канонической последовательности `PRICING_POLICY.md` §1:

```
код готов → пост-аудит чистый (imperal validate: 0 errors, 0 warnings) →
deploy_app → update_pricing → submit_for_review
```

**Шкала — фиксированная платформенная {0, 8, 16, 20, 40, 60}, без
исключений и без x1.8-маркапа (Stripe не Google-backed API):**

| Цена | Функции | Обоснование |
|---|---|---|
| 0 | `connect_stripe`, `disconnect_stripe`, `list_stripe_connections` | настройка/удаление доступа к учётным данным — не операция с Stripe API |
| 8 | все `list_*`/`get_*` чтения (36 функций: `get_balance`, `list_customers`, `get_customer`, `list_payment_methods`, `list_payment_intents`, `get_payment_intent`, `list_charges`, `get_charge`, `list_refunds`, `list_products`, `get_product`, `list_prices`, `get_price`, `list_subscriptions`, `get_subscription`, `list_invoices`, `get_invoice`, `get_checkout_session`, `list_checkout_sessions`, `list_payment_links`, `list_coupons`, `list_promotion_codes`, `list_disputes`, `get_dispute`, `list_payouts`, `get_payout`, `list_transfers`, `list_balance_transactions`, `list_connected_accounts`, `get_connected_account`, `get_setup_intent`, `list_setup_intents`, `list_tax_rates`, `list_webhook_endpoints`, `list_events`, `get_event`) плюс `verify_webhook_signature` (тоже чтение/проверка, не мутирует состояние) | простое чтение состояния с внешнего API — по правилу §2 "READ никогда не 0" |
| 16 | 37 стандартных одиночных write/destructive действий: `create_customer`, `update_customer`, `delete_customer`, `attach_payment_method`, `detach_payment_method`, `set_default_payment_method`, `create_payment_intent`, `cancel_payment_intent`, `create_refund`, `create_product`, `update_product`, `delete_product`, `create_price`, `update_price`, `create_subscription`, `update_subscription`, `cancel_subscription`, `create_invoice`, `finalize_invoice`, `void_invoice`, `send_invoice`, `create_checkout_session`, `expire_checkout_session`, `create_payment_link`, `update_payment_link`, `create_coupon`, `delete_coupon`, `create_promotion_code`, `update_promotion_code`, `update_dispute`, `create_connected_account`, `delete_connected_account`, `create_account_link`, `create_setup_intent`, `create_tax_rate`, `create_webhook_endpoint`, `update_webhook_endpoint`, `delete_webhook_endpoint` | создание/изменение/удаление ОДНОЙ сущности — стандартный write/destructive тариф |
| 20 | `confirm_payment_intent`, `capture_payment_intent`, `pay_invoice`, `create_payout`, `create_transfer` | реально двигают деньги пользователя ПРЯМО СЕЙЧАС (списание/выплата/перевод), а не просто создают объект-намерение — тяжелее обычного write |
| 40 | `get_revenue_report`, `get_dunning_report` | Tier-3 value-add отчёты, агрегирующие много объектов (charges/invoices) за один вызов в единый бизнес-отчёт |
| 60 | — (не использовано) | у Stripe Connector в этой версии нет bulk_*/CSV-функций; шкала оставлена для будущего расширения |

Итого: 3×0 + 36×8 + 1×8 (verify_webhook_signature) + 37×16 + 5×20 + 2×40 = 85
функций, полное покрытие манифеста — проверено программно (`tool-prices.json`
ключи == `imperal.json["tools"][].name`, множества совпадают 1:1).

`pricing_model = "per_action"`, `monthly_price = 0`, `revenue_split_dev = 95`
(partner-тир, тот же, что у MuleSoft Connector).

**Источник истины продублирован в `imperal.json["pricing"]`** этого
приложения (не только в `tool-prices.json`) — так цена видна прямо в
манифесте независимо от состояния платформенного API, по тому же
правилу, что и у MuleSoft/Make.com/n8n Connector.

**Метод применения — `developer.update_pricing`, ОСНОВНОЙ И
ПОДТВЕРЖДЁННО РАБОЧИЙ способ (см. канонический `PRICING_POLICY.md` §3).
`save_pricing` НЕ используется.** `pricing_config` передаётся как
настоящий JSON-объект (не экранированная строка), `revenue_split_dev=95`
передаётся явным параметром вызова, не только внутри `pricing_config`.
