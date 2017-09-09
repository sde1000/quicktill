from django.http import HttpResponse, Http404, HttpResponseRedirect
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.template import RequestContext, Context
from django.template.loader import get_template
from django.conf import settings
from django import forms
from .models import *
import sqlalchemy
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import subqueryload, subqueryload_all
from sqlalchemy.orm import joinedload, joinedload_all
from sqlalchemy.orm import lazyload
from sqlalchemy.orm import defaultload
from sqlalchemy.orm import undefer, defer, undefer_group
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql import desc
from sqlalchemy.sql.expression import tuple_, func, null
from sqlalchemy import distinct
from quicktill.models import *
from quicktill.version import version
from . import spreadsheets
import io

# We use this date format in templates - defined here so we don't have
# to keep repeating it.  It's available in templates as 'dtf'
dtf = "Y-m-d H:i"

# This view is only used when the tillweb is integrated into another
# django-based website.
@login_required
def publist(request):
    access = Access.objects.filter(user=request.user)
    return render(request, 'tillweb/publist.html',
                  {'access': access})

# The remainder of the view functions in this file follow a similar
# pattern.  They are kept separate rather than implemented as a
# generic view so that page-specific optimisations (the ".options()"
# clauses in the queries) can be added.  The common operations have
# been moved into the @tillweb_view decorator.

# This app can be deployed in one of two ways:

# 1. Integrated into a complete django-based website, with its own
# users and access controls.  In this case, information about which
# database to connect to and what users are permitted to do is fetched
# from the Till and Access models.  This case is used when the
# TILLWEB_SINGLE_SITE setting is absent or False.

# 2. As a standalone website, possibly with no concept of users and
# access controls.  In this case, the database, pubname and default
# access permission are read from the rest of the TILLWEB_ settings.

# Views are passed the following parameters:
# request - the Django http request object
# base - the base URL for the till's website
# user - the quicktill.models.User object if available, or 'R','M','F'
# session - sqlalchemy database session

def tillweb_view(view):
    single_site = getattr(settings, 'TILLWEB_SINGLE_SITE', False)
    tillweb_login_required = getattr(settings, 'TILLWEB_LOGIN_REQUIRED', True)
    def new_view(request, pubname="", *args, **kwargs):
        if single_site:
            till = None
            tillname = settings.TILLWEB_PUBNAME
            access = settings.TILLWEB_DEFAULT_ACCESS
            session = settings.TILLWEB_DATABASE()
            base = "/{}/".format(pubname) if pubname else "/"
        else:
            try:
                till = Till.objects.get(slug=pubname)
            except Till.DoesNotExist:
                raise Http404
            try:
                access = Access.objects.get(user=request.user, till=till)
            except Access.DoesNotExist:
                # Pretend it doesn't exist!
                raise Http404
            try:
                session = settings.SQLALCHEMY_SESSIONS[till.database]()
            except ValueError:
                # The database doesn't exist
                raise Http404
            base = till.get_absolute_url()
            tillname = till.name
            access = access.permission
        try:
            info = {
                'base': base,
                'access': access,
                'tillname': tillname,
            }
            result = view(request, info, session, *args, **kwargs)
            if isinstance(result, HttpResponse):
                return result
            t, d = result
            # object is the Till object, possibly used for a nav menu
            # (it's None if we are set up for a single site)
            # till is the name of the till
            # access is 'R','M','F'
            # u is the base URL for the till website including trailing /
            defaults = {'object': till,
                        'till': tillname, 'access': access, 'u': base,
                        'dtf': dtf, 'pubname': pubname,
                        'version': version}
            if t.endswith(".ajax"):
                # AJAX content typically is not a fully-formed HTML document.
                # If requested in a non-AJAX context, add a HTML container.
                if not request.is_ajax():
                    defaults['ajax_content'] = 'tillweb/' + t
                    t = 'non-ajax-container.html'
            defaults.update(d)
            return render(request, 'tillweb/' + t, defaults)
        except OperationalError as oe:
            t = get_template('tillweb/operationalerror.html')
            return HttpResponse(
                t.render(RequestContext(
                        request, {'object':till, 'access':access, 'error':oe})),
                status=503)
        finally:
            session.close()
    if tillweb_login_required or not single_site:
        new_view = login_required(new_view)
    return new_view

# undefer_group on a related entity is broken until sqlalchemy 1.1.14
def undefer_qtys(entity):
    """Return options to undefer the qtys group on a related entity"""
    if sqlalchemy.__version__ < "1.1.14":
        return defaultload(entity)\
            .undefer("used")\
            .undefer("sold")\
            .undefer("remaining")
    return defaultload(entity).undefer_group("qtys")

def business_totals(session, firstday, lastday):
    # This query is wrong in that it ignores the 'business' field in
    # VatRate objects.  Fixes that don't involve a database round-trip
    # per session are welcome!
    return session.query(
        Business,
        func.sum(Transline.items * Transline.amount))\
                  .join(VatBand)\
                  .join(Department)\
                  .join(Transline)\
                  .join(Transaction)\
                  .join(Session)\
                  .filter(Session.date <= lastday)\
                  .filter(Session.date >= firstday)\
                  .order_by(Business.id)\
                  .group_by(Business)\
                  .all()

@tillweb_view
def pubroot(request, info, session):
    date = datetime.date.today()
    # If it's the early hours of the morning, it's more useful for us
    # to consider it still to be yesterday.
    if datetime.datetime.now().hour < 4:
        date = date - datetime.timedelta(1)
    thisweek_start = date - datetime.timedelta(date.weekday())
    thisweek_end = thisweek_start + datetime.timedelta(6)
    lastweek_start = thisweek_start - datetime.timedelta(7)
    lastweek_end = thisweek_end - datetime.timedelta(7)
    weekbefore_start = lastweek_start - datetime.timedelta(7)
    weekbefore_end = lastweek_end - datetime.timedelta(7)

    weeks = [("Current week", thisweek_start, thisweek_end,
              business_totals(session, thisweek_start, thisweek_end)),
             ("Last week", lastweek_start, lastweek_end,
              business_totals(session, lastweek_start, lastweek_end)),
             ("The week before last", weekbefore_start, weekbefore_end,
              business_totals(session, weekbefore_start, weekbefore_end))]

    #currentsession = Session.current(session)
    currentsession = session\
                     .query(Session)\
                     .filter_by(endtime=None)\
                     .options(undefer('total'),
                              undefer('closed_total'))\
                     .first()

    barsummary = session\
                 .query(StockLine)\
                 .filter(StockLine.location == "Bar")\
                 .order_by(StockLine.dept_id,StockLine.name)\
                 .options(joinedload_all('stockonsale.stocktype.unit'))\
                 .options(undefer_qtys("stockonsale"))\
                 .all()

    stillage = session\
               .query(StockAnnotation)\
               .join(StockItem)\
               .outerjoin(StockLine)\
               .filter(tuple_(StockAnnotation.text, StockAnnotation.time).in_(
                   select([StockAnnotation.text,
                           func.max(StockAnnotation.time)],
                          StockAnnotation.atype == 'location')\
                   .group_by(StockAnnotation.text)))\
               .filter(StockItem.finished == None)\
               .order_by(StockLine.name != null(), StockAnnotation.time)\
               .options(joinedload_all('stockitem.stocktype.unit'),
                        joinedload_all('stockitem.stockline'),
                        undefer_qtys('stockitem'))\
               .all()

    deferred = session\
               .query(func.sum(Transline.items * Transline.amount))\
               .select_from(Transaction)\
               .join(Transline)\
               .filter(Transaction.sessionid == None)\
               .scalar()

    return ('index.html',
            {'currentsession': currentsession,
             'barsummary': barsummary,
             'stillage': stillage,
             'weeks': weeks,
             'deferred': deferred,
            })

@tillweb_view
def locationlist(request, info, session):
    locations = [x[0] for x in session.query(distinct(StockLine.location))\
                 .order_by(StockLine.location).all()]
    return ('locations.html', {'locations': locations})

@tillweb_view
def location(request, info, session, location):
    lines = session\
            .query(StockLine)\
            .filter(StockLine.location == location)\
            .order_by(StockLine.dept_id, StockLine.name)\
            .options(joinedload('stockonsale'),
                     joinedload('stockonsale.stocktype'),
                     undefer_qtys('stockonsale'))\
            .all()
    return ('location.html', {'location': location, 'lines': lines})

class SessionFinderForm(forms.Form):
    session = forms.IntegerField(label="Session ID")

class SessionRangeForm(forms.Form):
    startdate = forms.DateField(label="Start date", required=False)
    enddate = forms.DateField(label="End date", required=False)

@tillweb_view
def sessionfinder(request, info, session):
    if request.method == 'POST' and "submit_find" in request.POST:
        form = SessionFinderForm(request.POST)
        if form.is_valid():
            s = session.query(Session).get(form.cleaned_data['session'])
            if s:
                return HttpResponseRedirect(info['base'] + s.tillweb_url)
            form.add_error(None, "This session does not exist.")
    else:
        form = SessionFinderForm()

    if request.method == 'POST' and "submit_sheet" in request.POST:
        rangeform = SessionRangeForm(request.POST)
        if rangeform.is_valid():
            cd = rangeform.cleaned_data
            return spreadsheets.sessionrange(
                session,
                start=cd['startdate'],
                end=cd['enddate'],
                tillname=info['tillname'])
    else:
        rangeform = SessionRangeForm()

    recent = session\
             .query(Session)\
             .options(undefer('total'),
                      undefer('actual_total'))\
             .order_by(desc(Session.id))[:30]
    return ('sessions.html',
            {'recent': recent, 'form': form, 'rangeform': rangeform})

@tillweb_view
def session(request, info, session, sessionid):
    s = session\
        .query(Session)\
        .options(undefer('total'),
                 undefer('closed_total'),
                 undefer('actual_total'))\
        .get(int(sessionid))
    if not s:
        raise Http404

    nextlink = info['base'] + s.next.tillweb_url if s.next else None
    prevlink = info['base'] + s.previous.tillweb_url if s.previous else None

    return ('session.html',
            {'session': s, 'nextlink': nextlink, 'prevlink': prevlink})

@tillweb_view
def session_spreadsheet(request, info, session, sessionid):
    s = session\
        .query(Session)\
        .options(undefer('transactions.total'),
                 joinedload('transactions.payments'))\
        .get(int(sessionid))
    if not s:
        raise Http404
    return spreadsheets.session(session, s, info['tillname'])

@tillweb_view
def session_takings_by_dept(request, info, session, sessionid):
    s = session\
        .query(Session)\
        .get(int(sessionid))
    if not s:
        raise Http404

    return ('session-takings-by-dept.ajax', {'session': s})

@tillweb_view
def session_takings_by_user(request, info, session, sessionid):
    s = session\
        .query(Session)\
        .get(int(sessionid))
    if not s:
        raise Http404

    return ('session-takings-by-user.ajax', {'session': s})

@tillweb_view
def session_stock_sold(request,info,session,sessionid):
    s = session\
        .query(Session)\
        .get(int(sessionid))
    if not s:
        raise Http404

    return ('session-stock-sold.ajax', {'session': s})

@tillweb_view
def session_transactions(request, info, session, sessionid):
    s = session\
        .query(Session)\
        .options(undefer('transactions.total'),
                 joinedload('transactions.payments'))\
        .get(int(sessionid))
    if not s:
        raise Http404

    return ('session-transactions.ajax', {'session': s})

@tillweb_view
def sessiondept(request, info, session, sessionid, dept):
    s = session\
        .query(Session)\
        .get(int(sessionid))
    if not s:
        raise Http404

    dept = session\
           .query(Department)\
           .get(int(dept))
    if not dept:
        raise Http404

    nextlink = info['base'] + s.next.tillweb_url + "dept{}/".format(dept.id) \
        if s.next else None
    prevlink = info['base']+ s.previous.tillweb_url + "dept{}/".format(dept.id) \
        if s.previous else None

    translines = session\
                 .query(Transline)\
                 .join(Transaction)\
                 .options(joinedload('transaction'),
                          joinedload('user'),
                          joinedload_all('stockref.stockitem.stocktype.unit'))\
                 .filter(Transaction.sessionid == s.id)\
                 .filter(Transline.dept_id == dept.id)\
                 .order_by(Transline.id)\
                 .all()

    return ('sessiondept.html',
            {'session': s, 'department': dept,
             'translines': translines,
             'nextlink': nextlink, 'prevlink': prevlink})

@tillweb_view
def transactions_deferred(request, info, session):
    """Page showing all deferred transactions"""
    td = session\
         .query(Transaction)\
         .options(undefer('total'))\
         .filter(Transaction.sessionid == None)\
         .all()
    return ('transactions-deferred.html', {'transactions': td})

@tillweb_view
def transaction(request, info, session, transid):
    # XXX now that we store transaction descriptions explicitly, we
    # may not need to joinedload lines.stockref.stockitem.stocktype
    # and this will end up as a much simpler query.  Wait until old
    # transaction data has been migrated, though, because the web
    # interface is still used to look at old data.
    t = session\
        .query(Transaction)\
        .options(subqueryload_all('payments'),
                 joinedload('lines.department'),
                 joinedload_all('lines.stockref.stockitem.stocktype'),
                 joinedload('lines.user'),
                 undefer('total'))\
        .get(int(transid))
    if not t:
        raise Http404
    return ('transaction.html', {'transaction': t})

@tillweb_view
def transline(request, info, session, translineid):
    tl = session\
         .query(Transline)\
         .options(joinedload_all('stockref.stockitem.stocktype'),
                  joinedload('user'))\
         .get(int(translineid))
    if not tl:
        raise Http404
    return ('transline.html', {'tl': tl})

@tillweb_view
def supplierlist(request, info, session):
    sl = session\
         .query(Supplier)\
         .order_by(Supplier.name)\
         .all()
    return ('suppliers.html', {'suppliers': sl})

@tillweb_view
def supplier(request, info, session, supplierid):
    s = session\
        .query(Supplier)\
        .get(int(supplierid))
    if not s:
        raise Http404
    return ('supplier.html', {'supplier': s})

@tillweb_view
def deliverylist(request, info, session):
    dl = session\
         .query(Delivery)\
         .order_by(desc(Delivery.id))\
         .options(joinedload('supplier'))\
         .all()
    return ('deliveries.html', {'deliveries': dl})

@tillweb_view
def delivery(request, info, session, deliveryid):
    d = session\
        .query(Delivery)\
        .options(joinedload_all('items.stocktype.unit'),
                 joinedload_all('items.stockline'),
                 undefer_qtys('items'))\
        .get(int(deliveryid))
    if not d:
        raise Http404
    return ('delivery.html', {'delivery': d})

class StockTypeForm(forms.Form):
    manufacturer = forms.CharField(required=False)
    name = forms.CharField(required=False)
    shortname = forms.CharField(required=False)

    def is_filled_in(self):
        cd = self.cleaned_data
        return cd['manufacturer'] or cd['name'] or cd['shortname']

    def filter(self, q):
        cd = self.cleaned_data
        if cd['manufacturer']:
            q = q.filter(StockType.manufacturer.ilike(
                "%{}%".format(cd['manufacturer'])))
        if cd['name']:
            q = q.filter(StockType.name.ilike(
                "%{}%".format(cd['name'])))
        if cd['shortname']:
            q = q.filter(StockType.shortname.ilike(
                "%{}%".format(cd['shortname'])))
        return q

@tillweb_view
def stocktypesearch(request, info, session):
    form = StockTypeForm(request.GET)
    result = []
    if form.is_valid() and form.is_filled_in():
        q = session\
            .query(StockType)\
            .order_by(StockType.dept_id, StockType.manufacturer, StockType.name)
        q = form.filter(q)
        result = q.all()
    return ('stocktypesearch.html', {'form': form, 'stocktypes': result})

@tillweb_view
def stocktype(request, info, session, stocktype_id):
    s = session\
        .query(StockType)\
        .get(int(stocktype_id))
    if not s:
        raise Http404
    include_finished = request.GET.get("show_finished", "off") == "on"
    items = session\
            .query(StockItem)\
            .filter(StockItem.stocktype == s)\
            .options(undefer_group('qtys'),
                     joinedload('delivery'))\
            .order_by(desc(StockItem.id))
    if not include_finished:
        items = items.filter(StockItem.finished == None)
    items = items.all()
    return ('stocktype.html',
            {'stocktype': s, 'items': items,
             'include_finished': include_finished})

class StockForm(StockTypeForm):
    include_finished = forms.BooleanField(
        required=False, label="Include finished items")

@tillweb_view
def stocksearch(request,info,session):
    form = StockForm(request.GET)
    result = []
    if form.is_valid() and form.is_filled_in():
        q = session\
            .query(StockItem)\
            .join(StockType)\
            .order_by(StockItem.id)\
            .options(joinedload_all('stocktype.unit'),
                     joinedload('stockline'),
                     joinedload('delivery'),
                     undefer_group('qtys'))
        q = form.filter(q)
        if not form.cleaned_data['include_finished']:
            q = q.filter(StockItem.finished == None)
        result = q.all()
    return ('stocksearch.html', {'form': form, 'stocklist': result})

@tillweb_view
def stock(request, info, session, stockid):
    s = session\
        .query(StockItem)\
        .options(joinedload_all('stocktype.department'),
                 joinedload_all('stocktype.stockline_log.stockline'),
                 joinedload_all('delivery.supplier'),
                 joinedload_all('stockunit.unit'),
                 joinedload_all('annotations.type'),
                 subqueryload_all('out.transline.transaction'),
                 undefer_group('qtys'))\
        .get(int(stockid))
    if not s:
        raise Http404
    return ('stock.html', {'stock': s})

@tillweb_view
def stocklinelist(request, info, session):
    regular = session\
              .query(StockLine)\
              .order_by(StockLine.dept_id, StockLine.name)\
              .filter(StockLine.linetype == "regular")\
              .options(joinedload("stockonsale"))\
              .options(joinedload("stockonsale.stocktype"))\
              .all()
    display = session\
              .query(StockLine)\
              .filter(StockLine.linetype == "display")\
              .order_by(StockLine.name)\
              .options(joinedload("stockonsale"))\
              .options(undefer("stockonsale.used"))\
              .all()
    continuous = session\
                 .query(StockLine)\
                 .filter(StockLine.linetype == "continuous")\
                 .order_by(StockLine.name)\
                 .options(undefer("stocktype.remaining"))\
                 .all()
    return ('stocklines.html', {
        'regular': regular,
        'display': display,
        'continuous': continuous,
    })

@tillweb_view
def stockline(request, info, session, stocklineid):
    s = session\
        .query(StockLine)\
        .options(joinedload_all('stockonsale.stocktype.unit'),
                 joinedload_all('stockonsale.delivery'),
                 undefer_qtys('stockonsale'))\
        .get(int(stocklineid))
    if not s:
        raise Http404
    return ('stockline.html', {'stockline': s})

@tillweb_view
def plulist(request, info, session):
    plus = session\
           .query(PriceLookup)\
           .order_by(PriceLookup.dept_id, PriceLookup.description)\
           .all()
    return ('plus.html', {'plus': plus})

@tillweb_view
def plu(request, info, session, pluid):
    p = session\
        .query(PriceLookup)\
        .get(int(pluid))
    if not p:
        raise Http404
    return ('plu.html', {'plu': p})

@tillweb_view
def departmentlist(request, info, session):
    depts = session\
            .query(Department)\
            .order_by(Department.id)\
            .all()
    return ('departmentlist.html', {'depts': depts})

@tillweb_view
def department(request, info, session, departmentid, as_spreadsheet=False):
    d = session\
        .query(Department)\
        .get(int(departmentid))
    if d is None:
        raise Http404

    include_finished = request.GET.get("show_finished", "off") == "on"
    items = session\
            .query(StockItem)\
            .join(StockType)\
            .filter(StockType.department == d)\
            .order_by(desc(StockItem.id))\
            .options(joinedload_all('stocktype.unit'),
                     undefer_group('qtys'),
                     joinedload('stockline'),
                     joinedload('delivery'),
                     joinedload('finishcode'))
    if not include_finished:
        items = items.filter(StockItem.finished == None)
    items = items.all()

    if as_spreadsheet:
        return spreadsheets.stock(
            session, items, tillname=info['tillname'],
            filename="{}-dept{}-stock.ods".format(
                info['tillname'], departmentid))

    return ('department.html',
            {'department': d, 'items': items,
             'include_finished': include_finished})

class StockCheckForm(forms.Form):
    def __init__(self, depts, *args, **kwargs):
        super(StockCheckForm, self).__init__(*args, **kwargs)
        self.fields['department'].choices = [
            (d.id, d.description) for d in depts]

    short = forms.TextInput(attrs={'size': 3, 'maxlength': 3})
    weeks_ahead = forms.IntegerField(
        label="Weeks ahead", widget=short,
        min_value=0)
    months_behind = forms.IntegerField(
        label="Months behind", widget=short,
        min_value=0)
    minimum_sold = forms.FloatField(
        label="Minimum sold", widget=short,
        min_value=0.0, initial=1.0)
    department = forms.ChoiceField()

@tillweb_view
def stockcheck(request, info, session):
    buylist = []
    depts = session\
            .query(Department)\
            .order_by(Department.id)\
            .all()

    if request.method == 'POST':
        form = StockCheckForm(depts, request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            ahead = datetime.timedelta(days=cd['weeks_ahead'] * 7)
            behind = datetime.timedelta(days=cd['months_behind'] * 30.4)
            min_sale = cd['minimum_sold']
            dept = int(cd['department'])
            r = session\
                .query(StockType, func.sum(StockOut.qty) / behind.days)\
                .join(StockItem)\
                .join(StockOut)\
                .options(lazyload(StockType.department),
                         lazyload(StockType.unit),
                         undefer(StockType.instock))\
                .filter(StockOut.removecode_id == 'sold')\
                .filter((func.now() - StockOut.time) < behind)\
                .filter(StockType.dept_id == dept)\
                .having(func.sum(StockOut.qty) / behind.days > min_sale)\
                .group_by(StockType)\
                .all()
            buylist = [(st, '{:0.1f}'.format(sold),
                        '{:0.1f}'.format(sold * ahead.days - st.instock))
                       for st, sold in r]
            buylist.sort(key=lambda l: float(l[2]), reverse=True)
    else:
        form = StockCheckForm(depts)
    return ('stockcheck.html', {'form': form, 'buylist': buylist})

@tillweb_view
def userlist(request, info, session):
    q = session\
        .query(User)\
        .order_by(User.fullname)
    include_inactive = request.GET.get("include_inactive", "off") == "on"
    if not include_inactive:
        q = q.filter(User.enabled == True)
    users = q.all()
    return ('userlist.html',
            {'users': users, 'include_inactive': include_inactive})

@tillweb_view
def user(request, info, session, userid):
    u = session\
        .query(User)\
        .get(int(userid))
    if not u:
        raise Http404

    sales = session\
            .query(Transline)\
            .filter(Transline.user == u)\
            .options(joinedload('transaction'),
                     joinedload_all('stockref.stockitem.stocktype.unit'))\
            .order_by(desc(Transline.time))[:50]

    payments = session\
               .query(Payment)\
               .filter(Payment.user == u)\
               .options(joinedload('transaction'),
                        joinedload('paytype'))\
               .order_by(desc(Payment.time))[:50]

    annotations = session\
                  .query(StockAnnotation)\
                  .options(joinedload_all('stockitem.stocktype'),
                           joinedload('type'))\
                  .filter(StockAnnotation.user == u)\
                  .order_by(desc(StockAnnotation.time))[:50]

    return ('user.html',
            {'tuser': u, 'sales': sales, 'payments': payments,
             'annotations': annotations})

import matplotlib
matplotlib.use("SVG")
import matplotlib.pyplot as plt

@tillweb_view
def session_sales_pie_chart(request, info, session, sessionid):
    s = session\
        .query(Session)\
        .get(int(sessionid))
    if not s:
        raise Http404
    dt = s.dept_totals
    fig = plt.figure(figsize=(5, 5))
    ax = fig.add_subplot(1, 1, 1)
    patches, texts = ax.pie(
        [x[1] for x in dt], labels=[x[0].description for x in dt],
        colors=['r', 'g', 'b', 'c', 'y', 'm', 'olive', 'brown', 'orchid',
                'royalblue', 'sienna', 'steelblue'])
    for t in texts:
        t.set_fontsize(8)
    for p in patches:
        p.set_linewidth(0.5)
        p.set_joinstyle("bevel")
    response = HttpResponse(content_type="image/svg+xml")
    # XXX the use of the io.StringIO wrapper is temporary until django's
    # HttpResponse object is fixed, possibly in django-1.10
    # See https://code.djangoproject.com/ticket/25576
    wrapper = io.StringIO()
    fig.savefig(wrapper, format="svg", transparent=True)
    plt.close(fig)
    response.write(wrapper.getvalue())
    return response

@tillweb_view
def session_users_pie_chart(request, info, session, sessionid):
    s = session\
        .query(Session)\
        .get(int(sessionid))
    if not s:
        raise Http404
    ut = s.user_totals
    fig = plt.figure(figsize=(5, 5))
    ax = fig.add_subplot(1, 1, 1)
    patches, texts = ax.pie(
        [x[2] for x in ut], labels=[x[0].fullname for x in ut],
        colors=['r', 'g', 'b', 'c', 'y', 'm', 'olive', 'brown', 'orchid',
                'royalblue', 'sienna', 'steelblue'])
    for t in texts:
        t.set_fontsize(8)
    for p in patches:
        p.set_linewidth(0.5)
        p.set_joinstyle("bevel")
    response = HttpResponse(content_type="image/svg+xml")
    # XXX the use of the io.StringIO wrapper is temporary until django's
    # HttpResponse object is fixed, possibly in django-1.10
    # See https://code.djangoproject.com/ticket/25576
    wrapper = io.StringIO()
    fig.savefig(wrapper, format="svg", transparent=True)
    plt.close(fig)
    response.write(wrapper.getvalue())
    return response
