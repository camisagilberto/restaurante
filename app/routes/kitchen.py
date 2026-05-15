from __future__ import annotations

import json
import time
from functools import wraps

from flask import (
    Blueprint,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    stream_with_context,
    url_for,
)

from ..db import get_db
from ..errors import ValidationError
from ..security import csrf_token
from ..services.auth_service import verify_manager_password
from ..services.order_service import (
    ORDER_STATUS_LABELS,
    delete_all_orders,
    get_kitchen_orders_signature,
    list_orders_for_kitchen,
    update_order_status,
)

kitchen_bp = Blueprint('kitchen', __name__, url_prefix='/cozinha')


def kitchen_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('kitchen_authorized'):
            return redirect(url_for('client.home'))
        return view(*args, **kwargs)

    return wrapped


@kitchen_bp.route('/validar', methods=['POST'])
def validar_acesso():
    data = request.get_json(silent=True) or {}
    password = str(data.get('password') or '').strip()

    if not password:
        return jsonify(success=False, message='Informe a senha.'), 400

    db = get_db()

    if not verify_manager_password(db, password):
        return jsonify(success=False, message='Senha inválida.'), 401

    session['kitchen_authorized'] = True

    return jsonify(success=True, redirect_url=url_for('kitchen.orders'))


@kitchen_bp.route('/')
@kitchen_required
def orders():
    db = get_db()
    detailed_orders = list_orders_for_kitchen(db)

    return render_template(
        'kitchen/orders.html',
        orders=detailed_orders,
        status_labels=ORDER_STATUS_LABELS,
        csrf=csrf_token(),
    )


@kitchen_bp.route('/pedidos')
@kitchen_required
def orders_partial():
    db = get_db()
    detailed_orders = list_orders_for_kitchen(db)

    return render_template(
        'kitchen/_orders_grid.html',
        orders=detailed_orders,
        status_labels=ORDER_STATUS_LABELS,
        csrf=csrf_token(),
    )


@kitchen_bp.route('/eventos')
@kitchen_required
def kitchen_events():
    def event_stream():
        db = get_db()
        last_signature = get_kitchen_orders_signature(db)

        yield 'event: connected\n'
        yield f'data: {json.dumps({"signature": last_signature})}\n\n'

        while True:
            time.sleep(1)

            current_signature = get_kitchen_orders_signature(db)

            if current_signature != last_signature:
                last_signature = current_signature

                payload = {
                    'signature': current_signature,
                    'updated': True,
                }

                yield 'event: orders-updated\n'
                yield f'data: {json.dumps(payload)}\n\n'
            else:
                yield 'event: ping\n'
                yield f'data: {json.dumps({"signature": current_signature})}\n\n'

    response = Response(
        stream_with_context(event_stream()),
        mimetype='text/event-stream',
    )

    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'

    return response


@kitchen_bp.route('/<int:order_id>/status', methods=['POST'])
@kitchen_required
def update_status(order_id):
    status = request.form.get('status', 'novo')
    db = get_db()

    try:
        update_order_status(db, order_id, status)
        message = 'Status atualizado.'
    except (ValidationError, ValueError) as exc:
        message = str(exc)

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message=message), 400

        flash(message, 'error')
        return redirect(url_for('kitchen.orders'))

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(success=True, message=message)

    flash(message, 'success')
    return redirect(url_for('kitchen.orders'))


@kitchen_bp.route('/apagar-pedidos', methods=['POST'])
@kitchen_required
def delete_orders_history():
    data = request.get_json(silent=True) or {}
    password = str(data.get('password') or '').strip()

    if not password:
        return jsonify(success=False, message='Informe a senha do admin.'), 400

    db = get_db()

    if not verify_manager_password(db, password):
        return jsonify(success=False, message='Senha inválida.'), 401

    delete_all_orders(db)

    return jsonify(
        success=True,
        message='Histórico de pedidos apagado com sucesso.',
        redirect_url=url_for('kitchen.orders'),
    )
