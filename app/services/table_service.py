from __future__ import annotations

import base64
import io
import secrets
from typing import Any

import qrcode
from PIL import Image, ImageDraw, ImageFont

from ..errors import ValidationError


def parse_table_count(value: Any) -> int:
    try:
        table_count = int(str(value or '').strip())
    except (TypeError, ValueError) as exc:
        raise ValidationError('Informe uma quantidade válida de mesas.') from exc

    if table_count < 1:
        raise ValidationError('Informe pelo menos 1 mesa.')

    if table_count > 300:
        raise ValidationError('Informe no máximo 300 mesas por vez.')

    return table_count


def _ensure_table_token_table(db) -> None:
    db.execute(
        '''
        CREATE TABLE IF NOT EXISTS restaurant_table_qr_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            restaurant_id INTEGER NOT NULL,
            table_number TEXT NOT NULL,
            access_token TEXT NOT NULL UNIQUE,
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (restaurant_id, table_number),
            FOREIGN KEY (restaurant_id) REFERENCES restaurant_profiles(id) ON DELETE CASCADE
        )
        '''
    )
    db.execute(
        'CREATE INDEX IF NOT EXISTS idx_restaurant_table_qr_tokens_token ON restaurant_table_qr_tokens(access_token)'
    )
    db.execute(
        'CREATE INDEX IF NOT EXISTS idx_restaurant_table_qr_tokens_rest_table ON restaurant_table_qr_tokens(restaurant_id, table_number)'
    )


def _generate_table_access_token(db) -> str:
    _ensure_table_token_table(db)
    while True:
        token = secrets.token_urlsafe(18).replace('-', '').replace('_', '')[:24]
        row = db.execute(
            'SELECT id FROM restaurant_table_qr_tokens WHERE access_token = ? LIMIT 1',
            (token,),
        ).fetchone()
        if not row:
            return token


def ensure_table_tokens(db, restaurant_id: int | None, table_count: int, *, regenerate: bool = False) -> None:
    if not restaurant_id:
        raise ValidationError('Restaurante não identificado para gerar QR Codes.')

    _ensure_table_token_table(db)
    table_count = int(table_count or 0)

    if regenerate:
        db.execute(
            'DELETE FROM restaurant_table_qr_tokens WHERE restaurant_id = ?',
            (restaurant_id,),
        )

    for table_number in range(1, table_count + 1):
        table_label = str(table_number)
        row = db.execute(
            '''
            SELECT id
              FROM restaurant_table_qr_tokens
             WHERE restaurant_id = ?
               AND table_number = ?
             LIMIT 1
            ''',
            (restaurant_id, table_label),
        ).fetchone()

        if row:
            db.execute(
                '''
                UPDATE restaurant_table_qr_tokens
                   SET active = 1,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = ?
                ''',
                (row['id'],),
            )
            continue

        db.execute(
            '''
            INSERT INTO restaurant_table_qr_tokens (restaurant_id, table_number, access_token, active)
            VALUES (?, ?, ?, 1)
            ''',
            (restaurant_id, table_label, _generate_table_access_token(db)),
        )

    if table_count > 0:
        db.execute(
            '''
            UPDATE restaurant_table_qr_tokens
               SET active = 0,
                   updated_at = CURRENT_TIMESTAMP
             WHERE restaurant_id = ?
               AND CAST(table_number AS INTEGER) > ?
            ''',
            (restaurant_id, table_count),
        )


def save_table_count(db, admin_id: int | None, table_count: int, *, regenerate_tokens: bool = False) -> None:
    if not admin_id:
        raise ValidationError('Sessão inválida. Faça login novamente.')

    row = db.execute(
        'SELECT id FROM restaurant_profiles WHERE admin_id = ? LIMIT 1',
        (admin_id,),
    ).fetchone()

    if not row:
        raise ValidationError('Restaurante não encontrado para gerar QR Codes.')

    db.execute(
        '''
        UPDATE restaurant_profiles
           SET table_count = ?
         WHERE admin_id = ?
        ''',
        (table_count, admin_id),
    )
    ensure_table_tokens(db, int(row['id']), table_count, regenerate=regenerate_tokens)
    db.commit()


def list_table_tokens(db, restaurant_id: int | None, table_count: int) -> list[dict]:
    if not restaurant_id:
        return []

    _ensure_table_token_table(db)
    ensure_table_tokens(db, restaurant_id, table_count)
    db.commit()

    rows = db.execute(
        '''
        SELECT table_number, access_token
          FROM restaurant_table_qr_tokens
         WHERE restaurant_id = ?
           AND active = 1
         ORDER BY CAST(table_number AS INTEGER), table_number
        ''',
        (restaurant_id,),
    ).fetchall()
    return [{'table_number': row['table_number'], 'access_token': row['access_token']} for row in rows]


def get_table_by_access_token(db, access_token: str):
    _ensure_table_token_table(db)
    token = str(access_token or '').strip()
    if not token:
        return None

    return db.execute(
        '''
        SELECT t.table_number,
               t.access_token,
               p.*
          FROM restaurant_table_qr_tokens t
          JOIN restaurant_profiles p ON p.id = t.restaurant_id
         WHERE t.access_token = ?
           AND t.active = 1
         LIMIT 1
        ''',
        (token,),
    ).fetchone()


def _load_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = []

    if bold:
        candidates.extend(
            [
                'DejaVuSans-Bold.ttf',
                '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
                '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf',
                'arialbd.ttf',
            ]
        )
    else:
        candidates.extend(
            [
                'DejaVuSans.ttf',
                '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                '/usr/share/fonts/dejavu/DejaVuSans.ttf',
                'arial.ttf',
            ]
        )

    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except Exception:
            continue

    return ImageFont.load_default()


def _fit_brand_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, start_size: int) -> ImageFont.ImageFont:
    size = max(14, start_size)

    while size >= 14:
        font = _load_font(size, bold=True)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        if text_width <= max_width:
            return font
        size -= 1

    return _load_font(14, bold=True)


def build_qr_code_image(url: str, table_number: int | str, *, include_footer: bool = True) -> Image.Image:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    qr_image = qr.make_image(fill_color='black', back_color='white').convert('RGB')
    qr_width, qr_height = qr_image.size

    outer_padding = 18
    footer_height = 72 if include_footer else 0
    canvas_width = qr_width + (outer_padding * 2)
    canvas_height = qr_height + (outer_padding * 2) + footer_height

    canvas = Image.new('RGB', (canvas_width, canvas_height), 'white')
    qr_x = outer_padding
    qr_y = outer_padding
    canvas.paste(qr_image, (qr_x, qr_y))

    draw = ImageDraw.Draw(canvas)

    brand_text = 'QR Totem'
    mesa_text = f'Mesa {table_number}'

    max_brand_width = int(qr_width * 0.40)
    brand_font = _fit_brand_font(draw, brand_text, max_brand_width, max(18, qr_width // 10))
    mesa_font = _load_font(max(18, qr_width // 16), bold=True)

    brand_bbox = draw.textbbox((0, 0), brand_text, font=brand_font)
    brand_text_width = brand_bbox[2] - brand_bbox[0]
    brand_text_height = brand_bbox[3] - brand_bbox[1]

    brand_pad_x = 18
    brand_pad_y = 10
    brand_box_width = brand_text_width + (brand_pad_x * 2)
    brand_box_height = brand_text_height + (brand_pad_y * 2)

    brand_box_x1 = qr_x + (qr_width - brand_box_width) // 2
    brand_box_y1 = qr_y + (qr_height - brand_box_height) // 2
    brand_box_x2 = brand_box_x1 + brand_box_width
    brand_box_y2 = brand_box_y1 + brand_box_height

    draw.rounded_rectangle(
        (brand_box_x1, brand_box_y1, brand_box_x2, brand_box_y2),
        radius=18,
        fill='white',
        outline='black',
        width=2,
    )

    brand_text_x = brand_box_x1 + (brand_box_width - brand_text_width) // 2
    brand_text_y = brand_box_y1 + (brand_box_height - brand_text_height) // 2 - 1

    draw.text(
        (brand_text_x, brand_text_y),
        brand_text,
        fill='black',
        font=brand_font,
    )

    if include_footer:
        mesa_bbox = draw.textbbox((0, 0), mesa_text, font=mesa_font)
        mesa_text_width = mesa_bbox[2] - mesa_bbox[0]
        mesa_text_height = mesa_bbox[3] - mesa_bbox[1]

        mesa_text_x = (canvas_width - mesa_text_width) // 2
        mesa_text_y = qr_y + qr_height + ((footer_height - mesa_text_height) // 2)

        draw.text(
            (mesa_text_x, mesa_text_y),
            mesa_text,
            fill='black',
            font=mesa_font,
        )

    return canvas


def build_qr_code_data_uri(url: str, table_number: int | str) -> str:
    canvas = build_qr_code_image(url, table_number, include_footer=True)
    buffer = io.BytesIO()
    canvas.save(buffer, format='PNG')
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    return f'data:image/png;base64,{encoded}'


def build_qr_codes_pdf_bytes(table_cards: list[dict], *, title: str = 'FAÇA SEU PEDIDO AQUI') -> bytes:
    # A4 em 150 DPI, layout 3x3 como o modelo enviado pelo usuário.
    page_width, page_height = 1240, 1754
    margin_x, margin_y = 50, 48
    columns, rows = 3, 3
    cell_width = (page_width - (margin_x * 2)) // columns
    cell_height = (page_height - (margin_y * 2)) // rows

    title_font = _load_font(27, bold=True)
    mesa_font = _load_font(26, bold=True)

    pages: list[Image.Image] = []

    for offset in range(0, len(table_cards), columns * rows):
        page = Image.new('RGB', (page_width, page_height), 'white')
        draw = ImageDraw.Draw(page)

        for index, table in enumerate(table_cards[offset:offset + (columns * rows)]):
            col = index % columns
            row = index // columns
            x = margin_x + (col * cell_width)
            y = margin_y + (row * cell_height)

            heading = str(title or 'FAÇA SEU PEDIDO AQUI').upper()
            heading_bbox = draw.textbbox((0, 0), heading, font=title_font)
            heading_width = heading_bbox[2] - heading_bbox[0]
            draw.text((x + (cell_width - heading_width) // 2, y), heading, fill='black', font=title_font)

            qr_image = build_qr_code_image(table['url'], table['number'], include_footer=False)
            resampling = getattr(Image, 'Resampling', Image)
            qr_image = qr_image.resize((300, 300), resampling.LANCZOS)
            qr_x = x + (cell_width - qr_image.width) // 2
            qr_y = y + 52
            page.paste(qr_image, (qr_x, qr_y))

            mesa_text = f"Mesa {table['number']}"
            mesa_bbox = draw.textbbox((0, 0), mesa_text, font=mesa_font)
            mesa_width = mesa_bbox[2] - mesa_bbox[0]
            draw.text((x + (cell_width - mesa_width) // 2, qr_y + qr_image.height + 30), mesa_text, fill='black', font=mesa_font)

        pages.append(page)

    if not pages:
        pages.append(Image.new('RGB', (page_width, page_height), 'white'))

    buffer = io.BytesIO()
    first, rest = pages[0], pages[1:]
    first.save(buffer, format='PDF', save_all=True, append_images=rest, resolution=150.0)
    return buffer.getvalue()
