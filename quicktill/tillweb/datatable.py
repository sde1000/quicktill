from .views import tillweb_view, colours
from decimal import Decimal
from itertools import cycle
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
    UserToken,
    LogEntry,
    Transline,
    Department,
    Delivery,
    Supplier,
    StockType,
    StockItem,
    StockAnnotation,
    AnnotationType,
    zero,
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
                error = f'column {cname} not defined, valid columns are '\
                    f'{list(columns.keys())}'
                break
        else:
            break

    if error:
        return JsonResponse({'error': error})

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
        fq = fq.filter(or_(*qs))

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
def transactions(request, info):
    columns = {
        'id': Transaction.id,
        'sessionid': Transaction.sessionid,
        'session_date': Session.date,
        'total': Transaction.total,
        'discount_total': Transaction.discount_total,
        'notes': Transaction.notes,
        'closed': Transaction.closed,
        # There is a "discount policy" column that only applies to
        # open transactions; it doesn't seem particularly useful to
        # show it at the moment.
    }

    search_value = request.GET.get("search[value]")
    q = td.s.query(Transaction)\
        .join(Transaction.session, isouter=True)\
        .options(undefer('total'),
                 undefer('discount_total'),
                 contains_eager(Transaction.session))

    # Searching by amount is slow across the entire table. Disable
    # this if we are not filtering the table first.
    enable_amount_search = False

    # Apply filters from parameters. The 'unfiltered' item count for
    # this table is after this filtering step.
    try:
        sessionid = int(request.GET.get('sessionid'))
        q = q.filter(Session.id == sessionid)
        enable_amount_search = True
    except (ValueError, TypeError):
        pass

    # Apply filters from search value and other parameters. The
    # 'filtered' item count is after this filtering step.
    fq = q
    state = request.GET.get('state', 'any')
    if state == "closed":
        fq = fq.filter(Transaction.closed == True)
    elif state == "open":
        fq = fq.filter(Transaction.closed == False)\
               .filter(Transaction.sessionid != None)
    elif state == "deferred":
        fq = fq.filter(Transaction.sessionid == None)
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
            columns['notes'].ilike(f'%{search_value}%'),
        ]
        if intsearch:
            qs.append(columns['id'] == intsearch)
            qs.append(columns['sessionid'] == intsearch)
        if enable_amount_search and decsearch is not None:
            qs.append(columns['total'] == decsearch)
            qs.append(columns['discount_total'] == decsearch)
        fq = fq.filter(or_(*qs))

    return _datatables_json(
        request, q, fq, columns, lambda t: {
            'id': t.id,
            'url': t.get_absolute_url(),
            'sessionid': t.session.id if t.session else None,
            'session_url': t.session.get_absolute_url() if t.session else None,
            'session_date': t.session.date if t.session else None,
            'total': t.total,
            'discount_total': t.discount_total,
            'notes': t.notes,
            'closed': t.closed,
            'DT_RowClass': "table-warning" if t.sessionid and not t.closed
            else None,
        })


@tillweb_view
def translines(request, info):
    columns = {
        'id': Transline.id,
        'transid': Transline.transid,
        'text': Transline.text,
        'department': Transline.dept_id,
        'code': Transline.transcode,
        'items': Transline.items,
        'time': Transline.time,
        'amount': Transline.amount,
        'discount': Transline.total_discount,
        'discount_name': Transline.discount_name,
        'total': Transline.total,
        'source': Transline.source,
        'user': User.fullname,
    }
    search_value = request.GET.get("search[value]")
    q = td.s.query(Transline)\
        .join(Transline.department)\
        .join(Transline.user, isouter=True)\
        .join(Transline.transaction)\
        .join(Session, isouter=True)\
        .options(contains_eager(Transline.department),
                 contains_eager(Transline.user),
                 contains_eager(Transline.transaction))

    # Apply filters from parameters. The 'unfiltered' item count for
    # this table is after this filtering step.
    try:
        sessionid = int(request.GET.get('sessionid'))
        q = q.filter(Session.id == sessionid)
    except (ValueError, TypeError):
        pass
    try:
        userid = int(request.GET.get('userid'))
        q = q.filter(User.id == userid)
    except (ValueError, TypeError):
        pass
    try:
        deptid = int(request.GET.get('deptid'))
        q = q.filter(Department.id == deptid)
    except (ValueError, TypeError):
        pass

    # Apply filters from search value. The 'filtered' item count is
    # after this filtering step.
    fq = q
    try:
        filter_department = int(request.GET.get('filter_department'))
        fq = fq.filter(Department.id == filter_department)
    except (ValueError, TypeError):
        pass
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
            columns['discount_name'].ilike(f'%{search_value}%'),
        ]
        if intsearch:
            qs.append(columns['id'] == intsearch)
            qs.append(columns['transid'] == intsearch)
            qs.append(columns['items'] == intsearch)
        if decsearch is not None:
            qs.append(columns['amount'] == decsearch)
            qs.append(columns['discount'] == decsearch)
        fq = fq.filter(or_(*qs))

    return _datatables_json(
        request, q, fq, columns, lambda tl: {
            'id': tl.id,
            'url': tl.get_absolute_url(),
            'transid': tl.transid,
            'trans_url': tl.transaction.get_absolute_url(),
            'time': tl.time,
            'text': tl.text,
            'department': tl.department.description,
            'department_url': tl.department.get_absolute_url(),
            'code': tl.transcode,
            'items': tl.items,
            'source': tl.source,
            'amount': tl.amount,
            'discount': tl.total_discount,
            'discount_name': tl.discount_name,
            'total': tl.total,
            'user': tl.user.fullname if tl.user else '',
            'user_url': tl.user.get_absolute_url() if tl.user else None,
            'DT_RowClass': "table-warning" if tl.transcode == 'V'
            else "table-danger" if tl.voided_by_id is not None
            else None,
        })


@tillweb_view
def payments(request, info):
    columns = {
        'id': Payment.id,
        'transid': Payment.transid,
        'paytype_description': PayType.description,
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
    try:
        userid = int(request.GET.get('userid'))
        q = q.filter(User.id == userid)
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
            columns['paytype_description'].ilike(f'%{search_value}%'),
        ]
        if intsearch:
            qs.append(columns['id'] == intsearch)
            qs.append(columns['transid'] == intsearch)
        if decsearch is not None:
            qs.append(columns['amount'] == decsearch)
        fq = fq.filter(or_(*qs))

    return _datatables_json(
        request, q, fq, columns, lambda p: {
            'id': p.id,
            'url': p.get_absolute_url(),
            'transid': p.transid,
            'trans_url': p.transaction.get_absolute_url(),
            'time': p.time,
            'paytype': p.paytype_id,
            'paytype_description': p.paytype.description,
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
            fq = fq.filter(or_(*qs))

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
def deliveries(request, info):
    columns = {
        'id': Delivery.id,
        'date': Delivery.date,
        'supplier': Supplier.name,
        'docnumber': Delivery.docnumber,
        'checked': Delivery.checked,
    }
    search_value = request.GET.get("search[value]")
    q = td.s.query(Delivery)\
            .join(Supplier)\
            .options(contains_eager(Delivery.supplier))

    # Apply filters from parameters. The 'unfiltered' item count for
    # this table is after this filtering step.
    try:
        supplierid = int(request.GET.get('supplierid'))
        q = q.filter(Supplier.id == supplierid)
    except (ValueError, TypeError):
        pass

    # Apply filters from search value. The 'filtered' item count is
    # after this filtering step.
    fq = q
    if search_value:
        try:
            intsearch = int(search_value)
        except ValueError:
            intsearch = None
        qs = [
            columns['supplier'].ilike(f'%{search_value}%'),
            columns['docnumber'].ilike(f'{search_value}%'),
        ]
        if intsearch:
            qs.append(columns['id'] == intsearch)
        fq = fq.filter(or_(*qs))

    return _datatables_json(
        request, q, fq, columns, lambda d: {
            'id': d.id,
            'url': d.get_absolute_url(),
            'date': d.date,
            'supplier': d.supplier.name,
            'supplier_url': d.supplier.get_absolute_url(),
            'docnumber': d.docnumber,
            'checked': d.checked,
            'DT_RowClass': "table-warning" if not d.checked else None,
        })


@tillweb_view
def annotations(request, info):
    columns = {
        'id': StockAnnotation.id,
        'stockid': StockAnnotation.stockid,
        'stock_description': StockType.fullname,
        'time': StockAnnotation.time,
        'type': AnnotationType.description,
        'text': StockAnnotation.text,
        'user': User.fullname,
    }
    search_value = request.GET.get("search[value]")
    q = td.s.query(StockAnnotation)\
            .join(StockAnnotation.stockitem)\
            .join(StockItem.stocktype)\
            .join(StockAnnotation.user, isouter=True)\
            .join(StockAnnotation.type)\
            .options(contains_eager(StockAnnotation.stockitem)
                     .contains_eager(StockItem.stocktype),
                     contains_eager(StockAnnotation.user),
                     contains_eager(StockAnnotation.type))

    # Apply filters from parameters. The 'unfiltered' item count for
    # this table is after this filtering step.
    try:
        userid = int(request.GET.get('userid'))
        q = q.filter(StockAnnotation.user_id == userid)
    except (ValueError, TypeError):
        pass

    # Apply filters from search value. The 'filtered' item count is
    # after this filtering step.
    fq = q
    if search_value:
        try:
            intsearch = int(search_value)
        except ValueError:
            intsearch = None
        qs = [
            columns['stock_description'].ilike(f'%{search_value}%'),
            columns['type'].ilike(f'{search_value}%'),
            columns['text'].ilike(f'%{search_value}%'),
            columns['user'].ilike(f'%{search_value}%'),
        ]
        if intsearch:
            qs.append(columns['id'] == intsearch)
            qs.append(columns['stockid'] == intsearch)
        fq = fq.filter(or_(*qs))

    return _datatables_json(
        request, q, fq, columns, lambda a: {
            'id': a.id,
            'stockid': a.stockid,
            'stock_url': a.stockitem.get_absolute_url(),
            'stock_description': a.stockitem.stocktype.format(),
            'time': a.time,
            'type': a.type.description,
            'text': a.text,
            'user': a.user.fullname if a.user else None,
            'user_url': a.user.get_absolute_url() if a.user else None,
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

    # Apply filters from parameters. The 'unfiltered' item count for
    # this table is after this filtering step.
    try:
        supplierid = int(request.GET.get('supplierid'))
        q = q.filter(LogEntry.suppliers_id == supplierid)
    except (ValueError, TypeError):
        pass
    try:
        # We search for log entries by the user, as well as log
        # entries about the user
        userid = int(request.GET.get('userid'))
        q = q.filter(or_(LogEntry.users_id == userid,
                         LogEntry.user_id == userid))
    except (ValueError, TypeError):
        pass

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


@tillweb_view
def tokens(request, info):
    columns = {
        'token': UserToken.token,
        'description': UserToken.description,
        'last_seen': UserToken.last_seen,
        'user': User.fullname,
    }
    q = td.s.query(UserToken)\
            .join(User, isouter=True)\
            .options(contains_eager(UserToken.user))

    fq = q

    search_value = request.GET.get("search[value]")
    if search_value:
        qs = [
            columns['token'].ilike(f"%{search_value}%"),
            columns['description'].ilike(f"%{search_value}%"),
            columns['user'].ilike(f"%{search_value}%"),
        ]
        fq = fq.filter(or_(*qs))

    return _datatables_json(
        request, q, fq, columns, lambda t: {
            'token': t.token,
            'description': t.description,
            'last_seen': t.last_seen,
            'user': t.user.fullname if t.user else None,
            'user_url': t.user.get_absolute_url() if t.user else None,
        })


# N.B. This is _not_ a serverSide: true datatable; we just need to
# return the requested data
@tillweb_view
def depttotals(request, info):
    sessions = [int(x) for x in request.GET.get("sessions", "").split(",")
                if x]

    tot_all = td.s.query(func.sum(Transline.items * Transline.amount))\
                  .select_from(Transline.__table__)\
                  .join(Transaction)\
                  .filter(Transaction.sessionid.in_(sessions))\
                  .filter(Transline.dept_id == Department.id)
    tot_closed = tot_all.filter(Transaction.closed == True)
    tot_open = tot_all.filter(Transaction.closed == False)
    tot_discount = td.s.query(func.sum(Transline.items * Transline.discount))\
                       .select_from(Transline.__table__)\
                       .join(Transaction)\
                       .filter(Transaction.sessionid.in_(sessions))\
                       .filter(Transline.dept_id == Department.id)

    # Ordering by Department.id ensures stable colours for each
    # department in the pie chart.
    r = td.s.query(Department,
                   tot_closed.label("paid"),
                   tot_open.label("pending"),
                   tot_discount.label("discount_total"))\
            .order_by(Department.id)\
            .group_by(Department).all()

    c = cycle(colours)

    return JsonResponse({
        "data": [
            {"id": d.id,
             "url": d.get_absolute_url(),
             "description": d.description,
             "paid": paid or zero,
             "pending": pending or zero,
             "total": (paid or zero) + (pending or zero),
             "discount": discount_total or zero,
             "colour": colour,
             } for (d, paid, pending, discount_total), colour
            in zip(r, c)
            if paid or pending or discount_total],
    })


# N.B. This is _not_ a serverSide: true datatable; we just need to
# return the requested data
@tillweb_view
def usertotals(request, info):
    sessions = [int(x) for x in request.GET.get("sessions", "").split(",")
                if x]

    # Ordering by user ID ensures stable colours per user, as long as
    # the set of users doesn't change.
    r = td.s.query(User,
                   func.sum(Transline.items),
                   func.sum(Transline.items * Transline.amount))\
            .join(Transline, Transaction)\
            .filter(Transaction.sessionid.in_(sessions))\
            .order_by(User.id)\
            .group_by(User).all()

    c = cycle(colours)

    return JsonResponse({
        "data": [
            {"user_name": u.fullname,
             "user_url": u.get_absolute_url(),
             "items": items,
             "amount": amount,
             "colour": colour,
             } for (u, items, amount), colour in zip(r, c)],
    })
