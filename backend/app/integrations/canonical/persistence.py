from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.integrations.canonical.dto import (
    CanonicalAttendance,
    CanonicalCustomerIdentity,
    CanonicalEmployee,
    CanonicalInventory,
    CanonicalOrder,
    CanonicalProduct,
    CanonicalProductGroup,
    CanonicalPurchase,
    CanonicalRecipe,
    CanonicalStockMovement,
    CanonicalStockSnapshot,
    CanonicalSupplier,
    CanonicalTerminal,
    CanonicalVenue,
    CanonicalWarehouse,
    CanonicalWriteoff,
)
from app.models.pos_canonical import (
    POSEmployee,
    POSOrder,
    POSOrderDiscount,
    POSOrderEvent,
    POSOrderItem,
    POSPayment,
    POSProduct,
    POSProductGroup,
    POSRefund,
    POSTerminal,
    POSVenue,
)
from app.models.pos_inventory import (
    POSAttendance,
    POSCustomerIdentity,
    POSInventoryDocument,
    POSInventoryItem,
    POSPurchaseDocument,
    POSPurchaseItem,
    POSRecipe,
    POSRecipeItem,
    POSStockMovement,
    POSStockSnapshot,
    POSSupplier,
    POSWarehouse,
    POSWriteoff,
    POSWriteoffItem,
)

if TYPE_CHECKING:
    from app.integrations.normalization.contracts import NormalizationContext


def persist_canonical_batch(
    db: Session,
    values: Iterable[object],
    *,
    context: NormalizationContext,
) -> int:
    rows = list(values)
    groups = [item for item in rows if isinstance(item, CanonicalProductGroup)]
    for item in groups:
        _upsert_group(db, item, context=context)
    db.flush()
    for item in groups:
        if item.parent_external_id:
            row = _find(db, POSProductGroup, context.integration_connection_id, item.external_id)
            parent = _find(db, POSProductGroup, context.integration_connection_id, item.parent_external_id)
            row.parent_group_id = parent.id if parent is not None else None

    for item in rows:
        if isinstance(item, CanonicalVenue):
            _upsert_venue(db, item, context=context)
        elif isinstance(item, CanonicalTerminal):
            _upsert_terminal(db, item, context=context)
        elif isinstance(item, CanonicalEmployee):
            _upsert_employee(db, item, context=context)
        elif isinstance(item, CanonicalProduct):
            _upsert_product(db, item, context=context)
        elif isinstance(item, CanonicalWarehouse):
            _upsert_warehouse(db, item, context=context)
        elif isinstance(item, CanonicalSupplier):
            _upsert_supplier(db, item, context=context)
        elif isinstance(item, CanonicalCustomerIdentity):
            _upsert_customer_identity(db, item, context=context)
    db.flush()

    for item in rows:
        if isinstance(item, CanonicalOrder):
            _upsert_order(db, item, context=context)
        elif isinstance(item, CanonicalRecipe):
            _upsert_recipe(db, item, context=context)
        elif isinstance(item, CanonicalStockSnapshot):
            _upsert_stock_snapshot(db, item, context=context)
        elif isinstance(item, CanonicalStockMovement):
            _upsert_stock_movement(db, item, context=context)
        elif isinstance(item, CanonicalPurchase):
            _upsert_purchase(db, item, context=context)
        elif isinstance(item, CanonicalWriteoff):
            _upsert_writeoff(db, item, context=context)
        elif isinstance(item, CanonicalInventory):
            _upsert_inventory(db, item, context=context)
        elif isinstance(item, CanonicalAttendance):
            _upsert_attendance(db, item, context=context)
    db.flush()
    return len(rows)


def _find(db: Session, model, connection_id: int, external_id: str):
    return db.execute(
        select(model).where(model.connection_id == int(connection_id), model.external_id == str(external_id))
    ).scalar_one_or_none()


def _upsert_venue(db: Session, value: CanonicalVenue, *, context: NormalizationContext) -> POSVenue:
    row = _find(db, POSVenue, context.integration_connection_id, value.external_id)
    if row is None:
        row = POSVenue(connection_id=context.integration_connection_id, external_id=value.external_id)
        db.add(row)
    row.organization_id = None
    row.venue_id = context.venue_id
    row.source = context.provider.value
    row.name = value.name
    row.address = value.address
    row.timezone = value.timezone
    row.active = value.active
    return row


def _upsert_terminal(db: Session, value: CanonicalTerminal, *, context: NormalizationContext) -> POSTerminal:
    row = _find(db, POSTerminal, context.integration_connection_id, value.external_id)
    if row is None:
        row = POSTerminal(connection_id=context.integration_connection_id, external_id=value.external_id)
        db.add(row)
    row.venue_id = context.venue_id
    row.source = context.provider.value
    row.name = value.name
    row.active = value.active
    return row


def _upsert_employee(db: Session, value: CanonicalEmployee, *, context: NormalizationContext) -> POSEmployee:
    row = _find(db, POSEmployee, context.integration_connection_id, value.external_id)
    if row is None:
        row = POSEmployee(connection_id=context.integration_connection_id, external_id=value.external_id)
        db.add(row)
    row.name = value.name
    row.position_name = value.position_name
    row.active = value.active
    return row


def _upsert_group(db: Session, value: CanonicalProductGroup, *, context: NormalizationContext) -> POSProductGroup:
    row = _find(db, POSProductGroup, context.integration_connection_id, value.external_id)
    if row is None:
        row = POSProductGroup(connection_id=context.integration_connection_id, external_id=value.external_id)
        db.add(row)
    row.name = value.name
    row.kind = value.kind
    row.active = value.active
    return row


def _upsert_product(db: Session, value: CanonicalProduct, *, context: NormalizationContext) -> POSProduct:
    row = _find(db, POSProduct, context.integration_connection_id, value.external_id)
    if row is None:
        row = POSProduct(connection_id=context.integration_connection_id, external_id=value.external_id)
        db.add(row)
    row.name = value.name
    row.code = value.code
    row.barcode = value.barcode
    row.type = value.type
    row.unit = value.unit
    row.active = value.active
    group = (
        _find(db, POSProductGroup, context.integration_connection_id, value.group_external_id)
        if value.group_external_id
        else None
    )
    category = (
        _find(db, POSProductGroup, context.integration_connection_id, value.category_external_id)
        if value.category_external_id
        else None
    )
    row.group_id = group.id if group is not None else None
    row.category_id = category.id if category is not None else None
    return row


def _upsert_order(db: Session, value: CanonicalOrder, *, context: NormalizationContext) -> POSOrder:
    row = _find(db, POSOrder, context.integration_connection_id, value.external_id)
    if row is None:
        row = POSOrder(connection_id=context.integration_connection_id, external_id=value.external_id)
        db.add(row)
    row.organization_id = None
    row.venue_id = context.venue_id
    row.source = context.provider.value
    row.order_number = value.order_number
    row.check_number = value.check_number
    row.business_date = value.business_date
    row.calendar_date = value.calendar_date
    row.opened_at = value.opened_at
    row.closed_at = value.closed_at
    row.status = value.status
    row.order_type = value.order_type
    row.table_external_id = value.table_external_id
    row.table_name = value.table_name
    row.guest_count = value.guest_count
    row.subtotal = value.subtotal
    row.discount_amount = value.discount_amount
    row.service_charge = value.service_charge
    row.delivery_fee = value.delivery_fee
    row.total_amount = value.total_amount
    row.refund_amount = value.refund_amount
    row.currency = value.currency
    row.source_created_at = value.source_created_at
    row.source_updated_at = value.source_updated_at
    row.synced_at = datetime.now(timezone.utc)
    cashier = (
        _find(db, POSEmployee, context.integration_connection_id, value.cashier_external_id)
        if value.cashier_external_id
        else None
    )
    waiter = (
        _find(db, POSEmployee, context.integration_connection_id, value.waiter_external_id)
        if value.waiter_external_id
        else None
    )
    row.cashier_pos_employee_id = cashier.id if cashier is not None else None
    row.waiter_pos_employee_id = waiter.id if waiter is not None else None
    customer = (
        _find(db, POSCustomerIdentity, context.integration_connection_id, value.customer_external_id)
        if value.customer_external_id
        else None
    )
    row.customer_pos_identity_id = customer.id if customer is not None else None
    db.flush()

    _delete_stale_children(
        db,
        POSOrderItem,
        order_id=int(row.id),
        identity_column=POSOrderItem.external_id,
        identities={item.external_id for item in value.items},
    )
    _delete_stale_children(
        db,
        POSOrderEvent,
        order_id=int(row.id),
        identity_column=POSOrderEvent.external_id,
        identities={event.external_id for event in value.events},
    )
    _delete_stale_children(
        db,
        POSPayment,
        order_id=int(row.id),
        identity_column=POSPayment.external_id,
        identities={payment.external_id for payment in value.payments},
    )
    _delete_stale_children(
        db,
        POSRefund,
        order_id=int(row.id),
        identity_column=POSRefund.external_id,
        identities={refund.external_id for refund in value.refunds},
    )
    _delete_stale_children(
        db,
        POSOrderDiscount,
        order_id=int(row.id),
        identity_column=POSOrderDiscount.external_discount_id,
        identities={discount.external_id for discount in value.discounts},
    )

    item_rows = {}
    for item in value.items:
        product = (
            _find(db, POSProduct, context.integration_connection_id, item.product_external_id)
            if item.product_external_id
            else None
        )
        child = db.execute(
            select(POSOrderItem).where(POSOrderItem.order_id == row.id, POSOrderItem.external_id == item.external_id)
        ).scalar_one_or_none()
        if child is None:
            child = POSOrderItem(order_id=row.id, external_id=item.external_id)
            db.add(child)
        child.product_id = product.id if product is not None else None
        child.product_name_snapshot = item.product_name
        child.category_name_snapshot = item.category_name
        child.quantity = item.quantity
        child.base_price = item.base_price
        child.final_price = item.final_price
        child.gross_amount = item.gross_amount
        child.discount_amount = item.discount_amount
        child.net_amount = item.net_amount
        child.cost_amount = item.cost_amount
        child.is_modifier = item.is_modifier
        child.is_deleted = item.is_deleted
        child.is_refunded = item.is_refunded
        child.parent_item_id = None
        db.flush()
        item_rows[item.external_id] = child
    for item in value.items:
        if item.parent_external_id and item.external_id in item_rows:
            parent = item_rows.get(item.parent_external_id)
            item_rows[item.external_id].parent_item_id = parent.id if parent is not None else None

    for event in value.events:
        child = db.execute(
            select(POSOrderEvent).where(POSOrderEvent.order_id == row.id, POSOrderEvent.external_id == event.external_id)
        ).scalar_one_or_none()
        if child is None:
            child = POSOrderEvent(order_id=row.id, external_id=event.external_id)
            db.add(child)
        child.event_type = event.event_type
        child.occurred_at = event.occurred_at
        child.details_json = dict(event.details)

    for payment in value.payments:
        child = db.execute(
            select(POSPayment).where(POSPayment.order_id == row.id, POSPayment.external_id == payment.external_id)
        ).scalar_one_or_none()
        if child is None:
            child = POSPayment(order_id=row.id, external_id=payment.external_id)
            db.add(child)
        child.canonical_type = payment.canonical_type
        child.source_type = payment.source_type
        child.amount = payment.amount
        child.paid_at = payment.paid_at

    for refund in value.refunds:
        employee = (
            _find(db, POSEmployee, context.integration_connection_id, refund.employee_external_id)
            if refund.employee_external_id
            else None
        )
        child = db.execute(
            select(POSRefund).where(POSRefund.order_id == row.id, POSRefund.external_id == refund.external_id)
        ).scalar_one_or_none()
        if child is None:
            child = POSRefund(order_id=row.id, external_id=refund.external_id)
            db.add(child)
        child.amount = refund.amount
        child.reason = refund.reason
        child.refunded_at = refund.refunded_at
        child.pos_employee_id = employee.id if employee is not None else None

    for discount in value.discounts:
        employee = (
            _find(db, POSEmployee, context.integration_connection_id, discount.employee_external_id)
            if discount.employee_external_id
            else None
        )
        child = db.execute(
            select(POSOrderDiscount).where(
                POSOrderDiscount.order_id == row.id,
                POSOrderDiscount.external_discount_id == discount.external_id,
            )
        ).scalar_one_or_none()
        if child is None:
            child = POSOrderDiscount(order_id=row.id, external_discount_id=discount.external_id)
            db.add(child)
        child.source_name = discount.source_name
        child.canonical_type = discount.canonical_type
        child.amount = discount.amount
        child.percent = discount.percent
        child.employee_id = employee.id if employee is not None else None
    return row


def _linked(db: Session, model, context: NormalizationContext, external_id: str | None):
    if not external_id:
        return None
    with db.no_autoflush:
        return _find(db, model, context.integration_connection_id, external_id)


def _upsert_recipe(db: Session, value: CanonicalRecipe, *, context: NormalizationContext) -> POSRecipe:
    row = _find(db, POSRecipe, context.integration_connection_id, value.external_id)
    if row is None:
        row = POSRecipe(connection_id=context.integration_connection_id, external_id=value.external_id)
        db.add(row)
    product = _linked(db, POSProduct, context, value.product_external_id)
    row.product_id = product.id if product is not None else None
    row.valid_from = value.valid_from
    row.valid_to = value.valid_to
    row.yield_quantity = value.yield_quantity
    row.yield_unit = value.yield_unit
    row.source_updated_at = value.source_updated_at
    row.synced_at = datetime.now(timezone.utc)
    db.flush()
    _delete_document_children(
        db,
        POSRecipeItem,
        parent_column=POSRecipeItem.recipe_id,
        parent_id=int(row.id),
        identity_column=POSRecipeItem.external_id,
        identities={item.external_id for item in value.items},
    )
    for item in value.items:
        child = db.execute(
            select(POSRecipeItem).where(
                POSRecipeItem.recipe_id == int(row.id),
                POSRecipeItem.external_id == item.external_id,
            )
        ).scalar_one_or_none()
        if child is None:
            child = POSRecipeItem(recipe_id=int(row.id), external_id=item.external_id)
            db.add(child)
        ingredient = _linked(db, POSProduct, context, item.ingredient_external_id)
        child.ingredient_id = ingredient.id if ingredient is not None else None
        child.quantity = item.quantity
        child.unit = item.unit
    return row


def _upsert_warehouse(db: Session, value: CanonicalWarehouse, *, context: NormalizationContext) -> POSWarehouse:
    row = _find(db, POSWarehouse, context.integration_connection_id, value.external_id)
    if row is None:
        row = POSWarehouse(connection_id=context.integration_connection_id, external_id=value.external_id)
        db.add(row)
    row.venue_id = context.venue_id
    row.name = value.name
    row.type = value.type
    row.active = value.active
    return row


def _upsert_stock_snapshot(
    db: Session, value: CanonicalStockSnapshot, *, context: NormalizationContext
) -> POSStockSnapshot:
    row = _find(db, POSStockSnapshot, context.integration_connection_id, value.external_id)
    if row is None:
        row = POSStockSnapshot(connection_id=context.integration_connection_id, external_id=value.external_id)
        db.add(row)
    warehouse = _linked(db, POSWarehouse, context, value.warehouse_external_id)
    product = _linked(db, POSProduct, context, value.product_external_id)
    row.warehouse_id = warehouse.id if warehouse is not None else None
    row.product_id = product.id if product is not None else None
    row.quantity = value.quantity
    row.cost_per_unit = value.cost_per_unit
    row.total_cost = value.total_cost
    row.snapshot_at = value.snapshot_at
    row.synced_at = datetime.now(timezone.utc)
    return row


def _upsert_stock_movement(
    db: Session, value: CanonicalStockMovement, *, context: NormalizationContext
) -> POSStockMovement:
    row = _find(db, POSStockMovement, context.integration_connection_id, value.external_id)
    if row is None:
        row = POSStockMovement(connection_id=context.integration_connection_id, external_id=value.external_id)
        db.add(row)
    warehouse = _linked(db, POSWarehouse, context, value.warehouse_external_id)
    product = _linked(db, POSProduct, context, value.product_external_id)
    row.warehouse_id = warehouse.id if warehouse is not None else None
    row.product_id = product.id if product is not None else None
    row.movement_type = value.movement_type
    row.quantity = value.quantity
    row.unit = value.unit
    row.cost_per_unit = value.cost_per_unit
    row.total_cost = value.total_cost
    row.occurred_at = value.occurred_at
    row.source_reason = value.source_reason
    row.source_updated_at = value.source_updated_at
    row.synced_at = datetime.now(timezone.utc)
    return row


def _upsert_supplier(db: Session, value: CanonicalSupplier, *, context: NormalizationContext) -> POSSupplier:
    row = _find(db, POSSupplier, context.integration_connection_id, value.external_id)
    if row is None:
        row = POSSupplier(connection_id=context.integration_connection_id, external_id=value.external_id)
        db.add(row)
    row.name = value.name
    row.active = value.active
    return row


def _upsert_purchase(db: Session, value: CanonicalPurchase, *, context: NormalizationContext) -> POSPurchaseDocument:
    row = _find(db, POSPurchaseDocument, context.integration_connection_id, value.external_id)
    if row is None:
        row = POSPurchaseDocument(connection_id=context.integration_connection_id, external_id=value.external_id)
        db.add(row)
    supplier = _linked(db, POSSupplier, context, value.supplier_external_id)
    warehouse = _linked(db, POSWarehouse, context, value.warehouse_external_id)
    row.supplier_id = supplier.id if supplier is not None else None
    row.warehouse_id = warehouse.id if warehouse is not None else None
    row.document_date = value.document_date
    row.document_number = value.document_number
    row.total_amount = value.total_amount
    row.status = value.status
    row.source_updated_at = value.source_updated_at
    row.synced_at = datetime.now(timezone.utc)
    db.flush()
    _delete_document_children(
        db,
        POSPurchaseItem,
        parent_column=POSPurchaseItem.document_id,
        parent_id=int(row.id),
        identity_column=POSPurchaseItem.external_id,
        identities={item.external_id for item in value.items},
    )
    for item in value.items:
        child = db.execute(
            select(POSPurchaseItem).where(
                POSPurchaseItem.document_id == int(row.id),
                POSPurchaseItem.external_id == item.external_id,
            )
        ).scalar_one_or_none()
        if child is None:
            child = POSPurchaseItem(document_id=int(row.id), external_id=item.external_id)
            db.add(child)
        product = _linked(db, POSProduct, context, item.product_external_id)
        child.product_id = product.id if product is not None else None
        child.quantity = item.quantity
        child.unit = item.unit
        child.price_per_unit = item.price_per_unit
        child.total_amount = item.total_amount
    return row


def _upsert_writeoff(db: Session, value: CanonicalWriteoff, *, context: NormalizationContext) -> POSWriteoff:
    row = _find(db, POSWriteoff, context.integration_connection_id, value.external_id)
    if row is None:
        row = POSWriteoff(connection_id=context.integration_connection_id, external_id=value.external_id)
        db.add(row)
    warehouse = _linked(db, POSWarehouse, context, value.warehouse_external_id)
    row.warehouse_id = warehouse.id if warehouse is not None else None
    row.document_date = value.document_date
    row.document_number = value.document_number
    row.canonical_reason = value.canonical_reason
    row.source_reason = value.source_reason
    row.total_amount = value.total_amount
    row.status = value.status
    row.source_updated_at = value.source_updated_at
    row.synced_at = datetime.now(timezone.utc)
    db.flush()
    _delete_document_children(
        db,
        POSWriteoffItem,
        parent_column=POSWriteoffItem.document_id,
        parent_id=int(row.id),
        identity_column=POSWriteoffItem.external_id,
        identities={item.external_id for item in value.items},
    )
    for item in value.items:
        child = db.execute(
            select(POSWriteoffItem).where(
                POSWriteoffItem.document_id == int(row.id),
                POSWriteoffItem.external_id == item.external_id,
            )
        ).scalar_one_or_none()
        if child is None:
            child = POSWriteoffItem(document_id=int(row.id), external_id=item.external_id)
            db.add(child)
        product = _linked(db, POSProduct, context, item.product_external_id)
        child.product_id = product.id if product is not None else None
        child.quantity = item.quantity
        child.unit = item.unit
        child.cost_per_unit = item.cost_per_unit
        child.total_amount = item.total_amount
    return row


def _upsert_inventory(db: Session, value: CanonicalInventory, *, context: NormalizationContext) -> POSInventoryDocument:
    row = _find(db, POSInventoryDocument, context.integration_connection_id, value.external_id)
    if row is None:
        row = POSInventoryDocument(connection_id=context.integration_connection_id, external_id=value.external_id)
        db.add(row)
    warehouse = _linked(db, POSWarehouse, context, value.warehouse_external_id)
    row.warehouse_id = warehouse.id if warehouse is not None else None
    row.document_date = value.document_date
    row.document_number = value.document_number
    row.status = value.status
    row.source_updated_at = value.source_updated_at
    row.synced_at = datetime.now(timezone.utc)
    db.flush()
    _delete_document_children(
        db,
        POSInventoryItem,
        parent_column=POSInventoryItem.document_id,
        parent_id=int(row.id),
        identity_column=POSInventoryItem.external_id,
        identities={item.external_id for item in value.items},
    )
    for item in value.items:
        child = db.execute(
            select(POSInventoryItem).where(
                POSInventoryItem.document_id == int(row.id),
                POSInventoryItem.external_id == item.external_id,
            )
        ).scalar_one_or_none()
        if child is None:
            child = POSInventoryItem(document_id=int(row.id), external_id=item.external_id)
            db.add(child)
        product = _linked(db, POSProduct, context, item.product_external_id)
        child.product_id = product.id if product is not None else None
        child.book_quantity = item.book_quantity
        child.actual_quantity = item.actual_quantity
        child.difference_quantity = item.difference_quantity
        child.cost_per_unit = item.cost_per_unit
        child.difference_cost = item.difference_cost
    return row


def _upsert_attendance(db: Session, value: CanonicalAttendance, *, context: NormalizationContext) -> POSAttendance:
    row = _find(db, POSAttendance, context.integration_connection_id, value.external_id)
    if row is None:
        row = POSAttendance(connection_id=context.integration_connection_id, external_id=value.external_id)
        db.add(row)
    employee = _linked(db, POSEmployee, context, value.employee_external_id)
    row.pos_employee_id = employee.id if employee is not None else None
    row.clocked_in_at = value.clocked_in_at
    row.clocked_out_at = value.clocked_out_at
    row.source_updated_at = value.source_updated_at
    row.synced_at = datetime.now(timezone.utc)
    return row


def _upsert_customer_identity(
    db: Session, value: CanonicalCustomerIdentity, *, context: NormalizationContext
) -> POSCustomerIdentity:
    row = _find(db, POSCustomerIdentity, context.integration_connection_id, value.external_id)
    if row is None:
        row = POSCustomerIdentity(connection_id=context.integration_connection_id, external_id=value.external_id)
        db.add(row)
    row.display_name = value.display_name
    row.source_updated_at = value.source_updated_at
    row.synced_at = datetime.now(timezone.utc)
    return row


def _delete_stale_children(db: Session, model, *, order_id: int, identity_column, identities: set[str]) -> None:
    statement = delete(model).where(model.order_id == int(order_id))
    if identities:
        statement = statement.where(identity_column.not_in(sorted(identities)))
    db.execute(statement)


def _delete_document_children(
    db: Session,
    model,
    *,
    parent_column,
    parent_id: int,
    identity_column,
    identities: set[str],
) -> None:
    statement = delete(model).where(parent_column == int(parent_id))
    if identities:
        statement = statement.where(identity_column.not_in(sorted(identities)))
    db.execute(statement)
