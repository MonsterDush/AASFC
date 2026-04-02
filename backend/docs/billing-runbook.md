# Axelio Billing Runbook

## Что проверять после оплаты
1. В `venue_billing_transaction` появилась запись `PAYMENT`.
2. После callback статус стал `SUCCEEDED`.
3. В `venue_billing_event` появилось `ROBOKASSA_PAYMENT_SUCCEEDED`.
4. В `venue_billing_state` обновился `paid_until`.
5. Owner получил уведомление об успешной оплате.

## Что проверять после ручного продления
1. В `venue_billing_transaction` появилась запись `EXTEND`.
2. В `venue_billing_event` появилось `BILLING_EXTENDED_MANUALLY`.
3. `paid_until` сдвинулся на нужный срок.

## Что проверять при возврате
1. В `venue_billing_transaction` появилась запись `REFUND`.
2. В `venue_billing_event` появилось `BILLING_REFUND_CREATED`.
3. Доступ автоматически не отзывается.
4. При необходимости доступ отзывается отдельным ручным действием администратора.

## Если деньги списались, а доступ не продлился
1. Открыть `/admin/billing/reconciliation`.
2. Найти `SUCCEEDED_NOT_APPLIED`, `AMOUNT_MISMATCH` или `INVALID_SIGNATURE`.
3. Проверить `venue_billing_transaction`, `venue_billing_event`, `venue_billing_state`.
4. Проверить `journalctl -u axelio-api-prod --since "30 minutes ago"`.
5. При необходимости выполнить ручное продление и зафиксировать инцидент.

## Если callback пришёл повторно
1. Проверить событие `ROBOKASSA_RESULT_DUPLICATE`.
2. Убедиться, что период доступа не продлился повторно.
3. Убедиться, что transaction осталась в `SUCCEEDED` без повторного применения.

## Если checkout висит слишком долго
1. Открыть `/admin/billing/reconciliation`.
2. Найти `STALE_PENDING_CHECKOUT`.
3. Проверить, был ли реальный платёж.
4. При отсутствии платежа — дождаться автоистечения или оформить новый checkout.

## Базовые команды логов
- API prod: `sudo journalctl -u axelio-api-prod -f`
- API dev: `sudo journalctl -u axelio-api-dev -f`
- Billing jobs prod: `sudo journalctl -u axelio-billing-jobs-prod.service -n 100 --no-pager`
- Billing jobs dev: `sudo journalctl -u axelio-billing-jobs-dev.service -n 100 --no-pager`
