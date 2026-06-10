from __future__ import annotations

import re
from ..errors import ValidationError
from ..utils import normalize_text, parse_price


def ensure_product_addons_table(db) -> None:
    """Garante a tabela de adicionais em bancos SQLite já existentes.

    Isso evita erro em ambientes com volume persistente onde o banco foi criado
    antes da implantação da funcionalidade de adicionais.
    """
    db.execute("""
        CREATE TABLE IF NOT EXISTS product_addons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            price REAL NOT NULL DEFAULT 0 CHECK (price >= 0),
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        )
    """)
    db.execute(
        'CREATE INDEX IF NOT EXISTS idx_product_addons_product_active_sort '
        'ON product_addons(product_id, active, sort_order)'
    )


def ensure_product_flavors_table(db) -> None:
    """Garante a tabela de sabores em bancos SQLite já existentes."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS product_flavors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        )
    """)
    db.execute(
        'CREATE INDEX IF NOT EXISTS idx_product_flavors_product_active_sort '
        'ON product_flavors(product_id, active, sort_order)'
    )


def _require_restaurant_id(restaurant_id: int | None) -> int:
    if not restaurant_id:
        raise ValidationError('Restaurante não identificado.')

    return int(restaurant_id)


def _normalize_kind(kind: str | None = 'menu') -> str:
    value = str(kind or 'menu').strip().lower()
    return value if value in {'menu', 'coupon'} else 'menu'


def _normalize_addon_label(value: object) -> str:
    return normalize_text(value)


def _addon_field_count(payload: dict) -> int:
    try:
        count = int(payload.get('addon_count') or 0)
    except (TypeError, ValueError):
        count = 0

    indexes = set()
    for key in payload.keys():
        match = re.match(r'addon_label_(\d+)$', str(key))
        if match:
            indexes.add(int(match.group(1)))

    return max([count, *indexes], default=0)


def parse_addon_payload(payload: dict) -> list[dict]:
    addons: list[dict] = []
    seen = set()

    for index in range(1, _addon_field_count(payload) + 1):
        label = _normalize_addon_label(payload.get(f'addon_label_{index}'))
        price_raw = payload.get(f'addon_price_{index}')

        if not label and (price_raw is None or str(price_raw).strip() == ''):
            continue

        if not label:
            raise ValidationError(f'Informe o nome do adicional {index}.')

        price = parse_price(price_raw)
        if price <= 0:
            raise ValidationError(f'Informe um valor maior que zero para o adicional {index}.')

        key = label.casefold()
        if key in seen:
            raise ValidationError(f'O adicional "{label}" foi informado mais de uma vez.')

        seen.add(key)
        addons.append({
            'label': label,
            'price': price,
            'sort_order': len(addons) + 1,
            'active': 1,
        })

    return addons


def _flavor_field_count(payload: dict) -> int:
    try:
        count = int(payload.get('flavor_count') or 0)
    except (TypeError, ValueError):
        count = 0

    indexes = set()
    for key in payload.keys():
        match = re.match(r'flavor_label_(\d+)$', str(key))
        if match:
            indexes.add(int(match.group(1)))

    return max([count, *indexes], default=0)


def parse_flavor_payload(payload: dict) -> list[dict]:
    flavors: list[dict] = []
    seen = set()

    for index in range(1, _flavor_field_count(payload) + 1):
        label = normalize_text(payload.get(f'flavor_label_{index}'))

        if not label:
            continue

        key = label.casefold()
        if key in seen:
            raise ValidationError(f'O sabor "{label}" foi informado mais de uma vez.')

        seen.add(key)
        flavors.append({
            'label': label,
            'sort_order': len(flavors) + 1,
            'active': 1,
        })

    return flavors


def list_product_addons(db, product_id: int, restaurant_id: int | None = None, *, active_only: bool = True) -> list[dict]:
    ensure_product_addons_table(db)
    sql = """
        SELECT pa.*
          FROM product_addons pa
          JOIN products p ON p.id = pa.product_id
         WHERE pa.product_id = ?
    """
    params: list[object] = [int(product_id)]

    if restaurant_id is not None:
        sql += ' AND p.restaurant_id = ?'
        params.append(int(restaurant_id))

    if active_only:
        sql += ' AND pa.active = 1'

    sql += ' ORDER BY pa.sort_order ASC, pa.id ASC'
    return [dict(row) for row in db.execute(sql, params).fetchall()]


def addons_by_product(db, product_ids: list[int], *, active_only: bool = True) -> dict[int, list[dict]]:
    ensure_product_addons_table(db)
    ids = [int(product_id) for product_id in product_ids if product_id]
    if not ids:
        return {}

    placeholders = ','.join('?' for _ in ids)
    sql = f"""
        SELECT *
          FROM product_addons
         WHERE product_id IN ({placeholders})
    """
    params: list[object] = ids

    if active_only:
        sql += ' AND active = 1'

    sql += ' ORDER BY product_id ASC, sort_order ASC, id ASC'
    result: dict[int, list[dict]] = {product_id: [] for product_id in ids}

    for row in db.execute(sql, params).fetchall():
        result.setdefault(int(row['product_id']), []).append(dict(row))

    return result


def list_product_flavors(db, product_id: int, restaurant_id: int | None = None, *, active_only: bool = True) -> list[dict]:
    ensure_product_flavors_table(db)
    sql = """
        SELECT pf.*
          FROM product_flavors pf
          JOIN products p ON p.id = pf.product_id
         WHERE pf.product_id = ?
    """
    params: list[object] = [int(product_id)]

    if restaurant_id is not None:
        sql += ' AND p.restaurant_id = ?'
        params.append(int(restaurant_id))

    if active_only:
        sql += ' AND pf.active = 1'

    sql += ' ORDER BY pf.sort_order ASC, pf.id ASC'
    return [dict(row) for row in db.execute(sql, params).fetchall()]


def flavors_by_product(db, product_ids: list[int], *, active_only: bool = True) -> dict[int, list[dict]]:
    ensure_product_flavors_table(db)
    ids = [int(product_id) for product_id in product_ids if product_id]
    if not ids:
        return {}

    placeholders = ','.join('?' for _ in ids)
    sql = f"""
        SELECT *
          FROM product_flavors
         WHERE product_id IN ({placeholders})
    """
    params: list[object] = ids

    if active_only:
        sql += ' AND active = 1'

    sql += ' ORDER BY product_id ASC, sort_order ASC, id ASC'
    result: dict[int, list[dict]] = {product_id: [] for product_id in ids}

    for row in db.execute(sql, params).fetchall():
        result.setdefault(int(row['product_id']), []).append(dict(row))

    return result


def replace_product_flavors(db, product_id: int, restaurant_id: int, flavors: list[dict]) -> None:
    ensure_product_flavors_table(db)
    product = get_product(db, product_id, restaurant_id, kind='menu')
    if not product:
        raise ValidationError('Produto não encontrado.')

    db.execute('DELETE FROM product_flavors WHERE product_id = ?', (int(product_id),))

    for flavor in flavors:
        db.execute(
            """
            INSERT INTO product_flavors (
                product_id,
                label,
                active,
                sort_order
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                int(product_id),
                flavor['label'],
                int(flavor.get('active', 1)),
                int(flavor.get('sort_order', 0)),
            ),
        )


def replace_product_addons(db, product_id: int, restaurant_id: int, addons: list[dict]) -> None:
    ensure_product_addons_table(db)
    product = get_product(db, product_id, restaurant_id, kind='menu')
    if not product:
        raise ValidationError('Produto não encontrado.')

    db.execute('DELETE FROM product_addons WHERE product_id = ?', (int(product_id),))

    for addon in addons:
        db.execute(
            """
            INSERT INTO product_addons (
                product_id,
                label,
                price,
                active,
                sort_order
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(product_id),
                addon['label'],
                float(addon['price']),
                int(addon.get('active', 1)),
                int(addon.get('sort_order', 0)),
            ),
        )


def list_products(db, restaurant_id: int, *, active_only: bool = False, query: str | None = None, kind: str | None = 'menu'):
    restaurant_id = _require_restaurant_id(restaurant_id)
    kind = _normalize_kind(kind)

    sql = 'SELECT * FROM products WHERE restaurant_id = ? AND kind = ?'
    params: list[object] = [restaurant_id, kind]

    if active_only:
        sql += ' AND active = 1'

    if query:
        sql += ' AND (name LIKE ? OR category LIKE ? OR COALESCE(description, "") LIKE ?)'
        like = f'%{query.strip()}%'
        params.extend([like, like, like])

    sql += ' ORDER BY active DESC, category ASC, sort_order ASC, name ASC'
    return db.execute(sql, params).fetchall()


def get_product(db, product_id: int, restaurant_id: int, *, kind: str | None = None):
    restaurant_id = _require_restaurant_id(restaurant_id)

    sql = 'SELECT * FROM products WHERE id = ? AND restaurant_id = ?'
    params: list[object] = [product_id, restaurant_id]

    if kind is not None:
        sql += ' AND kind = ?'
        params.append(_normalize_kind(kind))

    return db.execute(sql, params).fetchone()


def _requested_sort_order(payload: dict) -> int | None:
    raw_value = payload.get('sort_order')

    if raw_value is None or str(raw_value).strip() == '':
        return None

    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None

    return value if value > 0 else None


def _last_sort_order(db, restaurant_id: int, category: str, *, kind: str = 'menu', exclude_product_id: int | None = None) -> int:
    params: list[object] = [restaurant_id, category, _normalize_kind(kind)]

    sql = '''
        SELECT COALESCE(MAX(sort_order), 0)
          FROM products
         WHERE restaurant_id = ?
           AND category = ?
           AND kind = ?
    '''

    if exclude_product_id is not None:
        sql += ' AND id <> ?'
        params.append(exclude_product_id)

    return int(db.execute(sql, params).fetchone()[0] or 0)


def _shift_category_from(db, restaurant_id: int, category: str, target_order: int, *, kind: str = 'menu', exclude_product_id: int | None = None) -> None:
    params: list[object] = [restaurant_id, category, _normalize_kind(kind), target_order]

    sql = '''
        UPDATE products
           SET sort_order = sort_order + 1,
               updated_at = CURRENT_TIMESTAMP
         WHERE restaurant_id = ?
           AND category = ?
           AND kind = ?
           AND sort_order >= ?
    '''

    if exclude_product_id is not None:
        sql += ' AND id <> ?'
        params.append(exclude_product_id)

    db.execute(sql, params)


def _reindex_category(db, restaurant_id: int, category: str, *, kind: str = 'menu') -> None:
    rows = db.execute(
        '''
        SELECT id
          FROM products
         WHERE restaurant_id = ?
           AND category = ?
           AND kind = ?
         ORDER BY sort_order ASC, name ASC, id ASC
        ''',
        (restaurant_id, category, _normalize_kind(kind)),
    ).fetchall()

    for index, row in enumerate(rows, start=1):
        db.execute(
            '''
            UPDATE products
               SET sort_order = ?,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
               AND restaurant_id = ?
            ''',
            (index, row['id'], restaurant_id),
        )


def validate_product_payload(payload: dict) -> dict:
    name = normalize_text(payload.get('name'))
    category = normalize_text(payload.get('category'))
    description = normalize_text(payload.get('description'))

    if not name:
        raise ValidationError('Informe o nome do produto.')
    if not category:
        raise ValidationError('Informe a categoria.')
    if len(name) < 2 or len(name) > 80:
        raise ValidationError('O nome deve ter entre 2 e 80 caracteres.')
    if len(category) < 2 or len(category) > 50:
        raise ValidationError('A categoria deve ter entre 2 e 50 caracteres.')

    price = parse_price(payload.get('price'))

    if price <= 0:
        raise ValidationError('O preço deve ser maior que zero.')

    return {
        'name': name,
        'description': description or None,
        'price': price,
        'category': category,
        'active': 1 if str(payload.get('active', '1')).lower() in {'1', 'true', 'on', 'yes'} else 0,
        'sort_order': _requested_sort_order(payload),
    }


def create_product(db, payload: dict, restaurant_id: int, *, kind: str = 'menu') -> int:
    restaurant_id = _require_restaurant_id(restaurant_id)
    data = validate_product_payload(payload)
    kind = _normalize_kind(kind)

    target_order = data['sort_order'] or (_last_sort_order(db, restaurant_id, data['category'], kind=kind) + 1)
    target_order = max(1, int(target_order))

    _shift_category_from(db, restaurant_id, data['category'], target_order, kind=kind)

    cursor = db.execute(
        '''
        INSERT INTO products (
            restaurant_id,
            name,
            description,
            price,
            category,
            active,
            sort_order,
            kind
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            restaurant_id,
            data['name'],
            data['description'],
            data['price'],
            data['category'],
            data['active'],
            target_order,
            kind,
        ),
    )

    _reindex_category(db, restaurant_id, data['category'], kind=kind)
    db.commit()
    return cursor.lastrowid


def update_product(db, product_id: int, payload: dict, restaurant_id: int, *, kind: str = 'menu') -> None:
    restaurant_id = _require_restaurant_id(restaurant_id)
    data = validate_product_payload(payload)
    kind = _normalize_kind(kind)
    current_product = get_product(db, product_id, restaurant_id, kind=kind)

    if not current_product:
        raise ValidationError('Produto não encontrado.')

    old_category = current_product['category']
    target_order = data['sort_order'] or (_last_sort_order(db, restaurant_id, data['category'], kind=kind, exclude_product_id=product_id) + 1)
    target_order = max(1, int(target_order))

    _shift_category_from(db, restaurant_id, data['category'], target_order, kind=kind, exclude_product_id=product_id)

    db.execute(
        '''
        UPDATE products
           SET name = ?,
               description = ?,
               price = ?,
               category = ?,
               active = ?,
               sort_order = ?,
               updated_at = CURRENT_TIMESTAMP
         WHERE id = ?
           AND restaurant_id = ?
        ''',
        (
            data['name'],
            data['description'],
            data['price'],
            data['category'],
            data['active'],
            target_order,
            product_id,
            restaurant_id,
        ),
    )

    _reindex_category(db, restaurant_id, data['category'], kind=kind)

    if old_category != data['category']:
        _reindex_category(db, restaurant_id, old_category, kind=kind)

    db.commit()


def toggle_product(db, product_id: int, restaurant_id: int, *, kind: str = 'menu') -> None:
    restaurant_id = _require_restaurant_id(restaurant_id)

    db.execute(
        '''
        UPDATE products
           SET active = CASE WHEN active = 1 THEN 0 ELSE 1 END,
               updated_at = CURRENT_TIMESTAMP
         WHERE id = ?
           AND restaurant_id = ?
           AND kind = ?
        ''',
        (product_id, restaurant_id, _normalize_kind(kind)),
    )
    db.commit()


def delete_product(db, product_id: int, restaurant_id: int, *, kind: str = 'menu') -> tuple[bool, str]:
    restaurant_id = _require_restaurant_id(restaurant_id)
    kind = _normalize_kind(kind)
    product = get_product(db, product_id, restaurant_id, kind=kind)

    if not product:
        return False, 'Produto não encontrado.'

    used = db.execute(
        '''
        SELECT COUNT(*)
          FROM order_items oi
          JOIN orders o ON o.id = oi.order_id
         WHERE oi.product_id = ?
           AND o.restaurant_id = ?
        ''',
        (product_id, restaurant_id),
    ).fetchone()[0]

    if used:
        db.execute(
            '''
            UPDATE products
               SET active = 0,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
               AND restaurant_id = ?
               AND kind = ?
            ''',
            (product_id, restaurant_id, kind),
        )
        db.commit()
        return False, 'Produto já aparece em pedidos históricos; ele foi desativado em vez de excluído.'

    db.execute(
        'DELETE FROM products WHERE id = ? AND restaurant_id = ? AND kind = ?',
        (product_id, restaurant_id, kind),
    )

    _reindex_category(db, restaurant_id, product['category'], kind=kind)
    db.commit()
    return True, 'Produto removido com sucesso.'


def delete_products_by_category(db, restaurant_id: int, category: str, *, kind: str = 'menu') -> tuple[int, int, str]:
    restaurant_id = _require_restaurant_id(restaurant_id)
    kind = _normalize_kind(kind)
    category = str(category or '').strip()

    if not category:
        raise ValidationError('Categoria inválida.')

    products = db.execute(
        '''
        SELECT id
          FROM products
         WHERE restaurant_id = ?
           AND category = ?
           AND kind = ?
        ''',
        (restaurant_id, category, kind),
    ).fetchall()

    if not products:
        return 0, 0, 'Nenhum produto encontrado nesta categoria.'

    product_ids = [int(row['id']) for row in products]
    deleted_count = 0
    deactivated_count = 0

    for product_id in product_ids:
        used = db.execute(
            '''
            SELECT COUNT(*)
              FROM order_items oi
              JOIN orders o ON o.id = oi.order_id
             WHERE oi.product_id = ?
               AND o.restaurant_id = ?
            ''',
            (product_id, restaurant_id),
        ).fetchone()[0]

        if used:
            db.execute(
                '''
                UPDATE products
                   SET active = 0,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = ?
                   AND restaurant_id = ?
                   AND kind = ?
                ''',
                (product_id, restaurant_id, kind),
            )
            deactivated_count += 1
        else:
            db.execute(
                'DELETE FROM products WHERE id = ? AND restaurant_id = ? AND kind = ?',
                (product_id, restaurant_id, kind),
            )
            deleted_count += 1

    _reindex_category(db, restaurant_id, category, kind=kind)
    db.commit()

    if deactivated_count:
        return deleted_count, deactivated_count, f'{deleted_count} produto(s) excluído(s) e {deactivated_count} produto(s) desativado(s), pois já aparecem em pedidos históricos.'

    return deleted_count, deactivated_count, f'{deleted_count} produto(s) excluído(s) da categoria {category}.'
