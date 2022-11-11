from .views import tillweb_view
from decimal import Decimal
from django.http import JsonResponse
from sqlalchemy.sql.expression import func, or_
from sqlalchemy.orm import contains_eager
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import undefer
from .db import td
from quicktill.models import (
    PayType,
    Session,
    SessionTotal,
    Transaction,
    Payment,
    User,
    LogEntry,
)


# Utilities to help write views for datatables
def _datatables_order(query, columns, params):
    for onum in range(1000):
        order_col = params.get(f"order[{onum}][column]")
        order_dir = params.get(f"order[{onum}][dir]")
        if not order_col or not order_dir:
            break
        expr = columns[int(order_col)]
        if order_dir == "desc":
            expr = expr.desc()
        query = query.order_by(expr)

    return query


def _datatables_paginate(query, params):
    start = int(params.get("start", "0"))
    length = int(params.get("length", "100"))
    query = query.offset(start)
    if length >= 0:
        query = query.limit(length)
    return query


def _datatables_json(request, query, filtered_query, columns, rowfunc):
    order_columns = []
    error = None
    for cnum in range(1000):
        cname = request.GET.get(f"columns[{cnum}][name]") \
            or request.GET.get(f"columns[{cnum}][data]")
        if cname:
            cexpr = columns.get(cname)
            if cexpr is not None:
                order_columns.append(cexpr)
            else:
                error = f'column {cname} not defined'
                break
        else:
            break

    q = _datatables_order(filtered_query, order_columns, request.GET)
    q = _datatables_paginate(q, request.GET)
    r = {
        'draw': int(request.GET.get("draw", "1")),
        'recordsTotal': query.count(),
        'recordsFiltered': filtered_query.count(),
        'data': [rowfunc(x) for x in q.all()],
    }
    if error:
        r['error'] = error
    return JsonResponse(r)


@tillweb_view
def sessions(request, info):
    columns = {
        'id': Session.id,
        'date': Session.date,
        'day': func.to_char(Session.date, 'Day'),
        'discount': Session.discount_total,
        'till_total': Session.total,
        'actual_total': Session.actual_total,
        'difference': Session.error,
    }
    search_value = request.GET.get("search[value]")
    q = td.s.query(Session)\
            .options(undefer('total'),
                     undefer('actual_total'),
                     undefer('discount_total'))

    # Apply filters - we filter on weekday name or session ID
    fq = q
    if search_value:
        try:
            sessionid = int(search_value)
        except ValueError:
            sessionid = None
        qs = [columns['day'].ilike(search_value + '%')]
        if sessionid:
            qs.append(columns['id'] == sessionid)
        fq = q.filter(or_(*qs))

    return _datatables_json(
        request, q, fq, columns, lambda s: {
            'id': s.id,
            'url': s.get_absolute_url(),
            'date': s.date,
            'day': s.date.weekday(),
            'discount': s.discount_total,
            'till_total': s.total,
            'actual_total': s.actual_total,
            'difference': s.error,
            'DT_RowClass': "table-warning" if s.actual_total is None else None,
        })


@tillweb_view
def payments(request, info):
    columns = {
        'id': Payment.id,
        'transid': Payment.transid,
        'time': Payment.time,
        'paytype': Payment.paytype_id,
        'text': Payment.text,
        'source': Payment.source,
        'amount': Payment.amount,
        'pending': Payment.pending,
        'user': User.fullname,
    }
    search_value = request.GET.get("search[value]")
    q = td.s.query(Payment)\
            .join(PayType)\
            .join(Payment.transaction)\
            .join(Payment.user, isouter=True)\
            .join(Session, isouter=True)\
            .options(contains_eager(Payment.paytype),
                     contains_eager(Payment.user),
                     contains_eager(Payment.transaction)
                     .contains_eager(Transaction.session))

    # Apply filters from parameters. The 'unfiltered' item count for
    # this table is after this filtering step.
    try:
        sessionid = int(request.GET.get('sessionid'))
        q = q.filter(Session.id == sessionid)
    except (ValueError, TypeError):
        pass
    paytype = request.GET.get('paytype')
    if paytype:
        q = q.filter(Payment.paytype_id == paytype)

    # Apply filters from search value. The 'filtered' item count is
    # after this filtering step.
    fq = q
    if search_value:
        try:
            intsearch = int(search_value)
        except ValueError:
            intsearch = None
        try:
            decsearch = Decimal(search_value)
        except Exception:
            decsearch = None
        qs = [
            columns['text'].ilike(f'%{search_value}%'),
            columns['source'].ilike(f'{search_value}%'),
            columns['user'].ilike(f'%{search_value}%'),
        ]
        if intsearch:
            qs.append(columns['id'] == intsearch)
            qs.append(columns['transid'] == intsearch)
        if decsearch is not None:
            qs.append(columns['amount'] == decsearch)
        fq = q.filter(or_(*qs))

    return _datatables_json(
        request, q, fq, columns, lambda p: {
            'id': p.id,
            'url': p.get_absolute_url(),
            'transid': p.transid,
            'trans_url': p.transaction.get_absolute_url(),
            'time': p.time,
            'paytype': p.paytype_id,
            'paytype_url': p.paytype.get_absolute_url(),
            'text': p.text,
            'source': p.source,
            'amount': p.amount,
            'pending': p.pending,
            'user': p.user.fullname if p.user else '',
            'user_url': p.user.get_absolute_url() if p.user else None,
            'DT_RowClass': "table-warning" if p.pending else None,
        })


@tillweb_view
def sessiontotals(request, info):
    columns = {
        'sessionid': Session.id,
        'paytype': PayType.description,
        'date': Session.date,
        'amount': SessionTotal.amount,
        'fees': SessionTotal.fees,
        'payment_amount': SessionTotal.payment_amount,
    }
    search_value = request.GET.get("search[value]")
    q = td.s.query(SessionTotal)\
            .join(Session)\
            .join(PayType)\
            .options(contains_eager(SessionTotal.session),
                     contains_eager(SessionTotal.paytype))

    # Apply filters from parameters. The 'unfiltered' item count for
    # this table is after this filtering step.
    paytype = request.GET.get('paytype')
    if paytype:
        q = q.filter(PayType.paytype == paytype)

    # Apply filters from search value. The 'filtered' item count is
    # after this filtering step.
    fq = q
    if search_value:
        try:
            intsearch = int(search_value)
        except ValueError:
            intsearch = None
        try:
            decsearch = Decimal(search_value)
        except Exception:
            decsearch = None
        qs = []
        if intsearch:
            qs.append(columns['sessionid'] == intsearch)
        if decsearch is not None:
            qs.append(columns['amount'] == decsearch)
            qs.append(columns['fees'] == decsearch)
            qs.append(columns['payment_amount'] == decsearch)
        if qs:
            fq = q.filter(or_(*qs))

    return _datatables_json(
        request, q, fq, columns, lambda t: {
            'sessionid': t.session.id,
            'session_url': t.session.get_absolute_url(),
            'paytype': t.paytype.paytype,
            'paytype_url': t.paytype.get_absolute_url(),
            'date': t.session.date,
            'amount': t.amount,
            'fees': t.fees,
            'payment_amount': t.payment_amount,
        })


@tillweb_view
def logs(request, info):
    columns = {
        'id': LogEntry.id,
        'time': LogEntry.time,
        'source': LogEntry.source,
        'user': User.fullname,
        'description': LogEntry.description,
    }
    search_value = request.GET.get("search[value]")
    q = td.s.query(LogEntry)\
            .join(User, User.id == LogEntry.user_id)\
            .options(joinedload('loguser'))

    # Apply filters - we filter on weekday name or session ID
    fq = q
    if search_value:
        try:
            logid = int(search_value)
        except ValueError:
            logid = None
        qs = [
            columns['source'].ilike(f"%{search_value}%"),
            columns['user'].ilike(f"%{search_value}%"),
            columns['description'].ilike(f"%{search_value}%"),
        ]
        if logid:
            qs.append(columns['id'] == logid)
        fq = fq.filter(or_(*qs))

    return _datatables_json(
        request, q, fq, columns, lambda l: {
            'id': l.id,
            'url': l.get_absolute_url(),
            'time': l.time.isoformat(sep=' ', timespec="seconds"),
            'source': l.source,
            'user': l.loguser.fullname,
            'userlink': l.loguser.get_absolute_url(),
            'description': l.as_text(),
        })


@tillweb_view
def users(request, info):
    columns = {
        'name': User.fullname,
        'shortname': User.shortname,
        'webuser': User.webuser,
        'enabled': User.enabled,
        'superuser': User.superuser,
    }
    q = td.s.query(User)
    fq = q

    # Apply filters from parameters - these are from a tickbox on the
    # page, they should not be applied before the item count
    include_disabled = request.GET.get("include_disabled", "no") == "yes"
    if not include_disabled:
        fq = fq.filter(User.enabled == True)

    # Apply filters from search
    search_value = request.GET.get("search[value]")
    if search_value:
        qs = [
            columns['name'].ilike(f"%{search_value}%"),
            columns['shortname'].ilike(f"%{search_value}%"),
            columns['webuser'].ilike(f"%{search_value}%"),
        ]
        fq = fq.filter(or_(*qs))

    return _datatables_json(
        request, q, fq, columns, lambda u: {
            'id': u.id,
            'url': u.get_absolute_url(),
            'name': u.fullname,
            'shortname': u.shortname,
            'webuser': u.webuser,
            'enabled': u.enabled,
            'superuser': u.superuser,
            'DT_RowClass': (
                "table-warning" if not u.enabled else
                "table-primary" if u.superuser else None),
        })
