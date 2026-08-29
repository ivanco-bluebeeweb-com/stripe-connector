# Stripe Connector — UI component plan

Источники: `ui-primitives-reference.md`, `UI_INTERFACE_STANDARD.md`, `concepts/panels.md`.
Основано на `POST_CONNECT_EXPERIENCE.md` этого приложения.

## 1. Компоненты

| Экран | Примитивы | Почему именно эти |
|---|---|---|
| Sidebar (left) | `ui.Column`(align="start") + `ui.Text`(режим Live/Test) + `ui.Divider` + navigation `ui.ListItem` + `ui.Button`("App settings") | Без карточек по стандарту; явный Live/Test индикатор — критично для платёжного коннектора (нельзя молча путать режимы). |
| Revenue Dashboard (center, `center_overlay=True`) | `ui.Stats`(MRR/Volume today/Failed rate) + `ui.Chart`(type="line", x_key="date" — revenue over time) + `ui.DataTable`(последние платежи) | `Chart` типа line — единственный подходящий для тренда выручки во времени; `Stats` даёт мгновенную сводку без чтения таблицы. |
| Payment/Charge Detail | Back-button + `ui.KeyValue`(amount/status/customer/method) + `ui.Badge`(status: succeeded/failed/refunded — цветовое кодирование) + `ui.Timeline`(события charge: created→authorized→captured→refunded) | `Badge` — стандартный способ показать статус транзакции цветом; `Timeline` точно ложится на жизненный цикл платежа. |
| Subscriptions List | `ui.DataTable`(columns: customer, plan, MRR, status, next_billing; sortable) + `ui.Select`(param_name="status_filter") с лейблом "Статус подписки" | `DataTable` с сортировкой — нужно быстро найти churn-риски (status=past_due). |
| Refund/Dispute Action | `ui.Dialog`(title="Вернуть средства?", content=`ui.Stack`([`ui.Text`(caption, "Сумма возврата"), `ui.Input`(type="number", param_name="refund_amount", placeholder="0.00"), `ui.Text`(caption, "Причина"), `ui.Select`(param_name="reason", options=[duplicate/fraudulent/requested_by_customer])]), confirm_label="Вернуть") | `Dialog` — единственный modal-подтверждение примитив в SDK; `Select` с коротким списком заменяет несуществующий Radio (см. `UI_COMPONENT_VOCABULARY.md` §4). |
| Invoice Builder | `ui.Form`(action="create_invoice") + `ui.Input`(type="email", param_name="customer_email", label-текст сверху) + N×`ui.Row`([`ui.Input`(description), `ui.Input`(type="number", amount)]) генерируется бэкендом по числу строк в состоянии черновика + `ui.Button`("+ Добавить позицию", on_click=`ui.Call`("add_invoice_line")) + `ui.Button`("Отправить счёт") | В SDK нет client-side repeater-примитива — динамический список строк собирается на бэкенде: каждый клик "+ Добавить позицию" вызывает `ui.Call`, который перерисовывает форму с ещё одной парой `Input`-полей (состояние черновика хранится в сессии), см. `UI_COMPONENT_VOCABULARY.md` §4. |
| App Settings | `ui.Accordion`([Connections+Disconnect, Webhooks CRUD, Default Currency Select]) | Централизованные настройки по стандарту. |

## 2. User flow

1. **SESSION INIT** → `__panel__stripe_sidebar` (left) рендерит режим (Live/Test) +
   разделы (Overview, Payments, Subscriptions, Customers, Invoices) + auto_action на
   последний активный раздел (обычно Overview).
2. Клик "Overview" → `ui.Call` → центр-панель `stripe_overview` (`center_overlay=True`):
   Stats + Chart + DataTable последних платежей.
3. Клик на строку платежа в DataTable → `ui.Call(item_id=charge.id)` на тот же
   center-panel handler, параметризованный `charge_id` → рендерит Payment Detail
   (back-button возвращает в список тем же handler'ом без `charge_id`).
4. На Payment Detail: если `status=succeeded` и не refunded → кнопка "Refund" →
   `ui.Dialog` подтверждения с `NumberInput` суммы → `ui.Call(action=refund_charge)` →
   `refresh_panels=["stripe_overview"]` обновляет и Stats (revenue), и DataTable.
5. Раздел "Subscriptions" (Tabs или отдельный sidebar-пункт) → DataTable с фильтром по
   статусу (`Select`) → клик на строку → Subscription Detail (KeyValue + история счетов
   как Timeline).
6. Раздел "Invoices" → кнопка "Создать счёт" → `ui.Call` открывает center overlay с
   `Form` (Repeater для позиций) → submit → `create_invoice` → `refresh_panels` списка
   счетов, форма закрывается (Empty/список).
7. "App settings" (правый нижний угол sidebar, всегда последний элемент) → отдельный
   center overlay `stripe_settings`: Accordion с Connections (rotate/disconnect
   двухшаговое подтверждение), Webhooks CRUD, Default Currency.

## 3. Конкретные экраны (screens)

### Screen: Overview (`stripe_overview`, center, default)
- Stats row: `MRR`, `Volume today`, `Failed payments rate` (3 Stat, trend где применимо).
- Chart: revenue за 30 дней (line).
- DataTable: 10 последних платежей (customer, amount, status Badge, date), row-click →
  Payment Detail.

### Screen: Payment Detail (`stripe_overview` + `charge_id` param)
- Back-button "← К платежам".
- KeyValue: amount, currency, customer email, payment method, created.
- Badge статуса крупно вверху.
- Timeline: authorized → captured → (refunded, если есть).
- Row of Buttons: "Refund" (если применимо), "View customer", "Resend receipt".

### Screen: Subscriptions (sidebar-раздел, отдельный center panel `stripe_subscriptions`)
- Select "Статус подписки" (плейсхолдер "Все статусы") над DataTable.
- DataTable: customer, plan, MRR, status Badge, next billing date.
- Row-click → Subscription Detail (KeyValue + Timeline биллинг-истории).

### Screen: Invoices (`stripe_invoices`)
- Button "Создать счёт" вверху.
- DataTable существующих счетов (number, customer, amount, status, due date).
- Create Invoice — center overlay с Form: TextInput "Email клиента" (placeholder
  "client@company.com"), Repeater строк (TextInput "Описание" + NumberInput "Сумма"),
  Button "Отправить".

### Screen: App settings (`stripe_settings`)
- Accordion секция "Подключение": текущий режим (Live/Test), API key (замаскирован),
  кнопки Rotate/Disconnect (2-шаговое подтверждение через Dialog).
- Accordion секция "Webhooks": List существующих + Button "Добавить" → Dialog с
  TextInput URL + Checkbox-группа событий.
- Accordion секция "Валюта по умолчанию": Select с лейблом "Валюта" для новых счетов.
