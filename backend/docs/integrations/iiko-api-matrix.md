# iikoCloud API endpoint matrix

Generated from the official OpenAPI schema on 2026-09-21.
Source: https://api-ru.iiko.services/api-docs/docs

Operations inventoried: **328** across **327** paths.

Status semantics:

- `BLOCKED`: adapter and contract test exist, but no successful live account probe has been recorded;
- `NOT_IMPLEMENTED`: endpoint is classified but not implemented in the current stage;
- `SUPPORTED` is intentionally absent until a successful live probe.

| Method | Endpoint | Official domain | Status | Planned stage | Summary |
|---|---|---|---|---|---|
| `POST` | `/api/1/access_token` | Authorization | `BLOCKED` | 4 | Retrieve session key for API user. |
| `POST` | `/api/1/cancel_causes` | Dictionaries | `BLOCKED` | 4 | Delivery cancel causes. |
| `POST` | `/api/1/cities` | Addresses | `NOT_IMPLEMENTED` | later | Cities. |
| `POST` | `/api/1/combo` | Menu | `NOT_IMPLEMENTED` | 4 | Get combos info |
| `POST` | `/api/1/combo/calculate` | Menu | `NOT_IMPLEMENTED` | 4 | Calculate combo price |
| `POST` | `/api/1/commands/status` | Operations | `NOT_IMPLEMENTED` | later | Get status of command. |
| `POST` | `/api/1/deliveries/add_items` | Deliveries: Create and update | `NOT_IMPLEMENTED` | 10 | Add order items. |
| `POST` | `/api/1/deliveries/add_payments` | Deliveries: Create and update | `NOT_IMPLEMENTED` | 10 | Add order payments. |
| `POST` | `/api/1/deliveries/by_delivery_date_and_phone` | Deliveries: Retrieve | `NOT_IMPLEMENTED` | 10 | Retrieve list of orders by telephone number, dates and revision. |
| `POST` | `/api/1/deliveries/by_delivery_date_and_source_key_and_filter` | Deliveries: Retrieve | `NOT_IMPLEMENTED` | 10 | Search orders by search text and additional filters (date, problem, statuses and other). |
| `POST` | `/api/1/deliveries/by_delivery_date_and_status` | Deliveries: Retrieve | `NOT_IMPLEMENTED` | 10 | Retrieve list of orders by statuses and dates. |
| `POST` | `/api/1/deliveries/by_id` | Deliveries: Retrieve | `NOT_IMPLEMENTED` | 10 | Retrieve orders by IDs. |
| `POST` | `/api/1/deliveries/by_revision` | Deliveries: Retrieve | `NOT_IMPLEMENTED` | 10 | Retrieve list of orders changed from the time revision was passed. |
| `POST` | `/api/1/deliveries/cancel` | Deliveries: Create and update | `NOT_IMPLEMENTED` | 10 | Cancel delivery order. |
| `POST` | `/api/1/deliveries/cancel_confirmation` | Deliveries: Create and update | `NOT_IMPLEMENTED` | 10 | Cancel delivery confirmation. |
| `POST` | `/api/1/deliveries/change_comment` | Deliveries: Create and update | `NOT_IMPLEMENTED` | 10 | Change delivery comment. |
| `POST` | `/api/1/deliveries/change_complete_before` | Deliveries: Create and update | `NOT_IMPLEMENTED` | 10 | Change time when client wants the order to be delivered. |
| `POST` | `/api/1/deliveries/change_delivery_point` | Deliveries: Create and update | `NOT_IMPLEMENTED` | 10 | Change order's delivery point information. |
| `POST` | `/api/1/deliveries/change_driver_info` | Deliveries: Create and update | `NOT_IMPLEMENTED` | 10 | Change driver info. |
| `POST` | `/api/1/deliveries/change_external_data` | Deliveries: Create and update | `NOT_IMPLEMENTED` | 10 | Change delivery external data. |
| `POST` | `/api/1/deliveries/change_operator` | Deliveries: Create and update | `NOT_IMPLEMENTED` | 10 | Assign/change the order operator. |
| `POST` | `/api/1/deliveries/change_payments` | Deliveries: Create and update | `NOT_IMPLEMENTED` | 10 | Change order's payments. |
| `POST` | `/api/1/deliveries/change_service_type` | Deliveries: Create and update | `NOT_IMPLEMENTED` | 10 | Change order's delivery type. |
| `POST` | `/api/1/deliveries/close` | Deliveries: Create and update | `NOT_IMPLEMENTED` | 10 | Close order. |
| `POST` | `/api/1/deliveries/confirm` | Deliveries: Create and update | `NOT_IMPLEMENTED` | 10 | Confirm delivery. |
| `POST` | `/api/1/deliveries/create` | Deliveries: Create and update | `NOT_IMPLEMENTED` | 10 | Create delivery. |
| `POST` | `/api/1/deliveries/drafts/by_filter` | Drafts | `NOT_IMPLEMENTED` | later | Retrieve order drafts list by parameters. |
| `POST` | `/api/1/deliveries/drafts/by_id` | Drafts | `NOT_IMPLEMENTED` | later | Retrieve order draft by ID. |
| `POST` | `/api/1/deliveries/drafts/commit` | Drafts | `NOT_IMPLEMENTED` | later | Admit order draft changes and send them to Front. |
| `POST` | `/api/1/deliveries/drafts/create` | Drafts | `NOT_IMPLEMENTED` | later | Create delivery order draft. |
| `POST` | `/api/1/deliveries/drafts/delete` | Drafts | `NOT_IMPLEMENTED` | later | Delete order draft. |
| `POST` | `/api/1/deliveries/drafts/lock` | Drafts | `NOT_IMPLEMENTED` | later | Lock order draft. |
| `POST` | `/api/1/deliveries/drafts/save` | Drafts | `NOT_IMPLEMENTED` | later | Update existing delivery order draft. |
| `POST` | `/api/1/deliveries/drafts/unlock` | Drafts | `NOT_IMPLEMENTED` | later | Unlock order draft. |
| `POST` | `/api/1/deliveries/history/by_delivery_date_and_phone` | Deliveries: Retrieve | `NOT_IMPLEMENTED` | 10 | Retrieve list of history orders by telephone number, dates and revision. |
| `POST` | `/api/1/deliveries/order_types` | Dictionaries | `BLOCKED` | 4 | Order types. |
| `POST` | `/api/1/deliveries/print_delivery_bill` | Deliveries: Create and update | `NOT_IMPLEMENTED` | 10 | Print delivery bill. |
| `POST` | `/api/1/deliveries/update_order_courier` | Deliveries: Create and update | `NOT_IMPLEMENTED` | 10 | Update order courier. |
| `POST` | `/api/1/deliveries/update_order_delivery_status` | Deliveries: Create and update | `NOT_IMPLEMENTED` | 10 | Update delivery status. |
| `POST` | `/api/1/deliveries/update_order_payments` | Deliveries: Create and update, Deprecated | `NOT_IMPLEMENTED` | 10 | Update order payment details. |
| `POST` | `/api/1/deliveries/update_order_problem` | Deliveries: Create and update | `NOT_IMPLEMENTED` | 10 | Update order problem. |
| `POST` | `/api/1/deliveries/update_tracking_link` | Deliveries: Create and update | `NOT_IMPLEMENTED` | 10 | Update tracking link of an order. |
| `POST` | `/api/1/delivery_restrictions` | Delivery restrictions | `NOT_IMPLEMENTED` | 10 | Retrieve list of delivery restrictions. |
| `POST` | `/api/1/delivery_restrictions/allowed` | Delivery restrictions | `NOT_IMPLEMENTED` | 10 | Get suitable terminal groups for delivery restrictions. |
| `POST` | `/api/1/discounts` | Dictionaries | `BLOCKED` | 4 | Discounts / surcharges. |
| `POST` | `/api/1/employees/couriers` | Employees | `NOT_IMPLEMENTED` | 8 | Returns list of all employees which are delivery drivers in specified restaurants. |
| `POST` | `/api/1/employees/couriers/active_location` | Employees | `NOT_IMPLEMENTED` | 8 | Returns list of all active (courier session is opened) courier's locations which are delivery drivers in specified restaurants. |
| `POST` | `/api/1/employees/couriers/active_location/by_terminal` | Employees | `NOT_IMPLEMENTED` | 8 | Returns list of all active (courier session is opened) courier's locations which are delivery drivers in specified restaurant and are clocked in on specified delivery terminal. |
| `POST` | `/api/1/employees/couriers/by_role` | Employees | `NOT_IMPLEMENTED` | 8 | Returns list of all employees which are delivery drivers in specified restaurants, and checks whether each employee has passed role. |
| `POST` | `/api/1/employees/couriers/locations/by_time_offset` | Employees | `NOT_IMPLEMENTED` | 8 | Method of obtaining drivers' coordinates history. |
| `POST` | `/api/1/employees/info` | Employees | `NOT_IMPLEMENTED` | 8 | Returns employee info. |
| `POST` | `/api/1/employees/shift/clockin` | Employees | `NOT_IMPLEMENTED` | 8 | Open personal session. |
| `POST` | `/api/1/employees/shift/clockout` | Employees | `NOT_IMPLEMENTED` | 8 | Close personal session. |
| `POST` | `/api/1/employees/shift/is_open` | Employees | `NOT_IMPLEMENTED` | 8 | Check if personal session is open. |
| `POST` | `/api/1/employees/shifts/by_courier` | Employees | `NOT_IMPLEMENTED` | 8 | Get terminal groups where employee session is opened. |
| `POST` | `/api/1/loyalty/iiko/calculate` | Discounts and promotions | `NOT_IMPLEMENTED` | 10 | Calculate checkin. |
| `POST` | `/api/1/loyalty/iiko/check_sms_sending_possibility` | Messages | `NOT_IMPLEMENTED` | later | Check sms sending possibility. |
| `POST` | `/api/1/loyalty/iiko/check_sms_status` | Messages | `NOT_IMPLEMENTED` | later | Check SMS status. |
| `POST` | `/api/1/loyalty/iiko/coupons/by_series` | Discounts and promotions | `NOT_IMPLEMENTED` | 10 | Get non-activated coupons |
| `POST` | `/api/1/loyalty/iiko/coupons/info` | Discounts and promotions | `NOT_IMPLEMENTED` | 10 | Get coupon info. |
| `POST` | `/api/1/loyalty/iiko/coupons/series` | Discounts and promotions | `NOT_IMPLEMENTED` | 10 | Get coupon series with non-activated coupons. |
| `POST` | `/api/1/loyalty/iiko/customer/card/add` | Customers | `NOT_IMPLEMENTED` | 10 | Add card. |
| `POST` | `/api/1/loyalty/iiko/customer/card/remove` | Customers | `NOT_IMPLEMENTED` | 10 | Delete card. |
| `POST` | `/api/1/loyalty/iiko/customer/create_or_update` | Customers | `NOT_IMPLEMENTED` | 10 | Create or update customer. |
| `POST` | `/api/1/loyalty/iiko/customer/info` | Customers | `NOT_IMPLEMENTED` | 10 | Get customer info. |
| `POST` | `/api/1/loyalty/iiko/customer/program/add` | Customers | `NOT_IMPLEMENTED` | 10 | Add customer to program. |
| `POST` | `/api/1/loyalty/iiko/customer/transactions/by_date` | Report | `NOT_IMPLEMENTED` | 5/6/7 | Get transaction report by period. |
| `POST` | `/api/1/loyalty/iiko/customer/transactions/by_revision` | Report | `NOT_IMPLEMENTED` | 5/6/7 | Get transaction report by revision. |
| `POST` | `/api/1/loyalty/iiko/customer/wallet/cancel_hold` | Customers | `NOT_IMPLEMENTED` | 10 | Cancel hold money. |
| `POST` | `/api/1/loyalty/iiko/customer/wallet/chargeoff` | Customers | `NOT_IMPLEMENTED` | 10 | Withdraw balance. |
| `POST` | `/api/1/loyalty/iiko/customer/wallet/hold` | Customers | `NOT_IMPLEMENTED` | 10 | Hold money. |
| `POST` | `/api/1/loyalty/iiko/customer/wallet/topup` | Customers | `NOT_IMPLEMENTED` | 10 | Refill balance. |
| `POST` | `/api/1/loyalty/iiko/customer_category` | Customer categories | `NOT_IMPLEMENTED` | 10 | Get customer categories. |
| `POST` | `/api/1/loyalty/iiko/customer_category/add` | Customer categories | `NOT_IMPLEMENTED` | 10 | Add category for customer. |
| `POST` | `/api/1/loyalty/iiko/customer_category/remove` | Customer categories | `NOT_IMPLEMENTED` | 10 | Remove category for customer. |
| `POST` | `/api/1/loyalty/iiko/delete_customers` | Customers | `NOT_IMPLEMENTED` | 10 | Logical deletion of customers. |
| `POST` | `/api/1/loyalty/iiko/get_counters` | Customers | `NOT_IMPLEMENTED` | 10 | Get counters. |
| `POST` | `/api/1/loyalty/iiko/manual_condition` | Discounts and promotions | `NOT_IMPLEMENTED` | 10 | Get manual conditions. |
| `POST` | `/api/1/loyalty/iiko/message/send_email` | Messages | `NOT_IMPLEMENTED` | later | Send email. |
| `POST` | `/api/1/loyalty/iiko/message/send_sms` | Messages | `NOT_IMPLEMENTED` | later | Send sms. |
| `POST` | `/api/1/loyalty/iiko/program` | Discounts and promotions | `NOT_IMPLEMENTED` | 10 | Get programs. |
| `POST` | `/api/1/loyalty/iiko/restore_customers` | Customers | `NOT_IMPLEMENTED` | 10 | Logical recovery of customers. |
| `POST` | `/api/1/marketing_sources` | Marketing sources | `BLOCKED` | 4 | Marketing sources. |
| `POST` | `/api/1/nomenclature` | Menu | `BLOCKED` | 4 | Menu. |
| `POST` | `/api/1/notifications/send` | Notifications | `NOT_IMPLEMENTED` | later | Send notification to external systems. |
| `POST` | `/api/1/order/add_customer` | Orders | `NOT_IMPLEMENTED` | 5/6/7 | Add customer to order. |
| `POST` | `/api/1/order/add_items` | Orders | `NOT_IMPLEMENTED` | 5/6/7 | Add order items. |
| `POST` | `/api/1/order/add_payments` | Orders | `NOT_IMPLEMENTED` | 5/6/7 | Add order payments. |
| `POST` | `/api/1/order/by_id` | Orders | `NOT_IMPLEMENTED` | 5/6/7 | Retrieve orders by IDs. |
| `POST` | `/api/1/order/by_table` | Orders | `NOT_IMPLEMENTED` | 5/6/7 | Retrieve orders by tables. |
| `POST` | `/api/1/order/cancel` | Orders | `NOT_IMPLEMENTED` | 5/6/7 | Cancel the table order. |
| `POST` | `/api/1/order/change_external_data` | Orders | `NOT_IMPLEMENTED` | 5/6/7 | Change table order external_data. |
| `POST` | `/api/1/order/change_payments` | Orders | `NOT_IMPLEMENTED` | 5/6/7 | Change table order's payments. |
| `POST` | `/api/1/order/close` | Orders | `NOT_IMPLEMENTED` | 5/6/7 | Close order. |
| `POST` | `/api/1/order/create` | Orders | `NOT_IMPLEMENTED` | 5/6/7 | Create order. |
| `POST` | `/api/1/order/init_by_posOrder` | Orders | `NOT_IMPLEMENTED` | 5/6/7 | Init orders, created on POS, by POS orders. |
| `POST` | `/api/1/order/init_by_table` | Orders | `NOT_IMPLEMENTED` | 5/6/7 | Init orders, created on POS, by tables. |
| `POST` | `/api/1/order/print_bill` | Deliveries: Create and update | `NOT_IMPLEMENTED` | 10 | Print bill. |
| `GET` | `/api/1/organizations` | Deprecated | `NOT_IMPLEMENTED` | later | Returns organizations available to api-login user. |
| `POST` | `/api/1/organizations` | Organizations | `BLOCKED` | 4 | Returns organizations available to api-login user. |
| `POST` | `/api/1/organizations/settings` | Organizations | `NOT_IMPLEMENTED` | 4 | Returns available to api-login user organizations specified settings. |
| `POST` | `/api/1/payment_types` | Dictionaries | `BLOCKED` | 4 | Payment types. |
| `POST` | `/api/1/regions` | Addresses | `NOT_IMPLEMENTED` | later | Regions. |
| `POST` | `/api/1/removal_types` | Dictionaries | `BLOCKED` | 4 | Removal types (reasons for deletion). |
| `POST` | `/api/1/reserve/add_items` | Banquets/reserves | `NOT_IMPLEMENTED` | 10 | Add order items. |
| `POST` | `/api/1/reserve/add_payments` | Banquets/reserves | `NOT_IMPLEMENTED` | 10 | Add order payments. |
| `POST` | `/api/1/reserve/available_organizations` | Banquets/reserves | `NOT_IMPLEMENTED` | 10 | Returns all organizations of current account (determined by Authorization request header) for which banquet/reserve booking are available. |
| `POST` | `/api/1/reserve/available_restaurant_sections` | Banquets/reserves | `BLOCKED` | 4 | Returns all restaurant sections of specified terminal groups, for which banquet/reserve booking are available. |
| `POST` | `/api/1/reserve/available_terminal_groups` | Banquets/reserves | `NOT_IMPLEMENTED` | 10 | Returns all terminal groups of specified organizations, for which banquet/reserve booking are available. |
| `POST` | `/api/1/reserve/cancel` | Banquets/reserves | `NOT_IMPLEMENTED` | 10 | Cancel reservation due to some reason. |
| `POST` | `/api/1/reserve/change_estimated_start_time` | Banquets/reserves | `NOT_IMPLEMENTED` | 10 | Change reserve/banquet estimated start time. |
| `POST` | `/api/1/reserve/change_items` | Banquets/reserves | `NOT_IMPLEMENTED` | 10 | Change order items. |
| `POST` | `/api/1/reserve/change_tables` | Banquets/reserves | `NOT_IMPLEMENTED` | 10 | Change reserve/banquet tables. |
| `POST` | `/api/1/reserve/create` | Banquets/reserves | `NOT_IMPLEMENTED` | 10 | Create banquet/reserve. |
| `POST` | `/api/1/reserve/restaurant_sections_workload` | Banquets/reserves | `NOT_IMPLEMENTED` | 10 | Returns all banquets/reserves for passed restaurant sections. |
| `POST` | `/api/1/reserve/status_by_id` | Banquets/reserves | `NOT_IMPLEMENTED` | 10 | Retrieve banquets/reserves statuses by IDs. |
| `POST` | `/api/1/stop_lists` | Menu | `BLOCKED` | 4 | Out-of-stock items. |
| `POST` | `/api/1/stop_lists/add` | Menu | `NOT_IMPLEMENTED` | 4 | Add items to out-of-stock list. (You should have extra rights to use this method). |
| `POST` | `/api/1/stop_lists/check` | Menu | `NOT_IMPLEMENTED` | 4 | Check items in out-of-stock list. |
| `POST` | `/api/1/stop_lists/clear` | Menu | `NOT_IMPLEMENTED` | 4 | Clear out-of-stock list. (You should have extra rights to use this method). |
| `POST` | `/api/1/stop_lists/remove` | Menu | `NOT_IMPLEMENTED` | 4 | Remove items from out-of-stock list. (You should have extra rights to use this method). |
| `POST` | `/api/1/streets/by_city` | Addresses | `NOT_IMPLEMENTED` | later | Streets by city. |
| `POST` | `/api/1/streets/by_id` | Addresses | `NOT_IMPLEMENTED` | later | Streets by id or by classifierId. |
| `POST` | `/api/1/terminal_groups` | Terminal groups | `BLOCKED` | 4 | Method that returns information on groups of delivery terminals. |
| `POST` | `/api/1/terminal_groups/awake` | Terminal groups | `NOT_IMPLEMENTED` | 4 | Awake terminal groups from sleep mode. |
| `POST` | `/api/1/terminal_groups/is_alive` | Terminal groups | `BLOCKED` | 4 | Returns information on availability of group of terminals. |
| `POST` | `/api/1/tips_types` | Dictionaries | `BLOCKED` | 4 | Get tips types for api-login`s rms group. |
| `POST` | `/api/1/webhooks/settings` | Webhooks | `NOT_IMPLEMENTED` | 5 | Get webhooks settings for specified organization and authorized API login. |
| `POST` | `/api/1/webhooks/update_settings` | Webhooks | `NOT_IMPLEMENTED` | 5 | Update webhooks settings for specified organization and authorized API login. |
| `POST` | `/api/2/menu` | Menu | `NOT_IMPLEMENTED` | 4 | External menus with price categories. |
| `POST` | `/api/2/menu/by_id` | Menu | `NOT_IMPLEMENTED` | 4 | Retrieve external menu by ID. |
| `POST` | `/api/employees/v1/attendance-type/list` | Employees.Attendance | `NOT_IMPLEMENTED` | 8 | List attendance types |
| `POST` | `/api/employees/v1/attendance/create` | Employees.Attendance | `NOT_IMPLEMENTED` | 8 | Create employee attendance |
| `POST` | `/api/employees/v1/attendance/delete` | Employees.Attendance | `NOT_IMPLEMENTED` | 8 | Delete employee attendance |
| `POST` | `/api/employees/v1/attendance/list` | Employees.Attendance | `NOT_IMPLEMENTED` | 8 | List employee attendances |
| `POST` | `/api/employees/v1/attendance/update` | Employees.Attendance | `NOT_IMPLEMENTED` | 8 | Update employee attendance |
| `POST` | `/api/employees/v1/employee/create` | Employees.Employees | `NOT_IMPLEMENTED` | 8 | Create employee |
| `POST` | `/api/employees/v1/employee/fire` | Employees.Employees | `NOT_IMPLEMENTED` | 8 | Fire employees |
| `POST` | `/api/employees/v1/employee/get` | Employees.Employees | `NOT_IMPLEMENTED` | 8 | Get employee |
| `POST` | `/api/employees/v1/employee/list` | Employees.Employees | `NOT_IMPLEMENTED` | 8 | List of employees |
| `POST` | `/api/employees/v1/employee/restore` | Employees.Employees | `NOT_IMPLEMENTED` | 8 | Restore employee |
| `POST` | `/api/employees/v1/employee/update` | Employees.Employees | `NOT_IMPLEMENTED` | 8 | Update employee |
| `POST` | `/api/employees/v1/positions/get` | Employees.Positions | `NOT_IMPLEMENTED` | 8 | Get employee position by identifier |
| `POST` | `/api/employees/v1/positions/list` | Employees.Positions | `NOT_IMPLEMENTED` | 8 | List employee positions |
| `POST` | `/api/finance/v1/account-posting/list` | Finance.AccountPosting | `NOT_IMPLEMENTED` | later | Account postings |
| `POST` | `/api/finance/v1/account-type/list` | Finance.AccountType | `NOT_IMPLEMENTED` | later | List of account types |
| `POST` | `/api/finance/v1/account/create` | Finance.Account | `NOT_IMPLEMENTED` | later | Create financial account |
| `POST` | `/api/finance/v1/account/delete` | Finance.Account | `NOT_IMPLEMENTED` | later | Delete financial account |
| `POST` | `/api/finance/v1/account/get` | Finance.Account | `NOT_IMPLEMENTED` | later | Get financial account |
| `POST` | `/api/finance/v1/account/list` | Finance.Account | `NOT_IMPLEMENTED` | later | List of financial accounts |
| `POST` | `/api/finance/v1/account/restore` | Finance.Account | `NOT_IMPLEMENTED` | later | Restore financial account |
| `POST` | `/api/finance/v1/account/update` | Finance.Account | `NOT_IMPLEMENTED` | later | Update financial account |
| `POST` | `/api/finance/v1/account_transactions/list` | Finance.AccountTransactions | `NOT_IMPLEMENTED` | later | Get account transactions |
| `POST` | `/api/finance/v1/balance-sheet/list` | Finance.BalanceSheet | `NOT_IMPLEMENTED` | later | Balance sheet |
| `POST` | `/api/finance/v1/cash-flow-category/create` | Finance.CashFlowCategory | `NOT_IMPLEMENTED` | later | Create cash flow category |
| `POST` | `/api/finance/v1/cash-flow-category/delete` | Finance.CashFlowCategory | `NOT_IMPLEMENTED` | later | Delete cash flow category |
| `POST` | `/api/finance/v1/cash-flow-category/get` | Finance.CashFlowCategory | `NOT_IMPLEMENTED` | later | Get cash flow category |
| `POST` | `/api/finance/v1/cash-flow-category/list` | Finance.CashFlowCategory | `NOT_IMPLEMENTED` | later | List of cash flow categories |
| `POST` | `/api/finance/v1/cash-flow-category/restore` | Finance.CashFlowCategory | `NOT_IMPLEMENTED` | later | Restore cash flow category |
| `POST` | `/api/finance/v1/cash-flow-category/update` | Finance.CashFlowCategory | `NOT_IMPLEMENTED` | later | Update cash flow category |
| `POST` | `/api/finance/v1/chart-of-accounts/list` | Finance.ChartOfAccounts | `NOT_IMPLEMENTED` | later | Chart of accounts |
| `POST` | `/api/finance/v1/document_transactions/list` | Finance.DocumentTransactions | `NOT_IMPLEMENTED` | later | Get document transactions |
| `POST` | `/api/finance/v1/incoming_service/cancel` | Finance.IncomingService | `NOT_IMPLEMENTED` | later | Cancel incoming service act draft |
| `POST` | `/api/finance/v1/incoming_service/create` | Finance.IncomingService | `NOT_IMPLEMENTED` | later | Create incoming service act |
| `POST` | `/api/finance/v1/incoming_service/get` | Finance.IncomingService | `NOT_IMPLEMENTED` | later | Get incoming service act |
| `POST` | `/api/finance/v1/incoming_service/list` | Finance.IncomingService | `NOT_IMPLEMENTED` | later | Export incoming service acts |
| `POST` | `/api/finance/v1/incoming_service/post` | Finance.IncomingService | `NOT_IMPLEMENTED` | later | Post incoming service act |
| `POST` | `/api/finance/v1/incoming_service/unpost` | Finance.IncomingService | `NOT_IMPLEMENTED` | later | Unpost incoming service act |
| `POST` | `/api/finance/v1/incoming_service/update` | Finance.IncomingService | `NOT_IMPLEMENTED` | later | Edit incoming service act |
| `POST` | `/api/finance/v1/item-category/list` | Finance.Directories | `NOT_IMPLEMENTED` | later | Get a list of fiscal categories |
| `POST` | `/api/finance/v1/outgoing_service/cancel` | Finance.OutgoingService | `NOT_IMPLEMENTED` | later | Cancel outgoing service act draft |
| `POST` | `/api/finance/v1/outgoing_service/create` | Finance.OutgoingService | `NOT_IMPLEMENTED` | later | Create outgoing service act |
| `POST` | `/api/finance/v1/outgoing_service/get` | Finance.OutgoingService | `NOT_IMPLEMENTED` | later | Get outgoing service act |
| `POST` | `/api/finance/v1/outgoing_service/list` | Finance.OutgoingService | `NOT_IMPLEMENTED` | later | Export outgoing service acts |
| `POST` | `/api/finance/v1/outgoing_service/post` | Finance.OutgoingService | `NOT_IMPLEMENTED` | later | Post outgoing service act |
| `POST` | `/api/finance/v1/outgoing_service/unpost` | Finance.OutgoingService | `NOT_IMPLEMENTED` | later | Unpost outgoing service act |
| `POST` | `/api/finance/v1/outgoing_service/update` | Finance.OutgoingService | `NOT_IMPLEMENTED` | later | Edit outgoing service act |
| `POST` | `/api/finance/v1/tax-category/list` | Finance.Directories | `NOT_IMPLEMENTED` | later | Get a list of tax categories |
| `POST` | `/api/inventory/v1/accounting_categories/get` | Inventory.Catalogs | `NOT_IMPLEMENTED` | 9 | Get accounting category by ID |
| `POST` | `/api/inventory/v1/accounting_categories/list` | Inventory.Catalogs | `NOT_IMPLEMENTED` | 9 | Get accounting categories list |
| `POST` | `/api/inventory/v1/conceptions/get` | Inventory.Catalogs | `NOT_IMPLEMENTED` | 9 | Get conception by ID |
| `POST` | `/api/inventory/v1/conceptions/list` | Inventory.Catalogs | `NOT_IMPLEMENTED` | 9 | Get conceptions list |
| `POST` | `/api/inventory/v1/costings/calculate` | Inventory.OutgoingInvoices | `NOT_IMPLEMENTED` | 9 | Get cost prices for nomenclature items |
| `POST` | `/api/inventory/v1/counteragents/list` | Inventory.Counteragents | `NOT_IMPLEMENTED` | 9 | Get counteragents list |
| `POST` | `/api/inventory/v1/disassemble_document/cancel` | Inventory.DisassembleDocument | `NOT_IMPLEMENTED` | 9 | Cancel disassemble document draft |
| `POST` | `/api/inventory/v1/disassemble_document/create` | Inventory.DisassembleDocument | `NOT_IMPLEMENTED` | 9 | Create disassemble document |
| `POST` | `/api/inventory/v1/disassemble_document/get` | Inventory.DisassembleDocument | `NOT_IMPLEMENTED` | 9 | Get disassemble document by identifier |
| `POST` | `/api/inventory/v1/disassemble_document/list` | Inventory.DisassembleDocument | `NOT_IMPLEMENTED` | 9 | Export disassemble documents |
| `POST` | `/api/inventory/v1/disassemble_document/post` | Inventory.DisassembleDocument | `NOT_IMPLEMENTED` | 9 | Post disassemble document |
| `POST` | `/api/inventory/v1/disassemble_document/unpost` | Inventory.DisassembleDocument | `NOT_IMPLEMENTED` | 9 | Unpost disassemble document |
| `POST` | `/api/inventory/v1/disassemble_document/update` | Inventory.DisassembleDocument | `NOT_IMPLEMENTED` | 9 | Edit disassemble document |
| `POST` | `/api/inventory/v1/incoming_inventory/cancel` | Inventory.IncomingInventory | `NOT_IMPLEMENTED` | 9 | Cancel inventory draft |
| `POST` | `/api/inventory/v1/incoming_inventory/create` | Inventory.IncomingInventory | `NOT_IMPLEMENTED` | 9 | Create inventory |
| `POST` | `/api/inventory/v1/incoming_inventory/get` | Inventory.IncomingInventory | `NOT_IMPLEMENTED` | 9 | Get inventory |
| `POST` | `/api/inventory/v1/incoming_inventory/list` | Inventory.IncomingInventory | `NOT_IMPLEMENTED` | 9 | Export inventories |
| `POST` | `/api/inventory/v1/incoming_inventory/post` | Inventory.IncomingInventory | `NOT_IMPLEMENTED` | 9 | Post inventory |
| `POST` | `/api/inventory/v1/incoming_inventory/unpost` | Inventory.IncomingInventory | `NOT_IMPLEMENTED` | 9 | Unpost inventory |
| `POST` | `/api/inventory/v1/incoming_inventory/update` | Inventory.IncomingInventory | `NOT_IMPLEMENTED` | 9 | Edit inventory |
| `POST` | `/api/inventory/v1/incoming_invoice/cancel` | Inventory.IncomingInvoices | `NOT_IMPLEMENTED` | 9 | Cancel incoming invoice draft |
| `POST` | `/api/inventory/v1/incoming_invoice/create` | Inventory.IncomingInvoices | `NOT_IMPLEMENTED` | 9 | Create incoming invoice |
| `POST` | `/api/inventory/v1/incoming_invoice/get` | Inventory.IncomingInvoices | `NOT_IMPLEMENTED` | 9 | Get incoming invoice by identifier |
| `POST` | `/api/inventory/v1/incoming_invoice/list` | Inventory.IncomingInvoices | `NOT_IMPLEMENTED` | 9 | Export incoming invoices |
| `POST` | `/api/inventory/v1/incoming_invoice/modify/add_payment` | Inventory.IncomingInvoices | `NOT_IMPLEMENTED` | 9 | Pay incoming invoice |
| `POST` | `/api/inventory/v1/incoming_invoice/patch/set_payment_date` | Inventory.IncomingInvoices | `NOT_IMPLEMENTED` | 9 | Set payment date for incoming invoice |
| `POST` | `/api/inventory/v1/incoming_invoice/post` | Inventory.IncomingInvoices | `NOT_IMPLEMENTED` | 9 | Post incoming invoice |
| `POST` | `/api/inventory/v1/incoming_invoice/unpost` | Inventory.IncomingInvoices | `NOT_IMPLEMENTED` | 9 | Unpost incoming invoice |
| `POST` | `/api/inventory/v1/incoming_invoice/update` | Inventory.IncomingInvoices | `NOT_IMPLEMENTED` | 9 | Edit incoming invoice |
| `POST` | `/api/inventory/v1/incoming_returned_invoice/cancel` | Inventory.IncomingReturnedInvoice | `NOT_IMPLEMENTED` | 9 | Cancel incoming returned invoice draft |
| `POST` | `/api/inventory/v1/incoming_returned_invoice/create` | Inventory.IncomingReturnedInvoice | `NOT_IMPLEMENTED` | 9 | Create incoming returned invoice |
| `POST` | `/api/inventory/v1/incoming_returned_invoice/get` | Inventory.IncomingReturnedInvoice | `NOT_IMPLEMENTED` | 9 | Get incoming returned invoice by identifier |
| `POST` | `/api/inventory/v1/incoming_returned_invoice/list` | Inventory.IncomingReturnedInvoice | `NOT_IMPLEMENTED` | 9 | Export incoming returned invoices |
| `POST` | `/api/inventory/v1/incoming_returned_invoice/post` | Inventory.IncomingReturnedInvoice | `NOT_IMPLEMENTED` | 9 | Post incoming returned invoice |
| `POST` | `/api/inventory/v1/incoming_returned_invoice/unpost` | Inventory.IncomingReturnedInvoice | `NOT_IMPLEMENTED` | 9 | Unpost incoming returned invoice |
| `POST` | `/api/inventory/v1/incoming_returned_invoice/update` | Inventory.IncomingReturnedInvoice | `NOT_IMPLEMENTED` | 9 | Edit incoming returned invoice |
| `POST` | `/api/inventory/v1/internal_transfer/cancel` | Inventory.InternalTransfer | `NOT_IMPLEMENTED` | 9 | Cancel internal transfer act draft |
| `POST` | `/api/inventory/v1/internal_transfer/create` | Inventory.InternalTransfer | `NOT_IMPLEMENTED` | 9 | Create internal transfer act |
| `POST` | `/api/inventory/v1/internal_transfer/get` | Inventory.InternalTransfer | `NOT_IMPLEMENTED` | 9 | Get internal transfer act by identifier |
| `POST` | `/api/inventory/v1/internal_transfer/list` | Inventory.InternalTransfer | `NOT_IMPLEMENTED` | 9 | Export internal transfer acts |
| `POST` | `/api/inventory/v1/internal_transfer/post` | Inventory.InternalTransfer | `NOT_IMPLEMENTED` | 9 | Post internal transfer act |
| `POST` | `/api/inventory/v1/internal_transfer/unpost` | Inventory.InternalTransfer | `NOT_IMPLEMENTED` | 9 | Unpost internal transfer act |
| `POST` | `/api/inventory/v1/internal_transfer/update` | Inventory.InternalTransfer | `NOT_IMPLEMENTED` | 9 | Edit internal transfer act |
| `POST` | `/api/inventory/v1/measure_units/get` | Inventory.Catalogs | `NOT_IMPLEMENTED` | 9 | Get measure unit by ID |
| `POST` | `/api/inventory/v1/measure_units/list` | Inventory.Catalogs | `NOT_IMPLEMENTED` | 9 | Get measure units list |
| `POST` | `/api/inventory/v1/organizations/settings/list` | Inventory.Organizations | `NOT_IMPLEMENTED` | 9 | Get corporation settings |
| `POST` | `/api/inventory/v1/organizations/tree` | Inventory.Organizations | `NOT_IMPLEMENTED` | 9 | Get terminal groups list |
| `POST` | `/api/inventory/v1/outgoing_invoice/cancel` | Inventory.OutgoingInvoices | `NOT_IMPLEMENTED` | 9 | Cancel outgoing invoice draft |
| `POST` | `/api/inventory/v1/outgoing_invoice/create` | Inventory.OutgoingInvoices | `NOT_IMPLEMENTED` | 9 | Create outgoing invoice |
| `POST` | `/api/inventory/v1/outgoing_invoice/get` | Inventory.OutgoingInvoices | `NOT_IMPLEMENTED` | 9 | Get outgoing invoice by ID |
| `POST` | `/api/inventory/v1/outgoing_invoice/list` | Inventory.OutgoingInvoices | `NOT_IMPLEMENTED` | 9 | Export outgoing invoices |
| `POST` | `/api/inventory/v1/outgoing_invoice/modify/add_payment` | Inventory.OutgoingInvoices | `NOT_IMPLEMENTED` | 9 | Pay outgoing invoice |
| `POST` | `/api/inventory/v1/outgoing_invoice/patch/set_payment_date` | Inventory.OutgoingInvoices | `NOT_IMPLEMENTED` | 9 | Set payment date for outgoing invoice |
| `POST` | `/api/inventory/v1/outgoing_invoice/post` | Inventory.OutgoingInvoices | `NOT_IMPLEMENTED` | 9 | Post outgoing invoice |
| `POST` | `/api/inventory/v1/outgoing_invoice/unpost` | Inventory.OutgoingInvoices | `NOT_IMPLEMENTED` | 9 | Unpost outgoing invoice |
| `POST` | `/api/inventory/v1/outgoing_invoice/update` | Inventory.OutgoingInvoices | `NOT_IMPLEMENTED` | 9 | Edit outgoing invoice |
| `POST` | `/api/inventory/v1/payment_types/get` | Inventory.Catalogs | `NOT_IMPLEMENTED` | 9 | Get payment type by ID |
| `POST` | `/api/inventory/v1/payment_types/list` | Inventory.Catalogs | `NOT_IMPLEMENTED` | 9 | Get payment types list |
| `POST` | `/api/inventory/v1/production_document/cancel` | Inventory.ProductionDocument | `NOT_IMPLEMENTED` | 9 | Cancel production document draft |
| `POST` | `/api/inventory/v1/production_document/create` | Inventory.ProductionDocument | `NOT_IMPLEMENTED` | 9 | Create production document |
| `POST` | `/api/inventory/v1/production_document/get` | Inventory.ProductionDocument | `NOT_IMPLEMENTED` | 9 | Get production document |
| `POST` | `/api/inventory/v1/production_document/list` | Inventory.ProductionDocument | `NOT_IMPLEMENTED` | 9 | Export production documents |
| `POST` | `/api/inventory/v1/production_document/post` | Inventory.ProductionDocument | `NOT_IMPLEMENTED` | 9 | Post production document |
| `POST` | `/api/inventory/v1/production_document/unpost` | Inventory.ProductionDocument | `NOT_IMPLEMENTED` | 9 | Unpost production document |
| `POST` | `/api/inventory/v1/production_document/update` | Inventory.ProductionDocument | `NOT_IMPLEMENTED` | 9 | Edit production document |
| `POST` | `/api/inventory/v1/returned_invoice/cancel` | Inventory.ReturnedInvoice | `NOT_IMPLEMENTED` | 9 | Cancel returned invoice draft |
| `POST` | `/api/inventory/v1/returned_invoice/create` | Inventory.ReturnedInvoice | `NOT_IMPLEMENTED` | 9 | Create returned invoice |
| `POST` | `/api/inventory/v1/returned_invoice/get` | Inventory.ReturnedInvoice | `NOT_IMPLEMENTED` | 9 | Get returned invoice by identifier |
| `POST` | `/api/inventory/v1/returned_invoice/list` | Inventory.ReturnedInvoice | `NOT_IMPLEMENTED` | 9 | Export returned invoices |
| `POST` | `/api/inventory/v1/returned_invoice/post` | Inventory.ReturnedInvoice | `NOT_IMPLEMENTED` | 9 | Post returned invoice |
| `POST` | `/api/inventory/v1/returned_invoice/unpost` | Inventory.ReturnedInvoice | `NOT_IMPLEMENTED` | 9 | Unpost returned invoice |
| `POST` | `/api/inventory/v1/returned_invoice/update` | Inventory.ReturnedInvoice | `NOT_IMPLEMENTED` | 9 | Edit returned invoice |
| `POST` | `/api/inventory/v1/sales_document/cancel` | Inventory.SalesDocument | `NOT_IMPLEMENTED` | 9 | Cancel sales document draft |
| `POST` | `/api/inventory/v1/sales_document/create` | Inventory.SalesDocument | `NOT_IMPLEMENTED` | 9 | Create sales document |
| `POST` | `/api/inventory/v1/sales_document/get` | Inventory.SalesDocument | `NOT_IMPLEMENTED` | 9 | Get sales document |
| `POST` | `/api/inventory/v1/sales_document/list` | Inventory.SalesDocument | `NOT_IMPLEMENTED` | 9 | Export sales documents |
| `POST` | `/api/inventory/v1/sales_document/post` | Inventory.SalesDocument | `NOT_IMPLEMENTED` | 9 | Post sales document |
| `POST` | `/api/inventory/v1/sales_document/unpost` | Inventory.SalesDocument | `NOT_IMPLEMENTED` | 9 | Unpost sales document |
| `POST` | `/api/inventory/v1/sales_document/update` | Inventory.SalesDocument | `NOT_IMPLEMENTED` | 9 | Edit sales document |
| `POST` | `/api/inventory/v1/stock_balance/list` | Inventory.StockBalance | `NOT_IMPLEMENTED` | 9 | Get stock balances by stores |
| `POST` | `/api/inventory/v1/stores/list` | Inventory.Organizations | `NOT_IMPLEMENTED` | 9 | Get stores list |
| `POST` | `/api/inventory/v1/transformation_document/cancel` | Inventory.TransformationDocument | `NOT_IMPLEMENTED` | 9 | Cancel transformation document draft |
| `POST` | `/api/inventory/v1/transformation_document/create` | Inventory.TransformationDocument | `NOT_IMPLEMENTED` | 9 | Create transformation document |
| `POST` | `/api/inventory/v1/transformation_document/get` | Inventory.TransformationDocument | `NOT_IMPLEMENTED` | 9 | Get transformation document |
| `POST` | `/api/inventory/v1/transformation_document/list` | Inventory.TransformationDocument | `NOT_IMPLEMENTED` | 9 | List transformation documents |
| `POST` | `/api/inventory/v1/transformation_document/post` | Inventory.TransformationDocument | `NOT_IMPLEMENTED` | 9 | Post transformation document |
| `POST` | `/api/inventory/v1/transformation_document/unpost` | Inventory.TransformationDocument | `NOT_IMPLEMENTED` | 9 | Unpost transformation document |
| `POST` | `/api/inventory/v1/transformation_document/update` | Inventory.TransformationDocument | `NOT_IMPLEMENTED` | 9 | Edit transformation document |
| `POST` | `/api/inventory/v1/writeoff_document/cancel` | Inventory.WriteoffDocument | `NOT_IMPLEMENTED` | 9 | Cancel write-off document draft |
| `POST` | `/api/inventory/v1/writeoff_document/create` | Inventory.WriteoffDocument | `NOT_IMPLEMENTED` | 9 | Create write-off document |
| `POST` | `/api/inventory/v1/writeoff_document/get` | Inventory.WriteoffDocument | `NOT_IMPLEMENTED` | 9 | Get write-off document by identifier |
| `POST` | `/api/inventory/v1/writeoff_document/list` | Inventory.WriteoffDocument | `NOT_IMPLEMENTED` | 9 | Export write-off documents |
| `POST` | `/api/inventory/v1/writeoff_document/post` | Inventory.WriteoffDocument | `NOT_IMPLEMENTED` | 9 | Post write-off document |
| `POST` | `/api/inventory/v1/writeoff_document/unpost` | Inventory.WriteoffDocument | `NOT_IMPLEMENTED` | 9 | Unpost write-off document |
| `POST` | `/api/inventory/v1/writeoff_document/update` | Inventory.WriteoffDocument | `NOT_IMPLEMENTED` | 9 | Edit write-off document |
| `POST` | `/api/licenses/v2/list` | Licenses | `NOT_IMPLEMENTED` | later | Get license list information for the API login. |
| `POST` | `/api/menu/v3/by_id` | Menu | `NOT_IMPLEMENTED` | 4 | Retrieve external menu V3 by ID. |
| `POST` | `/api/nomenclature/v1/allergen-group/list` | Nomenclature.Directories | `NOT_IMPLEMENTED` | 4/9 | Get a list of allergen groups |
| `POST` | `/api/nomenclature/v1/amount-unit/list` | Nomenclature.Directories | `NOT_IMPLEMENTED` | 4/9 | Get a list of amount units |
| `POST` | `/api/nomenclature/v1/assembly-chart/create` | Nomenclature.AssemblyChart | `NOT_IMPLEMENTED` | 4/9 | Create an assembly chart |
| `POST` | `/api/nomenclature/v1/assembly-chart/delete` | Nomenclature.AssemblyChart | `NOT_IMPLEMENTED` | 4/9 | Delete an assembly chart |
| `POST` | `/api/nomenclature/v1/assembly-chart/get` | Nomenclature.AssemblyChart | `NOT_IMPLEMENTED` | 4/9 | Get an assembly chart by ID |
| `POST` | `/api/nomenclature/v1/assembly-chart/list` | Nomenclature.AssemblyChart | `NOT_IMPLEMENTED` | 4/9 | Get a list of assembly charts by product |
| `POST` | `/api/nomenclature/v1/assembly-chart/update` | Nomenclature.AssemblyChart | `NOT_IMPLEMENTED` | 4/9 | Update an assembly chart |
| `POST` | `/api/nomenclature/v1/container/list` | Nomenclature.Directories | `NOT_IMPLEMENTED` | 4/9 | Get a list of containers |
| `POST` | `/api/nomenclature/v1/custom-category/list` | Nomenclature.Directories | `NOT_IMPLEMENTED` | 4/9 | Get a list of custom categories |
| `POST` | `/api/nomenclature/v1/group/create` | Nomenclature.NomenclatureGroup | `NOT_IMPLEMENTED` | 4/9 | Create a nomenclature group |
| `POST` | `/api/nomenclature/v1/group/delete` | Nomenclature.NomenclatureGroup | `NOT_IMPLEMENTED` | 4/9 | Delete nomenclature groups |
| `POST` | `/api/nomenclature/v1/group/list` | Nomenclature.NomenclatureGroup | `NOT_IMPLEMENTED` | 4/9 | Get a list of nomenclature groups |
| `POST` | `/api/nomenclature/v1/group/restore` | Nomenclature.NomenclatureGroup | `NOT_IMPLEMENTED` | 4/9 | Restore nomenclature groups |
| `POST` | `/api/nomenclature/v1/group/update` | Nomenclature.NomenclatureGroup | `NOT_IMPLEMENTED` | 4/9 | Update a nomenclature group |
| `POST` | `/api/nomenclature/v1/menu/list` | Nomenclature.Directories | `NOT_IMPLEMENTED` | 4/9 | Get a list of menu sections |
| `POST` | `/api/nomenclature/v1/modifier-schema/list` | Nomenclature.Directories | `NOT_IMPLEMENTED` | 4/9 | Get a list of modifier schemas |
| `POST` | `/api/nomenclature/v1/nomenclature/category/create` | Nomenclature.NomenclatureCategory | `NOT_IMPLEMENTED` | 4/9 | Create a product category |
| `POST` | `/api/nomenclature/v1/nomenclature/category/delete` | Nomenclature.NomenclatureCategory | `NOT_IMPLEMENTED` | 4/9 | Delete a product category |
| `POST` | `/api/nomenclature/v1/nomenclature/category/list` | Nomenclature.NomenclatureCategory | `NOT_IMPLEMENTED` | 4/9 | Get a list of product categories |
| `POST` | `/api/nomenclature/v1/nomenclature/category/restore` | Nomenclature.NomenclatureCategory | `NOT_IMPLEMENTED` | 4/9 | Restore a product category |
| `POST` | `/api/nomenclature/v1/nomenclature/category/update` | Nomenclature.NomenclatureCategory | `NOT_IMPLEMENTED` | 4/9 | Update a product category |
| `POST` | `/api/nomenclature/v1/place-type/list` | Nomenclature.Directories | `NOT_IMPLEMENTED` | 4/9 | Get a list of preparation place types |
| `POST` | `/api/nomenclature/v1/producer/list` | Nomenclature.Directories | `NOT_IMPLEMENTED` | 4/9 | Get a list of producers |
| `POST` | `/api/nomenclature/v1/product-scale/create` | Nomenclature.NomenclatureProductScale | `NOT_IMPLEMENTED` | 4/9 | Create a product size scale |
| `POST` | `/api/nomenclature/v1/product-scale/delete` | Nomenclature.NomenclatureProductScale | `NOT_IMPLEMENTED` | 4/9 | Delete a product size scale |
| `POST` | `/api/nomenclature/v1/product-scale/get` | Nomenclature.NomenclatureProductScale | `NOT_IMPLEMENTED` | 4/9 | Get a product size scale by ID |
| `POST` | `/api/nomenclature/v1/product-scale/list` | Nomenclature.NomenclatureProductScale | `NOT_IMPLEMENTED` | 4/9 | Get a list of product size scales |
| `POST` | `/api/nomenclature/v1/product-scale/update` | Nomenclature.NomenclatureProductScale | `NOT_IMPLEMENTED` | 4/9 | Update a product size scale |
| `POST` | `/api/nomenclature/v1/product-size/list` | Nomenclature.Directories | `NOT_IMPLEMENTED` | 4/9 | Get a list of product sizes |
| `POST` | `/api/nomenclature/v1/product-tag/list` | Nomenclature.Directories | `NOT_IMPLEMENTED` | 4/9 | Get a list of product tags |
| `POST` | `/api/nomenclature/v1/product/create` | Nomenclature.NomenclatureProduct | `NOT_IMPLEMENTED` | 4/9 | Create a product |
| `POST` | `/api/nomenclature/v1/product/delete` | Nomenclature.NomenclatureProduct | `NOT_IMPLEMENTED` | 4/9 | Delete products |
| `POST` | `/api/nomenclature/v1/product/list` | Nomenclature.NomenclatureProduct | `NOT_IMPLEMENTED` | 4/9 | Get a list of products |
| `POST` | `/api/nomenclature/v1/product/restore` | Nomenclature.NomenclatureProduct | `NOT_IMPLEMENTED` | 4/9 | Restore products |
| `POST` | `/api/nomenclature/v1/product/update` | Nomenclature.NomenclatureProduct | `NOT_IMPLEMENTED` | 4/9 | Update a product |
| `POST` | `/api/nomenclature/v1/product/update_barcodes` | Nomenclature.NomenclatureProduct | `NOT_IMPLEMENTED` | 4/9 | Update product barcodes |
| `POST` | `/api/nomenclature/v2/assembly-chart/create` | Nomenclature.AssemblyChart | `NOT_IMPLEMENTED` | 4/9 | Create an assembly chart (v2) |
| `POST` | `/api/nomenclature/v2/assembly-chart/delete` | Nomenclature.AssemblyChart | `NOT_IMPLEMENTED` | 4/9 | Delete an assembly chart (v2) |
| `POST` | `/api/nomenclature/v2/assembly-chart/get` | Nomenclature.AssemblyChart | `NOT_IMPLEMENTED` | 4/9 | Get an assembly chart by ID (v2) |
| `POST` | `/api/nomenclature/v2/assembly-chart/list` | Nomenclature.AssemblyChart | `NOT_IMPLEMENTED` | 4/9 | Get a list of assembly charts by product (v2) |
| `POST` | `/api/nomenclature/v2/assembly-chart/update` | Nomenclature.AssemblyChart | `NOT_IMPLEMENTED` | 4/9 | Update an assembly chart (v2) |
| `POST` | `/api/nomenclature/v2/group/create` | Nomenclature.NomenclatureGroup | `NOT_IMPLEMENTED` | 4/9 | Create a nomenclature group (v2) |
| `POST` | `/api/nomenclature/v2/group/delete` | Nomenclature.NomenclatureGroup | `NOT_IMPLEMENTED` | 4/9 | Delete nomenclature groups (v2) |
| `POST` | `/api/nomenclature/v2/group/list` | Nomenclature.NomenclatureGroup | `NOT_IMPLEMENTED` | 4/9 | Get a list of nomenclature groups (v2) |
| `POST` | `/api/nomenclature/v2/group/restore` | Nomenclature.NomenclatureGroup | `NOT_IMPLEMENTED` | 4/9 | Restore nomenclature groups (v2) |
| `POST` | `/api/nomenclature/v2/group/update` | Nomenclature.NomenclatureGroup | `NOT_IMPLEMENTED` | 4/9 | Update a nomenclature group (v2) |
| `POST` | `/api/nomenclature/v2/product/create` | Nomenclature.NomenclatureProduct | `NOT_IMPLEMENTED` | 4/9 | Create a product (v2) |
| `POST` | `/api/nomenclature/v2/product/delete` | Nomenclature.NomenclatureProduct | `NOT_IMPLEMENTED` | 4/9 | Delete products (v2) |
| `POST` | `/api/nomenclature/v2/product/list` | Nomenclature.NomenclatureProduct | `NOT_IMPLEMENTED` | 4/9 | Get a list of products (v2) |
| `POST` | `/api/nomenclature/v2/product/restore` | Nomenclature.NomenclatureProduct | `NOT_IMPLEMENTED` | 4/9 | Restore products (v2) |
| `POST` | `/api/nomenclature/v2/product/update` | Nomenclature.NomenclatureProduct | `NOT_IMPLEMENTED` | 4/9 | Update a product (v2) |
| `POST` | `/api/nomenclature/v2/product/update_barcodes` | Nomenclature.NomenclatureProduct | `NOT_IMPLEMENTED` | 4/9 | Update product barcodes (v2) |
| `POST` | `/api/v2/access_token` | Authorization | `BLOCKED` | 4 | Retrieve session key for API access (v2) |

## Stage 4 live gate

The Stage 4 adapter must not move an endpoint or capability to `SUPPORTED` until
that exact call succeeds against the selected iiko organization and its response
shape is recorded without credentials, tokens or business payload values.

Regenerate after an official schema update:

```bash
cd backend
.venv/bin/python tools/generate_iiko_api_matrix.py \
  --openapi /path/to/iiko-openapi.json \
  --output docs/integrations/iiko-api-matrix.md \
  --generated-on 2026-09-21
```
