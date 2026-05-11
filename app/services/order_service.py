from app.db import get_db


def create_order(table_number, items):
    db = get_db()

    total = 0

    for item in items:
        total += item["quantity"] * item["price"]

    cursor = db.execute(
        """
        INSERT INTO orders (table_number, total, status)
        VALUES (?, ?, ?)
        """,
        (table_number, total, "pending"),
    )

    order_id = cursor.lastrowid

    for item in items:
        db.execute(
            """
            INSERT INTO order_items
            (
                order_id,
                product_id,
                product_name_snapshot,
                quantity,
                unit_price
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                order_id,
                item["id"],
                item["name"],
                item["quantity"],
                item["price"],
            ),
        )

    db.commit()

    return order_id


def get_orders():
    db = get_db()

    orders = db.execute(
        """
        SELECT *
        FROM orders
        ORDER BY created_at DESC
        """
    ).fetchall()

    decorated_orders = []

    for order in orders:
        decorated_orders.append(_decorate_order(order))

    return decorated_orders


def get_pending_orders():
    db = get_db()

    orders = db.execute(
        """
        SELECT *
        FROM orders
        WHERE status != 'done'
        ORDER BY created_at ASC
        """
    ).fetchall()

    decorated_orders = []

    for order in orders:
        decorated_orders.append(_decorate_order(order))

    return decorated_orders


def update_order_status(order_id, status):
    db = get_db()

    db.execute(
        """
        UPDATE orders
        SET status = ?
        WHERE id = ?
        """,
        (status, order_id),
    )

    db.commit()


def delete_order(order_id):
    db = get_db()

    db.execute(
        "DELETE FROM order_items WHERE order_id = ?",
        (order_id,),
    )

    db.execute(
        "DELETE FROM orders WHERE id = ?",
        (order_id,),
    )

    db.commit()


def _decorate_order(order):
    db = get_db()

    items = db.execute(
        """
        SELECT
            oi.id,
            oi.order_id,
            oi.product_id,

            COALESCE(
                NULLIF(oi.product_name_snapshot, ''),
                p.name,
                'Item'
            ) AS name,

            oi.quantity,
            oi.unit_price

        FROM order_items oi

        LEFT JOIN products p
            ON p.id = oi.product_id

        WHERE oi.order_id = ?
        """,
        (order["id"],),
    ).fetchall()

    order_dict = dict(order)
    order_dict["items"] = [dict(item) for item in items]

    return order_dict
