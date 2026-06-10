from __future__ import annotations

import re
import unicodedata
from uuid import uuid4

from ..utils import parse_positive_int

LEGACY_CART_KEY = 'cart'
CART_PREFIX = 'cart'

_ADDON_PATTERN = re.compile(
    r'Adicional(?:\s+de)?\s+([^.:]+?):\s*R\$\s*([0-9]+(?:[\.,][0-9]{1,2})?)',
    re.IGNORECASE,
)


def _cart_scope(session) -> tuple[str | None, str | None]:
    restaurant_id = session.get('client_restaurant_id') or session.get('restaurant_id')
    table_number = session.get('current_table') or '1'

    restaurant_id = str(restaurant_id).strip() if restaurant_id else None
    table_number = str(table_number).strip() if table_number else None

    return restaurant_id, table_number


def cart_key(session) -> str:
    restaurant_id, table_number = _cart_scope(session)

    if restaurant_id and table_number:
        return f'{CART_PREFIX}:{restaurant_id}:{table_number}'

    return LEGACY_CART_KEY


def _money_to_float(value: str) -> float:
    return round(float(str(value).replace('.', '').replace(',', '.')), 2)


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize('NFKD', value)
    ascii_text = normalized.encode('ascii', 'ignore').decode('ascii')
    slug = re.sub(r'[^a-z0-9]+', '-', ascii_text.lower()).strip('-')
    return slug or 'adicional'


def extract_addon_options(description: str | None) -> list[dict]:
    """Return add-on options found in product descriptions.

    Examples supported:
    - "Adicional cheddar + bacon: R$6,00."
    - "Adicional de leite: R$3,00."
    """
    if not description:
        return []

    options = []
    seen = set()

    for match in _ADDON_PATTERN.finditer(str(description)):
        raw_label = ' '.join(match.group(1).split()).strip(' .:-')
        if not raw_label:
            continue

        prefix = 'Adicional de' if raw_label.lower() == 'leite' else 'Adicional'
        label = f'{prefix} {raw_label}'
        price = _money_to_float(match.group(2))
        option_id = _slugify(label)

        if option_id in seen:
            continue

        seen.add(option_id)
        options.append(
            {
                'id': option_id,
                'label': label,
                'price': price,
            }
        )

    return options


def resolve_selected_addons(description: str | None, selected_ids) -> list[dict]:
    if selected_ids is None:
        selected_ids = []

    if isinstance(selected_ids, str):
        selected_ids = [selected_ids]

    selected_set = {str(value).strip() for value in selected_ids if str(value).strip()}
    options = extract_addon_options(description)

    return [option for option in options if option['id'] in selected_set]


def _normalize_addons(value) -> list[dict]:
    if not isinstance(value, list):
        return []

    addons = []
    seen = set()

    for addon in value:
        if not isinstance(addon, dict):
            continue

        label = str(addon.get('label') or '').strip()
        option_id = str(addon.get('id') or _slugify(label)).strip()

        try:
            price = float(addon.get('price', 0))
        except (TypeError, ValueError):
            price = 0.0

        if not label or price <= 0 or option_id in seen:
            continue

        seen.add(option_id)
        addons.append(
            {
                'id': option_id,
                'label': label,
                'price': round(price, 2),
            }
        )

    return addons


def _normalize_flavor(value) -> dict | None:
    if not isinstance(value, dict):
        return None

    label = str(value.get('label') or '').strip()
    option_id = str(value.get('id') or _slugify(label)).strip()

    if not label or not option_id:
        return None

    return {'id': option_id, 'label': label}


def line_key_for(product_id: int, addons: list[dict] | None = None) -> str:
    addon_ids = sorted(str(addon.get('id') or '').strip() for addon in (addons or []) if str(addon.get('id') or '').strip())
    suffix = '|'.join(addon_ids)
    return f'{int(product_id)}:{suffix}'


def unit_line_key_for(product_id: int) -> str:
    return f'{int(product_id)}:unit:{uuid4().hex[:12]}'


def normalize_cart_item(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None

    try:
        product_id = int(item.get('product_id', item.get('id')))
        quantity = parse_positive_int(item.get('quantity', item.get('quantidade', 0)), default=0, minimum=1, maximum=999)
        price = float(item.get('price', item.get('preco')))
        name = str(item.get('name', item.get('nome'))).strip()
    except (TypeError, ValueError):
        return None

    if not product_id or not name or price < 0:
        return None

    addons = _normalize_addons(item.get('addons', []))
    flavor = _normalize_flavor(item.get('flavor'))
    base_price = item.get('base_price')

    try:
        base_price = float(base_price) if base_price is not None else round(price - sum(float(addon['price']) for addon in addons), 2)
    except (TypeError, ValueError):
        base_price = price

    normalized = {
        'product_id': product_id,
        'name': name,
        'price': round(price, 2),
        'base_price': round(max(base_price, 0), 2),
        'quantity': quantity,
        'addons': addons,
        'flavor': flavor,
        'unit_configurable': bool(item.get('unit_configurable')),
    }
    normalized['line_key'] = str(item.get('line_key') or (unit_line_key_for(product_id) if normalized['unit_configurable'] else line_key_for(product_id, addons)))

    return normalized


def get_cart(session) -> list[dict]:
    key = cart_key(session)
    raw = session.get(key)

    if raw is None and key != LEGACY_CART_KEY and session.get(LEGACY_CART_KEY):
        raw = session.get(LEGACY_CART_KEY, [])
        session[key] = raw
        session.pop(LEGACY_CART_KEY, None)
        session.modified = True

    raw = raw or []
    cart = []
    changed = False

    for item in raw:
        normalized = normalize_cart_item(item)

        if normalized:
            cart.append(normalized)
            changed = changed or normalized != item
        else:
            changed = True

    if changed:
        session[key] = cart
        session.modified = True

    return cart


def save_cart(session, cart: list[dict]) -> None:
    session[cart_key(session)] = cart
    session.modified = True


def clear_cart(session) -> None:
    session.pop(cart_key(session), None)
    session.pop(LEGACY_CART_KEY, None)
    session.modified = True


def find_item(cart: list[dict], product_id: int | None = None, addons: list[dict] | None = None, line_key: str | None = None) -> dict | None:
    if line_key:
        return next((item for item in cart if str(item.get('line_key')) == str(line_key)), None)

    if product_id is None:
        return None

    target_key = line_key_for(product_id, addons or [])
    return next((item for item in cart if str(item.get('line_key')) == target_key), None)


def totals(cart: list[dict]) -> tuple[float, int]:
    total = 0.0
    quantity = 0

    for item in cart:
        qty = int(item['quantity'])
        total += float(item['price']) * qty
        quantity += qty

    return round(total, 2), quantity


def add_item(cart: list[dict], product: dict, quantity: int, addons: list[dict] | None = None) -> list[dict]:
    addons = _normalize_addons(addons or [])
    addon_total = sum(float(addon['price']) for addon in addons)
    base_price = float(product['price'])
    unit_price = round(base_price + addon_total, 2)
    item = find_item(cart, product['id'], addons=addons)

    if item:
        item['quantity'] = quantity
        item['price'] = unit_price
        item['base_price'] = round(base_price, 2)
        item['addons'] = addons
        item['line_key'] = line_key_for(product['id'], addons)
    else:
        cart.append(
            {
                'product_id': int(product['id']),
                'line_key': line_key_for(product['id'], addons),
                'name': product['name'],
                'price': unit_price,
                'base_price': round(base_price, 2),
                'quantity': quantity,
                'addons': addons,
            }
        )

    return cart


def make_unit_item(product: dict, addons: list[dict] | None = None, flavor: dict | None = None, line_key: str | None = None) -> dict:
    addons = _normalize_addons(addons or [])
    base_price = float(product['price'])
    addon_total = sum(float(addon['price']) for addon in addons)
    return {
        'product_id': int(product['id']),
        'line_key': line_key or unit_line_key_for(product['id']),
        'name': product['name'],
        'price': round(base_price + addon_total, 2),
        'base_price': round(base_price, 2),
        'quantity': 1,
        'addons': addons,
        'flavor': _normalize_flavor(flavor),
        'unit_configurable': True,
    }


def set_product_quantity(cart: list[dict], product: dict, quantity: int, *, unit_configurable: bool = False, default_addons: list[dict] | None = None) -> list[dict]:
    product_id = int(product['id'])
    quantity = max(0, int(quantity))

    if not unit_configurable:
        cart = remove_item(cart, product_id)
        if quantity > 0:
            add_item(cart, product, quantity, default_addons or [])
        return cart

    existing_units = [item for item in cart if int(item['product_id']) == product_id]
    other_items = [item for item in cart if int(item['product_id']) != product_id]
    new_units = []

    for index in range(quantity):
        if index < len(existing_units):
            current = existing_units[index]
            current['quantity'] = 1
            current['unit_configurable'] = True
            current['line_key'] = current.get('line_key') or unit_line_key_for(product_id)
            new_units.append(current)
        else:
            new_units.append(make_unit_item(product, default_addons or []))

    return other_items + new_units


def update_item_options(cart: list[dict], line_key: str, addons: list[dict] | None = None, flavor: dict | None = None) -> tuple[list[dict], bool]:
    item = find_item(cart, line_key=line_key)

    if not item:
        return cart, False

    addons = _normalize_addons(addons or [])
    item['addons'] = addons
    item['flavor'] = _normalize_flavor(flavor)
    base_price = float(item.get('base_price') or item.get('price') or 0)
    item['price'] = round(base_price + sum(float(addon['price']) for addon in addons), 2)
    item['unit_configurable'] = True
    item['quantity'] = 1
    return cart, True


def update_item(cart: list[dict], product_id: int | None, quantity: int, line_key: str | None = None) -> tuple[list[dict], bool]:
    item = find_item(cart, product_id, line_key=line_key)

    if not item:
        return cart, False

    if quantity <= 0:
        return [row for row in cart if row is not item], True

    item['quantity'] = quantity
    return cart, False


def remove_item(cart: list[dict], product_id: int | None = None, line_key: str | None = None) -> list[dict]:
    if line_key:
        return [row for row in cart if str(row.get('line_key')) != str(line_key)]

    return [row for row in cart if int(row['product_id']) != int(product_id)]
