from django.http import HttpResponse, Http404, HttpResponseRedirect
from django.http import HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render
from django.template import RequestContext, Context
from django.template.loader import get_template, render_to_string
from django.conf import settings
from django import forms
import django.urls
from .models import *
import sqlalchemy
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import subqueryload
from sqlalchemy.orm import joinedload
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
    access = Access.objects.filter(user=request.user).order_by('till__name')
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
# info - a viewutils instance
# session - sqlalchemy database session
#
# They should return either a (template, dict) tuple or a HttpResponse
# instance.

class viewutils:
    """Info and utilities passed to a view function"""
    def __init__(self, **kwargs):
        for a, b in kwargs.items():
            setattr(self, a, b)

    def reverse(self, *args, **kwargs):
        if 'kwargs' in kwargs:
            rev_kwargs = kwargs['kwargs']
        else:
            rev_kwargs = {}
            kwargs['kwargs'] = rev_kwargs
        rev_kwargs["pubname"] = self.pubname
        return django.urls.reverse(*args, **kwargs)

    def user_has_perm(self, action):
        if not self.user:
            return False
        if not self.user.enabled:
            return False
        if self.access == 'R':
            return False
        if self.access == 'F':
            return True
        if self.user.superuser:
            return True
        if not hasattr(self, "_permissions_cache"):
            self._permissions_cache = set(p.id for p in self.user.permissions)
        return action in self._permissions_cache

def tillweb_view(view):
    single_site = getattr(settings, 'TILLWEB_SINGLE_SITE', False)
    tillweb_login_required = getattr(settings, 'TILLWEB_LOGIN_REQUIRED', True)
    def new_view(request, pubname="", *args, **kwargs):
        if single_site:
            till = None
            tillname = settings.TILLWEB_PUBNAME
            access = settings.TILLWEB_DEFAULT_ACCESS
            session = settings.TILLWEB_DATABASE()
            money = settings.TILLWEB_MONEY_SYMBOL
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
            tillname = till.name
            access = access.permission
            money = till.money_symbol
        # At this point, access will be "R", "M" or "F".
        # For anything other than "R" access, we need a quicktill.models.User
        tilluser = None
        if request.user.is_authenticated:
            tilluser = session.query(User)\
                              .options(joinedload('permissions'))\
                              .filter(User.webuser==request.user.username)\
                              .one_or_none()

        try:
            info = viewutils(
                access=access,
                user=tilluser,
                tillname=tillname, # Formatted for people
                pubname=pubname, # Used in url
            )
            result = view(request, info, session, *args, **kwargs)
            if isinstance(result, HttpResponse):
                return result
            t, d = result
            # till is the name of the till
            # access is 'R','M','F'
            defaults = {
                'single_site': single_site, # Used for breadcrumbs
                'till': tillname,
                'access': access,
                'tilluser': tilluser,
                'dtf': dtf,
                'pubname': pubname,
                'version': version,
                'money': money,
            }
            if t.endswith(".ajax"):
                # AJAX content typically is not a fully-formed HTML document.
                # If requested in a non-AJAX context, add a HTML container.
                if not request.is_ajax():
                    defaults['ajax_content'] = 'tillweb/' + t
                    t = 'non-ajax-container.html'
            defaults.update(d)
            return render(request, 'tillweb/' + t, defaults)
        except OperationalError as oe:
            return render(request, "tillweb/operationalerror.html",
                          {'till': till,
                           'pubname': pubname,
                           'access': access,
                           'error': oe},
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

class _pager_page:
    def __init__(self, pager, page):
        self._pager = pager
        self._page = page

    @property
    def page(self):
        return self._page

    def pagelink(self):
        return self._pager.pagelink(self._page)

class Pager:
    """Manage paginated data

    This is similar in idea to the class in django.core.paginator but
    works with sqlalchemy and has a different API.

    preserve_query_parameters is a list of query parameters that
    should be passed through in the pagesize_hidden_inputs() method,
    for the pagesize form to include in the query string when the
    pagesize is changed.
    """
    def __init__(self, request, query, items_per_page=25,
                 preserve_query_parameters=[]):
        self._request = request
        self._query = query
        self._preserve_query_parameters = preserve_query_parameters
        self.page = 1
        self.default_items_per_page = items_per_page
        if 'page' in request.GET:
            try:
                self.page = int(request.GET['page'])
            except:
                pass
        self.items_per_page = items_per_page
        if 'pagesize' in request.GET:
            try:
                self.items_per_page = max(1, int(request.GET['pagesize']))
            except:
                if request.GET['pagesize'] == "All":
                    self.items_per_page = None

        # If the requested page is outside the range of the available items,
        # reset it to 1
        if self.items_per_page:
            if ((self.page - 1) * self.items_per_page) > self.count():
                self.page = 1

    def count(self):
        """Number of items to display
        """
        if not hasattr(self, '_count'):
            self._count = self._query.count()
        return self._count

    def pages(self):
        """Number of pages for all the items
        """
        if self.items_per_page:
            return (self.count() // self.items_per_page) + 1
        return 1

    @property
    def num_pages(self):
        return self.pages()

    def page_range(self):
        return (_pager_page(self, x) for x in range(1, self.pages() + 1))

    def local_page_range(self):
        # 7 pages centered on the current page, unless there are fewer
        # than four pages ahead of or behind the current page
        target = 3
        start = self.page - target
        end = self.page + target
        if start < 1:
            end += 1 - start
        if end > self.pages():
            start += self.pages() - end
        return (_pager_page(self, x) for x in range(
            max(start, 1), min(self.pages(), end) + 1))

    def has_next(self):
        return self.page < self.pages()

    def has_previous(self):
        return self.page > 1

    def has_other_pages(self):
        return self.has_next() or self.has_previous()

    def items(self):
        q = self._query
        if self.items_per_page:
            q = q.offset((self.page - 1) * self.items_per_page)\
                 .limit(self.items_per_page)
        return q.all()

    def pagelink(self, page):
        d = self._request.GET.copy()
        d['page'] = str(page)
        if self.items_per_page != self.default_items_per_page:
            d['pagesize'] = str(self.items_per_page)
        return "?" + d.urlencode()

    def pagesize_hidden_inputs(self):
        return [(x, self._request.GET[x])
                 for x in self._preserve_query_parameters
                 if x in self._request.GET]

    def nextlink(self):
        return self.pagelink(self.page + 1) if self.has_next() else None

    def prevlink(self):
        return self.pagelink(self.page - 1) if self.has_previous() else None

    def firstlink(self):
        return self.pagelink(1) if self.has_previous() else None

    def lastlink(self):
        return self.pagelink(self.pages()) if self.has_next() else None

    def as_html(self):
        return render_to_string("tillweb/pager.html", context={
            'pager': self})

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
                 .options(joinedload('stockonsale')
                          .joinedload('stocktype')
                          .joinedload('unit'))\
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
               .options(joinedload('stockitem')
                        .joinedload('stocktype')
                        .joinedload('unit'),
                        joinedload('stockitem').joinedload('stockline'),
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
    return ('locations.html', {
        'nav': [("Locations", info.reverse('tillweb-locations'))],
        'locations': StockLine.locations(session),
    })

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
    return ('location.html', {
        'nav': [("Locations", info.reverse('tillweb-locations')),
                (location, info.reverse('tillweb-location',
                                        kwargs={'location': location}))],
        'location': location,
        'lines': lines,
    })

class SessionFinderForm(forms.Form):
    session = forms.IntegerField(label="Session ID")

class SessionSheetForm(forms.Form):
    startdate = forms.DateField(label="Start date", required=False)
    enddate = forms.DateField(label="End date", required=False)
    rows = forms.ChoiceField(label="Rows show", choices=[
        ("Sessions", "Sessions"),
        ("Days", "Days"),
        ("Weeks", "Weeks"),
        ])

@tillweb_view
def sessionfinder(request, info, session):
    if request.method == 'POST' and "submit_find" in request.POST:
        form = SessionFinderForm(request.POST)
        if form.is_valid():
            s = session.query(Session).get(form.cleaned_data['session'])
            if s:
                return HttpResponseRedirect(s.get_absolute_url())
            form.add_error(None, "This session does not exist.")
    else:
        form = SessionFinderForm()

    if request.method == 'POST' and "submit_sheet" in request.POST:
        rangeform = SessionSheetForm(request.POST)
        if rangeform.is_valid():
            cd = rangeform.cleaned_data
            return spreadsheets.sessionrange(
                session,
                start=cd['startdate'],
                end=cd['enddate'],
                rows=cd['rows'],
                tillname=info.tillname)
    else:
        rangeform = SessionSheetForm()

    sessions = session\
               .query(Session)\
               .options(undefer('total'),
                        undefer('actual_total'),
                        undefer('discount_total'))\
               .order_by(desc(Session.id))

    pager = Pager(request, sessions)

    return ('sessions.html',
            {'nav': [("Sessions", info.reverse("tillweb-sessions"))],
             'recent': pager.items,
             'pager': pager,
             'nextlink': pager.nextlink(),
             'prevlink': pager.prevlink(),
             'form': form,
             'rangeform': rangeform})

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

    nextlink = s.next.get_absolute_url() if s.next else None
    prevlink = s.previous.get_absolute_url() if s.previous else None

    return ('session.html',
            {'tillobject': s,
             'session': s,
             'nextlink': nextlink,
             'prevlink': prevlink,
            })

@tillweb_view
def session_spreadsheet(request, info, session, sessionid):
    s = session\
        .query(Session)\
        .options(undefer('transactions.total'),
                 joinedload('transactions.payments'))\
        .get(int(sessionid))
    if not s:
        raise Http404
    return spreadsheets.session(session, s, info.tillname)

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
def session_discounts(request, info, session, sessionid):
    s = session\
        .query(Session)\
        .get(int(sessionid))
    if not s:
        raise Http404

    departments = session.query(Department).order_by(Department.id).all()

    discounts = session.query(
        Department,
        Transline.discount_name,
        func.sum(Transline.items * Transline.discount).label("discount"))\
                       .select_from(Transaction)\
                       .join(Transline, Department)\
                       .filter(Transaction.sessionid == sessionid)\
                       .filter(Transline.discount_name != None)\
                       .group_by(Department, Transline.discount_name)\
                       .order_by(Department.id, Transline.discount_name)\
                       .all()
    # discounts table: rows are departments, columns are discount names
    discount_totals = {}
    for d in discounts:
        discount_totals[d.discount_name] = discount_totals.get(d.discount_name, zero) + d.discount
    discount_names = sorted(discount_totals.keys())
    discount_totals = [ discount_totals[x] for x in discount_names ]
    discount_totals.append(sum(discount_totals))

    for d in discounts:
        dept = d.Department
        d_info = getattr(dept, 'd_info', [zero] * (len(discount_names) + 1))
        d_info[discount_names.index(d.discount_name)] = d.discount
        d_info[-1] += d.discount
        dept.d_info = d_info

    return ('session-discounts.ajax',
            {'session': s,
             'departments': departments,
             'discount_names': discount_names,
             'discount_totals': discount_totals,
            })

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
                 undefer('transactions.discount_total'),
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

    nextlink = info.reverse("tillweb-session-department", kwargs={
        'sessionid': s.next.id,
        'dept': dept.id}) if s.next else None
    prevlink = info.reverse("tillweb-session-department", kwargs={
        'sessionid': s.previous.id,
        'dept': dept.id}) if s.previous else None

    translines = session\
                 .query(Transline)\
                 .join(Transaction)\
                 .options(joinedload('transaction'),
                          joinedload('user'),
                          joinedload('stockref').joinedload('stockitem')
                          .joinedload('stocktype').joinedload('unit'))\
                 .filter(Transaction.sessionid == s.id)\
                 .filter(Transline.dept_id == dept.id)\
                 .order_by(Transline.id)\
                 .all()

    return ('sessiondept.html',
            {'nav': s.tillweb_nav() + [
                (dept.description,
                 info.reverse("tillweb-session-department", kwargs={
                     'sessionid': s.id,
                     'dept': dept.id}))],
             'session': s, 'department': dept,
             'translines': translines,
             'nextlink': nextlink, 'prevlink': prevlink})

@tillweb_view
def transactions_deferred(request, info, session):
    """Page showing all deferred transactions"""
    td = session\
         .query(Transaction)\
         .options(undefer('total'))\
         .filter(Transaction.sessionid == None)\
         .order_by(Transaction.id)\
         .all()
    return ('transactions-deferred.html', {
        'transactions': td,
        'nav': [("Deferred transactions", info.reverse('tillweb-deferred-transactions'))],
    })

class TransactionNotesForm(forms.Form):
    notes = forms.CharField(required=False, max_length=60)

@tillweb_view
def transaction(request, info, session, transid):
    t = session\
        .query(Transaction)\
        .options(subqueryload('payments'),
                 joinedload('lines.department'),
                 joinedload('lines.user'),
                 undefer('total'),
                 undefer('discount_total'))\
        .get(int(transid))
    if not t:
        raise Http404

    form = None
    if info.user_has_perm("edit-transaction-note"):
        initial = {'notes': t.notes }
        if request.method == "POST":
            form = TransactionNotesForm(request.POST, initial=initial)
            if form.is_valid():
                cd = form.cleaned_data
                t.notes = cd["notes"]
                session.commit()
                return HttpResponseRedirect(t.get_absolute_url())
        else:
            form = TransactionNotesForm(initial=initial)

    return ('transaction.html', {
        'transaction': t,
        'tillobject': t,
        'form': form,
    })

@tillweb_view
def transline(request, info, session, translineid):
    tl = session\
         .query(Transline)\
         .options(joinedload('stockref').joinedload('stockitem')
                  .joinedload('stocktype'),
                  joinedload('user'))\
         .get(int(translineid))
    if not tl:
        raise Http404
    return ('transline.html', {'tl': tl, 'tillobject': tl})

@tillweb_view
def supplierlist(request, info, session):
    sl = session\
         .query(Supplier)\
         .order_by(Supplier.name)\
         .all()
    return ('suppliers.html', {
        'nav': [("Suppliers", info.reverse("tillweb-suppliers"))],
        'suppliers': sl,
    })

@tillweb_view
def supplier(request, info, session, supplierid):
    s = session\
        .query(Supplier)\
        .get(int(supplierid))
    if not s:
        raise Http404

    deliveries = session\
                 .query(Delivery)\
                 .order_by(desc(Delivery.id))\
                 .filter(Delivery.supplier == s)

    pager = Pager(request, deliveries)
    return ('supplier.html', {
        'tillobject': s,
        'supplier': s,
        'pager': pager,
    })

@tillweb_view
def deliverylist(request, info, session):
    dl = session\
         .query(Delivery)\
         .order_by(desc(Delivery.id))\
         .options(joinedload('supplier'))

    pager = Pager(request, dl)

    return ('deliveries.html', {
        'nav': [("Deliveries", info.reverse("tillweb-deliveries"))],
                'pager': pager,
        })

@tillweb_view
def delivery(request, info, session, deliveryid):
    d = session\
        .query(Delivery)\
        .options(joinedload('items').joinedload('stocktype')
                 .joinedload('unit'),
                 joinedload('items').joinedload('stockline'),
                 undefer_qtys('items'))\
        .get(int(deliveryid))
    if not d:
        raise Http404
    return ('delivery.html', {
        'tillobject': d,
        'delivery': d,
    })

class StockTypeForm(forms.Form):
    manufacturer = forms.CharField(required=False)
    name = forms.CharField(required=False)

    def is_filled_in(self):
        cd = self.cleaned_data
        return cd['manufacturer'] or cd['name']

    def filter(self, q):
        cd = self.cleaned_data
        if cd['manufacturer']:
            q = q.filter(StockType.manufacturer.ilike(
                "%{}%".format(cd['manufacturer'])))
        if cd['name']:
            q = q.filter(StockType.name.ilike(
                "%{}%".format(cd['name'])))
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
    return ('stocktypesearch.html', {
        'nav': [("Stock types", info.reverse("tillweb-stocktype-search"))],
        'form': form,
        'stocktypes': result,
    })

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
            {'tillobject': s,
             'stocktype': s,
             'items': items,
             'include_finished': include_finished,
            })

class StockForm(StockTypeForm):
    include_finished = forms.BooleanField(
        required=False, label="Include finished items")

@tillweb_view
def stocksearch(request, info, session):
    form = StockForm(request.GET)
    pager = None
    if form.is_valid() and form.is_filled_in():
        q = session\
            .query(StockItem)\
            .join(StockType)\
            .order_by(StockItem.id)\
            .options(joinedload('stocktype').joinedload('unit'),
                     joinedload('stockline'),
                     joinedload('delivery'),
                     undefer_group('qtys'))
        q = form.filter(q)
        if not form.cleaned_data['include_finished']:
            q = q.filter(StockItem.finished == None)

        pager = Pager(request, q, preserve_query_parameters=[
            "manufacturer", "name", "include_finished"])

    return ('stocksearch.html', {
        'nav': [("Stock", info.reverse("tillweb-stocksearch"))],
        'form': form,
        'stocklist': pager.items() if pager else [],
        'pager': pager})

@tillweb_view
def stock(request, info, session, stockid):
    s = session\
        .query(StockItem)\
        .options(joinedload('stocktype').joinedload('department'),
                 joinedload('stocktype').joinedload('stockline_log')
                 .joinedload('stockline'),
                 joinedload('delivery').joinedload('supplier'),
                 joinedload('stockunit').joinedload('unit'),
                 joinedload('annotations').joinedload('type'),
                 subqueryload('out').subqueryload('transline')
                 .subqueryload('transaction'),
                 undefer_group('qtys'))\
        .get(int(stockid))
    if not s:
        raise Http404
    return ('stock.html', {
        'tillobject': s,
        'stock': s,
    })

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
        'nav': [("Stock lines", info.reverse("tillweb-stocklines"))],
        'regular': regular,
        'display': display,
        'continuous': continuous,
    })

@tillweb_view
def stockline(request, info, session, stocklineid):
    s = session\
        .query(StockLine)\
        .options(joinedload('stockonsale').joinedload('stocktype')
                 .joinedload('unit'),
                 joinedload('stockonsale').joinedload('delivery'),
                 undefer_qtys('stockonsale'))\
        .get(int(stocklineid))
    if not s:
        raise Http404
    return ('stockline.html', {
        'tillobject': s,
        'stockline': s,
    })

@tillweb_view
def plulist(request, info, session):
    plus = session\
           .query(PriceLookup)\
           .order_by(PriceLookup.dept_id, PriceLookup.description)\
           .all()

    may_create_plu = info.user_has_perm("create-plu")

    return ('plus.html', {
        'nav': [("Price lookups", info.reverse("tillweb-plus"))],
        'plus': plus,
        'may_create_plu': may_create_plu,
    })

class PLUForm(forms.Form):
    def __init__(self, depts, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['department'].choices = [
            (d.id, d.description) for d in depts]

    description = forms.CharField()
    department = forms.ChoiceField()
    note = forms.CharField(required=False)
    price = forms.DecimalField(
        required=False, min_value=zero,
        max_digits=money_max_digits, decimal_places=money_decimal_places)
    altprice1 = forms.DecimalField(
        required=False, min_value=zero,
        max_digits=money_max_digits, decimal_places=money_decimal_places)
    altprice2 = forms.DecimalField(
        required=False, min_value=zero,
        max_digits=money_max_digits, decimal_places=money_decimal_places)
    altprice3 = forms.DecimalField(
        required=False, min_value=zero,
        max_digits=money_max_digits, decimal_places=money_decimal_places)

@tillweb_view
def plu(request, info, session, pluid):
    p = session\
        .query(PriceLookup)\
        .get(int(pluid))
    if not p:
        raise Http404

    form = None
    if info.user_has_perm("alter-plu"):
        depts = session\
                .query(Department)\
                .order_by(Department.id)\
                .all()
        initial = {
            'description': p.description,
            'note': p.note,
            'department': p.department.id,
            'price': p.price,
            'altprice1': p.altprice1,
            'altprice2': p.altprice2,
            'altprice3': p.altprice3,
        }
        if request.method == "POST":
            if 'submit_delete' in request.POST:
                messages.success(request, "Price lookup '{}' deleted.".format(p.description))
                session.delete(p)
                session.commit()
                return HttpResponseRedirect(info.reverse("tillweb-plus"))
            form = PLUForm(depts, request.POST, initial=initial)
            if form.is_valid():
                cd = form.cleaned_data
                p.description = cd['description']
                p.note = cd['note']
                p.dept_id = cd['department']
                p.price = cd['price']
                p.altprice1 = cd['altprice1']
                p.altprice2 = cd['altprice2']
                p.altprice3 = cd['altprice3']
                session.commit()
                messages.success(request, "Price lookup '{}' updated.".format(p.description))
                return HttpResponseRedirect(p.get_absolute_url())
        else:
            form = PLUForm(depts, initial=initial)

    return ('plu.html', {
        'tillobject': p,
        'plu': p,
        'form': form,
    })

@tillweb_view
def create_plu(request, info, session):
    if not info.user_has_perm("create-plu"):
        return HttpResponseForbidden("You don't have permission to create new price lookups")

    depts = session\
            .query(Department)\
            .order_by(Department.id)\
            .all()

    if request.method == "POST":
        form = PLUForm(depts, request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            p = PriceLookup(
                description=cd['description'],
                note=cd['note'],
                dept_id=cd['department'],
                price=cd['price'],
                altprice1=cd['altprice1'],
                altprice2=cd['altprice2'],
                altprice3=cd['altprice3'])
            session.add(p)
            session.commit()
            messages.success(request, "Price lookup '{}' created.".format(p.description))
            return HttpResponseRedirect(p.get_absolute_url())
    else:
        form = PLUForm(depts)

    return ('new-plu.html', {
        'nav': [("Price lookups", info.reverse("tillweb-plus")),
                ("New", info.reverse("tillweb-create-plu"))],
        'form': form,
    })

@tillweb_view
def departmentlist(request, info, session):
    depts = session\
            .query(Department)\
            .order_by(Department.id)\
            .all()
    return ('departmentlist.html', {
        'nav': [("Departments", info.reverse("tillweb-departments"))],
        'depts': depts,
    })

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
            .options(joinedload('stocktype').joinedload('unit'),
                     undefer_group('qtys'),
                     joinedload('stockline'),
                     joinedload('delivery'),
                     joinedload('finishcode'))
    if not include_finished:
        items = items.filter(StockItem.finished == None)

    if as_spreadsheet:
        return spreadsheets.stock(
            session, items.all(), tillname=info.tillname,
            filename="{}-dept{}-stock.ods".format(
                info.tillname, departmentid))

    pager = Pager(request, items, preserve_query_parameters=["show_finished"])

    return ('department.html',
            {'tillobject': d,
             'department': d, 'pager': pager,
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
    return ('stockcheck.html', {
        'nav': [("Buying list", info.reverse("tillweb-stockcheck"))],
        'form': form,
        'buylist': buylist,
    })

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
            {'nav': [("Users", info.reverse("tillweb-till-users"))],
             'users': users,
             'include_inactive': include_inactive,
            })

class EditUserForm(forms.Form):
    fullname = forms.CharField()
    shortname = forms.CharField()
    web_username = forms.CharField(required=False)
    enabled = forms.BooleanField(required=False)
    groups = forms.MultipleChoiceField()

    def __init__(self, groups, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['groups'].choices = groups

@tillweb_view
def user(request, info, session, userid):
    u = session\
        .query(User)\
        .get(int(userid))
    if not u:
        raise Http404

    form = None
    if not u.superuser and info.user_has_perm("edit-user"):
        groups = session.query(Group).order_by(Group.id).all()
        gchoices = [ (g.id, "{g.id} — {g.description}".format(g=g))
                     for g in groups ]
        initial = {
            'fullname': u.fullname,
            'shortname': u.shortname,
            'web_username': u.webuser,
            'enabled': u.enabled,
            'groups': [g.id for g in u.groups],
        }
        if request.method == "POST":
            form = EditUserForm(gchoices, request.POST, initial=initial)
            if form.is_valid():
                cd = form.cleaned_data
                u.fullname = cd['fullname']
                u.shortname = cd['shortname']
                u.webuser = cd['web_username'] if cd['web_username'] else None
                u.enabled = cd['enabled']
                u.groups = [
                    session.query(Group).get(g)
                    for g in cd['groups'] ]
                try:
                    session.commit()
                    messages.success(request, "User '{}' updated.".format(
                        u.fullname))
                    return HttpResponseRedirect(u.get_absolute_url())
                except sqlalchemy.exc.IntegrityError:
                    session.rollback()
                    form.add_error("web_username", "Username already in use")
                    messages.error(
                        request, "Could not update user: the web username "
                        "is already in use by another till user")
        else:
            form = EditUserForm(gchoices, initial=initial)

    sales = session\
            .query(Transline)\
            .filter(Transline.user == u)\
            .options(joinedload('transaction'),
                     joinedload('stockref').joinedload('stockitem')
                     .joinedload('stocktype').joinedload('unit'))\
            .order_by(desc(Transline.time))[:50]

    payments = session\
               .query(Payment)\
               .filter(Payment.user == u)\
               .options(joinedload('transaction'),
                        joinedload('paytype'))\
               .order_by(desc(Payment.time))[:50]

    annotations = session\
                  .query(StockAnnotation)\
                  .options(joinedload('stockitem').joinedload('stocktype'),
                           joinedload('type'))\
                  .filter(StockAnnotation.user == u)\
                  .order_by(desc(StockAnnotation.time))[:50]

    return ('user.html',
            {'tillobject': u,
             'tuser': u,
             'sales': sales,
             'payments': payments,
             'annotations': annotations,
             'form': form,
            })

@tillweb_view
def grouplist(request, info, session):
    groups = session\
             .query(Group)\
             .order_by(Group.id)\
             .all()

    return ('grouplist.html',
            {'nav': [("Groups", info.reverse("tillweb-till-groups"))],
             'groups': groups,
            })

class EditGroupForm(forms.Form):
    name = forms.CharField()
    description = forms.CharField()
    permissions = forms.MultipleChoiceField()

    def __init__(self, permissions, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['permissions'].choices = permissions

@tillweb_view
def group(request, info, session, groupid):
    g = session\
        .query(Group)\
        .get(groupid)
    if not g:
        raise Http404

    form = None

    # XXX may want to introduce a permission for editing groups?
    # edit-user is the closest I could find
    if info.user_has_perm("edit-user"):
        permissions = session.query(Permission).order_by(Permission.id).all()
        pchoices = [ (p.id, "{p.id} — {p.description}".format(p=p))
                     for p in permissions ]
        initial = {
            'name': g.id,
            'description': g.description,
            'permissions': [p.id for p in g.permissions],
        }
        if request.method == "POST":
            if 'submit_delete' in request.POST:
                messages.success(request, "Group '{}' deleted.".format(g.id))
                session.delete(g)
                session.commit()
                return HttpResponseRedirect(info.reverse("tillweb-till-groups"))
            form = EditGroupForm(pchoices, request.POST, initial=initial)
            if form.is_valid():
                cd = form.cleaned_data
                changed = form.changed_data
                g.id = cd['name']
                g.description = cd['description']
                g.permissions = [
                    session.query(Permission).get(p)
                    for p in cd['permissions'] ]
                session.commit()
                messages.success(request, "Group '{}' updated.".format(g.id))
                return HttpResponseRedirect(g.get_absolute_url())
        else:
            form = EditGroupForm(pchoices, initial=initial)

    return ('group.html',
            {'tillobject': g,
             'group': g,
             'form': form,
             'can_delete': len(g.users) == 0,
            })

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

class WasteReportForm(forms.Form):
    startdate = forms.DateField(label="Start date", required=False)
    enddate = forms.DateField(label="End date", required=False)
    columns = forms.ChoiceField(label="Columns show", choices=[
        ("depts", "Departments"),
        ("waste", "Waste type"),
    ])

class StockSoldReportForm(forms.Form):
    startdate = forms.DateField(label="Start date", required=False)
    enddate = forms.DateField(label="End date", required=False)
    dates = forms.ChoiceField(label="Based on", choices=[
        ("transaction", "Transaction Date"),
        ("stockusage", "Date entered"),
    ])

@tillweb_view
def reportindex(request, info, session):
    if request.method == 'POST' and "submit_waste" in request.POST:
        wasteform = WasteReportForm(request.POST, prefix="waste")
        if wasteform.is_valid():
            cd = wasteform.cleaned_data
            return spreadsheets.waste(
                session,
                start=cd['startdate'],
                end=cd['enddate'],
                cols=cd['columns'],
                tillname=info.tillname)
    else:
        wasteform = WasteReportForm(prefix="waste")

    if request.method == 'POST' and "submit_stocksold" in request.POST:
        stocksoldform = StockSoldReportForm(request.POST, prefix="stocksold")
        if stocksoldform.is_valid():
            cd = stocksoldform.cleaned_data
            return spreadsheets.stocksold(
                session,
                start=cd['startdate'],
                end=cd['enddate'],
                dates=cd['dates'],
                tillname=info.tillname)
    else:
        stocksoldform = StockSoldReportForm(prefix="stocksold")

    return ('reports.html',
            {'nav': [("Reports", info.reverse("tillweb-reports"))],
             'wasteform': wasteform,
             'stocksoldform': stocksoldform,
            })
