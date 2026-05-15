from __future__ import annotations

from collections import defaultdict
from datetime import datetime

ORDER_STATUS_LABELS = {
    'novo': 'Novo',
    'preparando': 'Preparando',
    'pronto': 'Pronto',
    'entregue': 'Entregue',
    'cancelado': 'Cancelado',
}

ACTIVE_ORDER_STATUSES = ('novo', 'preparando', 'pronto')
KITCHEN_ORDER_LIMIT = 100


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec='seconds')


def _format_created_at(value) -> str:
    if not value:
        return ''

    text = str(value)

    for candidate in (text, text.replace(' ', 'T')):
        try:
            return datetime.fromisoformat(candidate).strftime('%d/%m/%Y %H:%M')
        except ValueError:
            continue

    return text


def _decorate_orders(db, orders):
    orders = list(orders)

    if not orders:
        return []

    order_ids = [int(order['id']) for order in orders]
    placeholders = ', '.join('?' for _ in order_ids)

    item_rows = db.execute(
        f'''
        SELECT
            oi.id,
            oi.order_id,
            oi.product_id,
            COALESCE(NULLIF(oi.product_name_snapshot, ''), p.name, 'Item') AS name,
            oi.quantity,
            oi.unit_price
        FROM order_items oi
        LEFT JOIN products p ON p.id = oi.product_id
        WHERE oi.order_id IN ({placeholders})
        ORDER BY oi.order_id DESC, oi.id ASC
        ''',
        order_ids,
    ).fetchall()

    items_by_order = defaultdict(list)

    for item in item_rows:
        items_by_order[int(item['order_id'])].append(item)

    decorated = []

    for order in orders:
        decorated.append(
            {
                'order': order,
                'items': items_by_order[int(order['id'])],
                'status_label': ORDER_STATUS_LABELS.get(order['status'], order['status']),
                'created_at_display': _format_created_at(order['created_at']),
            }
        )

    return decorated


def create_order_from_cart(
    db,
    table_number: str,
    cart: list[dict],
    customer_name: str,
    notes: str | None = None,
) -> int:
    now = _now_iso()

    total = round(
        sum(float(item['price']) * int(item['quantity']) for item in cart),
        2,
    )

    try:
        cursor = db.execute(
            '''
            INSERT INTO orders (
                table_number,
                customer_name,
                status,
                notes,
                total_amount,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                str(table_number),
                customer_name,
                'novo',
                notes,
                total,
                now,
                now,
            ),
        )

        order_id = int(cursor.lastrowid)

        db.executemany(
            '''
            INSERT INTO order_items (
                order_id,
                product_id,
                product_name_snapshot,
                quantity,
                unit_price
            )
            VALUES (?, ?, ?, ?, ?)
            ''',
            [
                (
                    order_id,
                    int(item['product_id']),
                    str(item['name']),
                    int(item['quantity']),
                    float(item['price']),
                )
                for item in cart
            ],
        )

        db.commit()
        return order_id

    except Exception:
        db.rollback()
        raise


def list_orders_for_table(db, table_number: str):
    placeholders = ', '.join('?' for _ in ACTIVE_ORDER_STATUSES)

    orders = db.execute(
        f'''
        SELECT *
        FROM orders
        WHERE table_number = ?
          AND status IN ({placeholders})
        ORDER BY id DESC
        ''',
        (str(table_number), *ACTIVE_ORDER_STATUSES),
    ).fetchall()

    return _decorate_orders(db, orders)


def list_orders_for_kitchen(db):
    orders = db.execute(
        '''
        SELECT *
        FROM orders
        ORDER BY id DESC
        LIMIT ?
        ''',
        (KITCHEN_ORDER_LIMIT,),
    ).fetchall()

    return _decorate_orders(db, orders)


def get_kitchen_orders_signature(db) -> str:
    row = db.execute(
        '''
        SELECT
            COUNT(*) AS total_orders,
            COALESCE(MAX(id), 0) AS last_order_id,
            COALESCE(MAX(updated_at), '') AS last_update
        FROM orders
        '''
    ).fetchone()

    return f"{row['total_orders']}:{row['last_order_id']}:{row['last_update']}"


def update_order_status(db, order_id: int, status: str):
    if status not in ORDER_STATUS_LABELS:
        raise ValueError('Status inválido.')

    try:
        db.execute(
            '''
            UPDATE orders
            SET status = ?,
                updated_at = ?
            WHERE id = ?
            ''',
            (
                status,
                _now_iso(),
                order_id,
            ),
        )

        db.commit()

    except Exception:
        db.rollback()
        raise


def delete_all_orders(db):
    try:
        db.execute('DELETE FROM order_items')
        db.execute('DELETE FROM orders')
        db.commit()

    except Exception:
        db.rollback()
        raise
