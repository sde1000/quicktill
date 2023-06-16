from django.http import HttpResponse, Http404, HttpResponseRedirect
from django.http import HttpResponseForbidden
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render
from django.template.loader import render_to_string
from django.conf import settings
from django import forms
from django.core.exceptions import ValidationError
import django.urls
from .models import Till, Access
import sqlalchemy
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import subqueryload
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import lazyload
from sqlalchemy.orm import defaultload
from sqlalchemy.orm import undefer, undefer_group
from sqlalchemy.sql import select, desc
from sqlalchemy.sql.expression import tuple_, func, null
from sqlalchemy import distinct
from quicktill.models import (
    StockType,
    LogEntry,
    User,
    Business,
    Transline,
    VatBand,
    Department,
    Session,
    SessionTotal,
    StockLine,
    StockAnnotation,
    StockItem,
    Transaction,
    Delivery,
    Supplier,
    StockUnit,
    StockTake,
    Unit,
    AnnotationType,
    RemoveCode,
    StockOut,
    PriceLookup,
    Barcode,
    Group,
    Permission,
    Config,
    Payment,
    PayType,
    money_max_digits,
    money_decimal_places,
    qty_max_digits,
    qty_decimal_places,
    abv_max_digits,
    abv_decimal_places,
    min_quantity,
    min_abv_value,
    max_abv_value,
    zero,
)
from quicktill.version import version
from . import spreadsheets
import datetime
import logging
from .db import td
from .forms import SQLAModelChoiceField
from .forms import StringIDMultipleChoiceField
from .forms import StringIDChoiceField
from .forms import Select2, Select2Ajax


log = logging.getLogger(__name__)

# We use this date format in templates - defined here so we don't have
# to keep repeating it.  It's available in templates as 'dtf'
dtf = "Y-m-d H:i"


# Colour cycle for charts etc.
# Taken from https://sashamaps.net/docs/resources/20-colors/
colours = [
    '230, 25, 75',    # Red
    '60, 180, 75',    # Green
    '255, 225, 25',   # Yellow
    '0, 130, 200',    # Blue
    '245, 130, 48',   # Orange
    '145, 30, 180',   # Purple
    '70, 240, 240',   # Cyan
    '240, 50, 230',   # Magenta
    '210, 245, 60',   # Lime
    '250, 190, 212',  # Pink
    '0, 128, 128',    # Teal
    '220, 190, 255',  # Lavendar
    '170, 110, 40',   # Brown
    '255, 250, 200',  # Beige
    '128, 0, 0',      # Maroon
    '170, 255, 195',  # Mint
    '128, 128, 0',    # Olive
    '255, 215, 180',  # Apricot
    '0, 0, 128',      # Navy
    '128, 128, 128',  # Grey
    '255, 255, 255',  # White
    '0, 0, 0',        # Black
]


# Custom DateInput widget: use ISO 8601 dates only
class DateInput(forms.DateInput):
    def __init__(self, *args, **kwargs):
        attrs = kwargs.setdefault('attrs', {})
        attrs['autocomplete'] = 'off'

        # Uncomment the next line to enable native datepickers
        # attrs['type'] = 'date'

        super().__init__(*args, **kwargs, format='%Y-%m-%d')


# Several forms require the user to input an optional date period first
class DatePeriodForm(forms.Form):
    startdate = forms.DateField(label="Start date", required=False,
                                widget=DateInput)
    enddate = forms.DateField(label="End date", required=False,
                              widget=DateInput)

    def clean(self):
        cd = super().clean()
        if cd['startdate'] and cd['enddate'] \
           and cd['startdate'] > cd['enddate']:
            self.add_error('startdate', 'Start date cannot be after end date')
        return cd


# Format a StockType model as a string for Select widgets
def stocktype_widget_label(x):
    return f"{x.format()} ({x.department}, sold in {x.unit.item_name_plural})"


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
#
# They should return either a (template, dict) tuple or a HttpResponse
# instance.

class viewutils:
    """Info and utilities passed to a view function"""
    def __init__(self, **kwargs):
        for a, b in kwargs.items():
            setattr(self, a, b)

    def reverse(self, *args, **kwargs):
        rev_kwargs = kwargs.setdefault('kwargs', {})
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


class user:
    @staticmethod
    def log(message):
        """Record an entry in the user activity log

        NB does not commit automatically
        """
        l = LogEntry(source="Web",
                     sourceaddr=td.request.META['REMOTE_ADDR'],
                     loguser=td.info.user,
                     description=message)
        l.update_refs(td.s)
        td.s.add(l)


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
                              .filter(User.webuser == request.user.username)\
                              .one_or_none()

        try:
            if settings.DEBUG:
                queries_before_render = 0
                queries = []

                def querylog_callback(_conn, _cur, query, params, *_):
                    queries.append(query)

                sqlalchemy.event.listen(
                    session.get_bind(), "before_cursor_execute",
                    querylog_callback)

            info = viewutils(
                access=access,
                user=tilluser,
                tillname=tillname,  # Formatted for people
                pubname=pubname,  # Used in url
                money=money,
            )
            td.request = request
            td.info = info
            td.s = session
            result = view(request, info, *args, **kwargs)
            if settings.DEBUG:
                queries_before_render = len(queries)
            if isinstance(result, HttpResponse):
                return result
            t, d = result
            # till is the name of the till
            # access is 'R','M','F'
            defaults = {
                'single_site': single_site,  # Used for breadcrumbs
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
            if settings.DEBUG:
                sqlalchemy.event.remove(
                    session.get_bind(), "before_cursor_execute",
                    querylog_callback)
                if len(queries) > 3:
                    log.warning(
                        "Excessive queries in view (%d pre render, %d "
                        "during render)",
                        queries_before_render,
                        len(queries) - queries_before_render)

            td.s = None
            td.request = None
            td.info = None
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


def business_totals(firstday, lastday):
    # This query is wrong in that it ignores the 'business' field in
    # VatRate objects.  Fixes that don't involve a database round-trip
    # per session are welcome!
    return td.s.query(Business,
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
            except Exception:
                pass
        self.items_per_page = items_per_page
        if 'pagesize' in request.GET:
            try:
                self.items_per_page = max(1, int(request.GET['pagesize']))
            except Exception:
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
def pubroot(request, info):
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
              business_totals(thisweek_start, thisweek_end)),
             ("Last week", lastweek_start, lastweek_end,
              business_totals(lastweek_start, lastweek_end)),
             ("The week before last", weekbefore_start, weekbefore_end,
              business_totals(weekbefore_start, weekbefore_end))]

    # currentsession = Session.current(session)
    currentsession = td.s.query(Session)\
                         .filter_by(endtime=None)\
                         .options(undefer('total'),
                                  undefer('closed_total'))\
                         .first()

    barsummary = td.s.query(StockLine)\
                     .filter(StockLine.location == "Bar")\
                     .order_by(StockLine.dept_id, StockLine.name)\
                     .options(joinedload('stockonsale')
                              .joinedload('stocktype')
                              .joinedload('unit'))\
                     .options(undefer_qtys("stockonsale"))\
                     .all()

    stillage = td.s.query(StockAnnotation)\
                   .join(StockItem)\
                   .outerjoin(StockLine)\
                   .filter(
                       tuple_(StockAnnotation.text, StockAnnotation.time).in_(
                           select([StockAnnotation.text,
                                   func.max(StockAnnotation.time)],
                                  StockAnnotation.atype == 'location')
                           .group_by(StockAnnotation.text)))\
                   .filter(StockItem.finished == None)\
                   .order_by(StockLine.name != null(), StockAnnotation.time)\
                   .options(joinedload('stockitem')
                            .joinedload('stocktype')
                            .joinedload('unit'),
                            joinedload('stockitem').joinedload('stockline'),
                            undefer_qtys('stockitem'))\
                   .all()

    deferred = td.s.query(func.sum(Transline.items * Transline.amount))\
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
def locationlist(request, info):
    return ('locations.html', {
        'nav': [("Locations", info.reverse('tillweb-locations'))],
        'locations': StockLine.locations(td.s),
    })


@tillweb_view
def location(request, info, location):
    lines = td.s.query(StockLine)\
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


class SessionSheetForm(DatePeriodForm):
    rows = forms.ChoiceField(label="Rows show", choices=[
        ("Sessions", "Sessions"),
        ("Days", "Days"),
        ("Weeks", "Weeks"),
    ])


@tillweb_view
def sessions(request, info):
    if request.method == 'POST' and "submit_sheet" in request.POST:
        rangeform = SessionSheetForm(request.POST)
        if rangeform.is_valid():
            cd = rangeform.cleaned_data
            return spreadsheets.sessionrange(
                start=cd['startdate'],
                end=cd['enddate'],
                rows=cd['rows'],
                tillname=info.tillname)
    else:
        rangeform = SessionSheetForm()

    return ('sessions.html',
            {'nav': [("Sessions", info.reverse("tillweb-sessions"))],
             'rangeform': rangeform,
             })


@tillweb_view
def session(request, info, sessionid):
    s = td.s.query(Session)\
            .options(undefer('total'),
                     undefer('closed_total'),
                     undefer('actual_total'))\
            .get(sessionid)
    if not s:
        raise Http404

    nextlink = s.next.get_absolute_url() if s.next else None
    prevlink = s.previous.get_absolute_url() if s.previous else None

    totals = td.s.query(SessionTotal)\
                 .join(PayType)\
                 .order_by(PayType.order, PayType.paytype)\
                 .filter(SessionTotal.sessionid == sessionid)\
                 .all()

    return ('session.html',
            {'tillobject': s,
             'session': s,
             'totals': totals,
             'nextlink': nextlink,
             'prevlink': prevlink,
             })


@tillweb_view
def session_spreadsheet(request, info, sessionid):
    s = td.s.query(Session)\
            .options(undefer('transactions.total'),
                     joinedload('transactions.payments'))\
            .get(sessionid)
    if not s:
        raise Http404
    return spreadsheets.session(s, info.tillname)


@tillweb_view
def session_discounts(request, info, sessionid):
    s = td.s.query(Session).get(sessionid)
    if not s:
        raise Http404

    departments = td.s.query(Department).order_by(Department.id).all()

    discounts = td.s.query(Department,
                           Transline.discount_name,
                           func.sum(Transline.items * Transline.discount)
                           .label("discount"))\
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
        discount_totals[d.discount_name] = discount_totals.get(
            d.discount_name, zero) + d.discount
    discount_names = sorted(discount_totals.keys())
    discount_totals = [discount_totals[x] for x in discount_names]
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
def session_stock_sold(request, info, sessionid):
    s = td.s.query(Session).get(sessionid)
    if not s:
        raise Http404

    return ('session-stock-sold.ajax', {'session': s})


@tillweb_view
def session_transactions(request, info, sessionid):
    s = td.s.query(Session)\
            .options(undefer('transactions.total'),
                     undefer('transactions.discount_total'),
                     joinedload('transactions.payments'))\
            .get(sessionid)
    if not s:
        raise Http404

    return ('session-transactions.ajax', {'session': s})


@tillweb_view
def sessiondept(request, info, sessionid, dept):
    s = td.s.query(Session).get(sessionid)
    if not s:
        raise Http404

    dept = td.s.query(Department).get(dept)
    if not dept:
        raise Http404

    nextlink = info.reverse("tillweb-session-department", kwargs={
        'sessionid': s.next.id,
        'dept': dept.id}) if s.next else None
    prevlink = info.reverse("tillweb-session-department", kwargs={
        'sessionid': s.previous.id,
        'dept': dept.id}) if s.previous else None

    translines = td.s.query(Transline)\
                     .join(Transaction)\
                     .options(joinedload('transaction'),
                              joinedload('user'),
                              joinedload('stockref').joinedload('stockitem')
                              .joinedload('stocktype').joinedload('unit'))\
                     .filter(Transaction.sessionid == s.id)\
                     .filter(Transline.dept_id == dept.id)\
                     .order_by(Transline.id)\
                     .all()

    return ('sessiondept.html', {
        'nav': s.tillweb_nav() + [
            (dept.description,
             info.reverse("tillweb-session-department", kwargs={
                 'sessionid': s.id,
                 'dept': dept.id}))],
        'session': s, 'department': dept,
        'translines': translines,
        'nextlink': nextlink,
        'prevlink': prevlink,
    })


@tillweb_view
def transactions_deferred(request, info):
    """Page showing all deferred transactions"""
    t = td.s.query(Transaction)\
            .options(undefer('total'))\
            .filter(Transaction.sessionid == None)\
            .order_by(Transaction.id)\
            .all()
    return ('transactions-deferred.html', {
        'transactions': t,
        'nav': [("Deferred transactions",
                 info.reverse('tillweb-deferred-transactions'))],
    })


class TransactionNotesForm(forms.Form):
    notes = forms.CharField(required=False, max_length=60)


@tillweb_view
def transaction(request, info, transid):
    t = td.s.query(Transaction)\
            .options(subqueryload('payments'),
                     joinedload('lines.department'),
                     joinedload('lines.user'),
                     undefer('total'),
                     undefer('discount_total'))\
            .get(transid)
    if not t:
        raise Http404

    form = None
    if info.user_has_perm("edit-transaction-note"):
        initial = {'notes': t.notes}
        if request.method == "POST":
            form = TransactionNotesForm(request.POST, initial=initial)
            if form.is_valid():
                cd = form.cleaned_data
                t.notes = cd["notes"]
                td.s.commit()
                return HttpResponseRedirect(t.get_absolute_url())
        else:
            form = TransactionNotesForm(initial=initial)

    return ('transaction.html', {
        'transaction': t,
        'tillobject': t,
        'form': form,
    })


@tillweb_view
def transline(request, info, translineid):
    tl = td.s.query(Transline)\
             .options(joinedload('stockref').joinedload('stockitem')
                      .joinedload('stocktype'),
                      joinedload('user'))\
             .get(translineid)
    if not tl:
        raise Http404
    return ('transline.html', {'tl': tl, 'tillobject': tl})


@tillweb_view
def payment(request, info, paymentid):
    payment = td.s.query(Payment)\
                  .options(joinedload('paytype'),
                           joinedload('user'))\
                  .get(paymentid)
    if not payment:
        raise Http404
    return ('payment.html', {'payment': payment, 'tillobject': payment})


@tillweb_view
def paytypelist(request, info):
    paytypes = td.s.query(PayType)\
                   .order_by(PayType.order, PayType.paytype)\
                   .all()

    may_manage_paytypes = info.user_has_perm("manage-payment-methods")

    if may_manage_paytypes and request.method == "POST":
        for pt in paytypes:
            key = f"paytype_{pt.paytype}_order"
            try:
                pt.order = int(request.POST.get(key))
            except Exception:
                pass
        user.log(
            "Changed order of payment methods to: "
            + ', '.join(pt.description for pt in paytypes
                        if pt.mode != 'disabled'))
        td.s.commit()
        messages.info(request, "Payment method order saved")
        return HttpResponseRedirect(info.reverse("tillweb-paytypes"))

    return ('paytypelist.html', {
        'nav': [("Payment methods", info.reverse("tillweb-paytypes"))],
        'paytypes': paytypes,
        'may_create_paytype': info.user_has_perm("edit-payment-methods"),
        'may_manage_paytypes': may_manage_paytypes,
    })


class PayTypeForm(forms.Form):
    description = forms.CharField(
        max_length=10,
        help_text="Shown in menus, on receipts, etc.")
    driver_name = forms.CharField(
        required=False,
        help_text="Name of driver module to use")
    mode = forms.ChoiceField(choices=PayType.modes.items())
    config = forms.CharField(widget=forms.TextInput, required=False)
    payments_account = forms.CharField(
        required=False,
        help_text="Name of account to receive payments in accounting system")
    fees_account = forms.CharField(
        required=False,
        help_text="Name of account to receive fees in accounting system")
    payment_date_policy = forms.CharField(
        help_text="Name of date policy function to use for payments "
        "to the payment account in the accounting system")

    def clean(self):
        cd = super().clean()
        if cd['mode'] != 'disabled' and not cd['driver_name']:
            self.add_error(
                'mode', "Driver name must be specified to activate "
                "a payment method")


@tillweb_view
def paytype(request, info, paytype):
    pt = td.s.query(PayType).get(paytype)
    if not pt:
        raise Http404

    may_edit = info.user_has_perm("edit-payment-methods")

    initial = {
        'description': pt.description,
        'driver_name': pt.driver_name,
        'mode': pt.mode,
        'config': pt.config,
        'payments_account': pt.payments_account,
        'fees_account': pt.fees_account,
        'payment_date_policy': pt.payment_date_policy,
    }

    # Even though the tables on the page are loaded by DataTables now,
    # we have to check whether any payments or totals exist to disable
    # the "Delete" button where necessary.
    recent_payments = td.s.query(Payment)\
                          .filter(Payment.paytype == pt)\
                          .limit(1)\
                          .all()
    recent_totals = td.s.query(SessionTotal)\
                        .filter(SessionTotal.paytype == pt)\
                        .limit(1)\
                        .all()

    if may_edit and request.method == "POST":
        if 'submit_update' in request.POST:
            form = PayTypeForm(request.POST, initial=initial)
            if form.is_valid():
                cd = form.cleaned_data
                pt.description = cd['description']
                pt.driver_name = cd['driver_name']
                pt.mode = cd['mode']
                pt.config = cd['config']
                pt.payments_account = cd['payments_account']
                pt.fees_account = cd['fees_account']
                pt.payment_date_policy = cd['payment_date_policy']
                user.log(f"Updated payment method '{pt}'")
                td.s.commit()
                messages.info(request, f"Updated payment method '{pt}'")
                return HttpResponseRedirect(info.reverse("tillweb-paytypes"))
        elif 'submit_delete' in request.POST:
            if recent_payments or recent_totals:
                messages.error(request, "Cannot delete a payment method "
                               "that has been used")
                return HttpResponseRedirect(pt.get_absolute_url())
            user.log(f"Deleted unused payment method '{pt}'")
            messages.info(request, f"Deleted payment method '{pt}'")
            td.s.delete(pt)
            td.s.commit()
            return HttpResponseRedirect(info.reverse("tillweb-paytypes"))
    else:
        form = PayTypeForm(initial=initial)

    return ('paytype.html', {
        'paytype': pt,
        'form': form,
        'tillobject': pt,
        'recent_payments': recent_payments,
        'recent_totals': recent_totals,
        'may_edit': may_edit,
    })


class NewPayTypeForm(forms.Form):
    code = forms.CharField(
        max_length=8,
        help_text="Internal name for new payment method; must be unique")
    description = forms.CharField(
        max_length=10,
        help_text="Description of new payment method, used in menus and "
        "printed on receipts, etc.")


@tillweb_view
def create_paytype(request, info):
    if not info.user_has_perm("edit-payment-methods"):
        return HttpResponseForbidden("You cannot create new payment methods")

    if request.method == "POST":
        form = NewPayTypeForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            pt = PayType(paytype=cd['code'], description=cd['description'],
                         order=10000000)
            try:
                td.s.add(pt)
                user.log(f"Created payment method '{pt}' (code '{pt.paytype}')")
                td.s.commit()
                return HttpResponseRedirect(pt.get_absolute_url())
            except sqlalchemy.exc.IntegrityError:
                td.s.rollback()
                form.add_error(
                    "code", "There is another payment method with this code")
    else:
        form = NewPayTypeForm()

    return ('new-paytype.html', {
        'nav': [("Payment methods", info.reverse("tillweb-paytypes")),
                ("New", info.reverse("tillweb-create-paytype"))],
        'form': form,
    })


@tillweb_view
def supplierlist(request, info):
    sl = td.s.query(Supplier)\
             .order_by(Supplier.name)\
             .all()
    may_edit = info.user_has_perm("edit-supplier")
    return ('suppliers.html', {
        'nav': [("Suppliers", info.reverse("tillweb-suppliers"))],
        'suppliers': sl,
        'may_create_supplier': may_edit,
    })


class SupplierForm(forms.Form):
    name = forms.CharField(max_length=60)
    telephone = forms.CharField(max_length=20, required=False)
    email = forms.EmailField(max_length=60, required=False)
    web = forms.URLField(required=False)


@tillweb_view
def supplier(request, info, supplierid):
    s = td.s.query(Supplier).get(supplierid)
    if not s:
        raise Http404

    deliveries = td.s.query(Delivery)\
                     .order_by(desc(Delivery.id))\
                     .filter(Delivery.supplier == s)

    form = None
    can_delete = False
    if info.user_has_perm("edit-supplier"):
        initial = {
            'name': s.name,
            'telephone': s.tel,
            'email': s.email,
            'web': s.web,
        }
        if deliveries.count() == 0:
            can_delete = True
        if request.method == "POST":
            if can_delete and 'submit_delete' in request.POST:
                messages.success(request, f"Supplier '{s.name}' deleted.")
                user.log(f"Deleted supplier {s.logref}")
                td.s.delete(s)
                td.s.commit()
                return HttpResponseRedirect(info.reverse("tillweb-suppliers"))
            form = SupplierForm(request.POST, initial=initial)
            if form.is_valid():
                cd = form.cleaned_data
                s.name = cd['name']
                s.tel = cd['telephone']
                s.email = cd['email']
                s.web = cd['web']
                try:
                    td.s.commit()
                    messages.success(request, f"Supplier '{s.name}' updated.")
                    return HttpResponseRedirect(s.get_absolute_url())
                except sqlalchemy.exc.IntegrityError:
                    td.s.rollback()
                    form.add_error(
                        "name", "There is another supplier with this name")
                    messages.error(
                        request, "Could not update supplier: there is "
                        "another supplier with this name")
        else:
            form = SupplierForm(initial=initial)

    pager = Pager(request, deliveries)
    return ('supplier.html', {
        'tillobject': s,
        'supplier': s,
        'form': form,
        'pager': pager,
        'can_delete': can_delete,
    })


@tillweb_view
def create_supplier(request, info):
    if not info.user_has_perm("edit-supplier"):
        return HttpResponseForbidden(
            "You don't have permission to create new suppliers")

    if request.method == "POST":
        form = SupplierForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            s = Supplier(
                name=cd['name'],
                tel=cd['telephone'],
                email=cd['email'],
                web=cd['web'])
            td.s.add(s)
            try:
                td.s.flush()
                user.log(f"Created supplier {s.logref}")
                td.s.commit()
                messages.success(request, f"Supplier '{s.name}' created.")
                return HttpResponseRedirect(s.get_absolute_url())
            except sqlalchemy.exc.IntegrityError:
                td.s.rollback()
                form.add_error(
                    "name", "There is another supplier with this name")
                messages.error(
                    request, "Could not add supplier: there is "
                    "another supplier with this name")
    else:
        form = SupplierForm()

    return ('new-supplier.html', {
        'nav': [("Suppliers", info.reverse("tillweb-suppliers")),
                ("New", info.reverse("tillweb-create-supplier"))],
        'form': form,
    })


@tillweb_view
def deliverylist(request, info):
    dl = td.s.query(Delivery)\
             .order_by(desc(Delivery.id))\
             .options(joinedload('supplier'))

    pager = Pager(request, dl)

    may_create_delivery = info.user_has_perm("deliveries")

    return ('deliveries.html', {
        'nav': [("Deliveries", info.reverse("tillweb-deliveries"))],
        'pager': pager,
        'may_create_delivery': may_create_delivery,
    })


class DeliveryForm(forms.Form):
    supplier = SQLAModelChoiceField(
        Supplier,
        query_filter=lambda x: x.order_by(Supplier.name),
        widget=Select2)
    docnumber = forms.CharField(
        label="Document number", required=False, max_length=40)
    date = forms.DateField(widget=DateInput)


@tillweb_view
def create_delivery(request, info):
    if not info.user_has_perm("deliveries"):
        return HttpResponseForbidden(
            "You don't have permission to create new deliveries")

    if request.method == "POST":
        form = DeliveryForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            d = Delivery(
                supplier=cd['supplier'],
                docnumber=cd['docnumber'],
                date=cd['date'])
            td.s.add(d)
            td.s.commit()
            messages.success(request, "Draft delivery created.")
            return HttpResponseRedirect(d.get_absolute_url())
    else:
        form = DeliveryForm()

    return ('new-delivery.html', {
        'nav': [("Deliveries", info.reverse("tillweb-deliveries")),
                ("New", info.reverse("tillweb-create-delivery"))],
        'form': form,
    })


class EditDeliveryForm(DeliveryForm):
    def __init__(self, info, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set the URL for the stocktype widget ajax
        self.fields['stocktype'].widget.ajax = {
            'url': info.reverse("tillweb-stocktype-search-stockunits-json"),
            'dataType': 'json',
            'delay': 250,
        }
        self.header_fields = [
            self['supplier'], self['docnumber'], self['date'],
        ]

    stocktype = SQLAModelChoiceField(
        StockType,
        required=False,
        empty_label='Choose a stock type',
        label_function=stocktype_widget_label,
        query_filter=lambda x: x.order_by(StockType.manufacturer,
                                          StockType.name),
        widget=Select2Ajax(min_input_length=2))
    itemsize = SQLAModelChoiceField(StockUnit, required=False,
                                    empty_label='Choose an item size')
    quantity = forms.IntegerField(min_value=1, required=False, initial=1)
    costprice = forms.DecimalField(
        required=False, min_value=zero,
        max_digits=money_max_digits, decimal_places=money_decimal_places)
    saleprice = forms.DecimalField(
        required=False, min_value=zero,
        max_digits=money_max_digits, decimal_places=money_decimal_places)
    bestbefore = forms.DateField(required=False, widget=DateInput)

    def clean(self):
        cd = super().clean()
        if cd['stocktype'] or cd['itemsize'] or cd['quantity'] \
           or cd['costprice'] or cd['saleprice'] or cd['bestbefore']:
            msg = 'Required when adding stock to a delivery'
            if not cd.get('stocktype'):
                self.add_error('stocktype', msg)
            if not cd.get('itemsize'):
                self.add_error('itemsize', msg)
            if not cd.get('quantity'):
                self.add_error('quantity', msg)
            if cd.get('itemsize') and cd.get('stocktype'):
                if cd['itemsize'].unit != cd['stocktype'].unit:
                    self.add_error('itemsize', 'Item size is not valid for '
                                   'the selected stock type')


@tillweb_view
def delivery(request, info, deliveryid):
    d = td.s.query(Delivery)\
            .options(joinedload('items').joinedload('stocktype')
                     .joinedload('unit'),
                     joinedload('items').joinedload('stockline'),
                     undefer_qtys('items'))\
            .get(deliveryid)
    if not d:
        raise Http404

    may_edit = not d.checked and info.user_has_perm('deliveries')
    form = None

    total = sum(i.costprice or zero for i in d.items)

    if may_edit:
        initial = {
            'supplier': d.supplier,
            'docnumber': d.docnumber,
            'date': d.date,
        }
        if request.method == 'POST':
            if 'submit_delete' in request.POST:
                if d.items:
                    messages.error(
                        request, "There are items in this delivery.  The "
                        "delivery can't be deleted until they are removed.")
                    return HttpResponseRedirect(d.get_absolute_url())
                messages.success(request, "Delivery deleted.")
                td.s.delete(d)
                td.s.commit()
                return HttpResponseRedirect(info.reverse("tillweb-deliveries"))
            for s in d.items:
                if f'del{s.id}' in request.POST:
                    td.s.delete(s)
                    td.s.commit()
                    return HttpResponseRedirect(d.get_absolute_url())
            form = EditDeliveryForm(info, request.POST, initial=initial)
            if form.is_valid():
                cd = form.cleaned_data
                d.supplier = cd['supplier']
                d.docnumber = cd['docnumber']
                d.date = cd['date']
                if cd['stocktype']:
                    stockunit = cd['itemsize']
                    stocktype = cd['stocktype']
                    if cd['saleprice'] \
                       and cd['saleprice'] != stocktype.saleprice:
                        user.log(
                            f"Changed sale price of {stocktype.logref} from "
                            f"{info.money}{stocktype.saleprice} to "
                            f"{info.money}{cd['saleprice']} while working "
                            f"on delivery {d.logref}")
                        stocktype.saleprice = cd['saleprice']
                    qty = cd['quantity']
                    d.add_items(stocktype, stockunit, qty, cd['costprice'],
                                cd['bestbefore'])
                td.s.commit()
                return HttpResponseRedirect(d.get_absolute_url())
        else:
            form = EditDeliveryForm(info, initial=initial)

    return ('edit-delivery.html' if may_edit else 'delivery.html', {
        'tillobject': d,
        'delivery': d,
        'may_edit': may_edit,
        'form': form,
        'total': total,
    })


class StockTypeSearchForm(forms.Form):
    manufacturer = forms.CharField(required=False)
    name = forms.CharField(required=False)
    department = SQLAModelChoiceField(
        Department,
        query_filter=lambda q: q.order_by(Department.id),
        required=False)

    def is_filled_in(self):
        cd = self.cleaned_data
        return cd['manufacturer'] or cd['name'] or cd['department']

    def filter(self, q):
        cd = self.cleaned_data
        if cd['manufacturer']:
            q = q.filter(StockType.manufacturer.ilike(
                "%{}%".format(cd['manufacturer'])))
        if cd['name']:
            q = q.filter(StockType.name.ilike(
                "%{}%".format(cd['name'])))
        if cd['department']:
            q = q.filter(StockType.department == cd['department'])
        return q


@tillweb_view
def stocktypesearch(request, info):
    form = StockTypeSearchForm(request.GET)
    result = []
    if form.is_valid() and form.is_filled_in():
        q = form.filter(td.s.query(StockType))
        result = q.order_by(StockType.dept_id, StockType.manufacturer,
                            StockType.name)\
                  .all()

    may_alter = info.user_has_perm("alter-stocktype")

    may_stocktake = info.user_has_perm("stocktake")

    candidate_stocktakes = []
    if may_stocktake and result:
        # Find candidate stocktakes to add to
        candidate_stocktakes = td.s.query(StockTake)\
                                   .filter(StockTake.start_time == None)\
                                   .order_by(desc(StockTake.id))\
                                   .all()
        if request.method == 'POST':
            for c in candidate_stocktakes:
                if f'submit_add_to_{c.id}' in request.POST:
                    # synchronize_session=False means that the session
                    # will be out of sync after the update, but this
                    # doesn't matter because we're expiring everything
                    # on commit immediately afterwards.
                    q.filter(StockType.stocktake == None).update(
                        {StockType.stocktake_id: c.id},
                        synchronize_session=False)
                    td.s.commit()
                    return HttpResponseRedirect(c.get_absolute_url())

    return ('stocktypesearch.html', {
        'nav': [("Stock types", info.reverse("tillweb-stocktype-search"))],
        'form': form,
        'stocktypes': result,
        'may_alter': may_alter,
        'may_stocktake': may_stocktake,
        'candidate_stocktakes': candidate_stocktakes,
    })


class ValidateStockTypeABV:
    """Mixin class to validate abv of a stock type
    """
    def clean(self):
        cd = super().clean()
        minabv = cd['department'].minabv
        maxabv = cd['department'].maxabv
        if minabv is not None:
            if cd['abv'] is None:
                self.add_error(
                    'abv', "ABV must be specified, even if it is zero")
            elif cd['abv'] < minabv:
                self.add_error(
                    'abv', f"ABV must be at least {minabv}%")
        if maxabv is not None:
            if cd['abv'] is not None and cd['abv'] > maxabv:
                self.add_error(
                    'abv', f"ABV can be {maxabv}% at most")
        return cd


class NewStockTypeForm(ValidateStockTypeABV, forms.Form):
    department = SQLAModelChoiceField(
        Department,
        query_filter=lambda q: q.order_by(Department.id),
        required=True)
    manufacturer = forms.CharField(max_length=30, widget=forms.TextInput(
        attrs={'list': 'manufacturers', 'autocomplete': 'off'}))
    name = forms.CharField(max_length=30, widget=forms.TextInput(
        attrs={'autocomplete': 'off'}))
    abv = forms.DecimalField(
        label="ABV",
        required=False,
        decimal_places=abv_decimal_places,
        min_value=min_abv_value,
        max_value=max_abv_value)
    unit = SQLAModelChoiceField(
        Unit,
        query_filter=lambda x: x.order_by(Unit.name),
        label_function=lambda u: f"{u.description} (base unit: {u.name})")
    saleprice = forms.DecimalField(
        label="Sale price inc. VAT",
        required=False, decimal_places=money_decimal_places,
        min_value=zero, max_digits=money_max_digits)


@tillweb_view
def create_stocktype(request, info):
    if not info.user_has_perm("alter-stocktype"):
        return HttpResponseForbidden(
            "You don't have permission to create new stock types")

    manufacturers = [x[0].strip() for x in
                     td.s.query(distinct(StockType.manufacturer))
                     .order_by(StockType.manufacturer)
                     .all()]

    if request.method == 'POST':
        form = NewStockTypeForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            s = StockType(
                department=cd['department'],
                manufacturer=cd['manufacturer'],
                name=cd['name'],
                abv=cd['abv'],
                unit=cd['unit'],
                saleprice=cd['saleprice'],
            )
            td.s.add(s)
            td.s.flush()
            user.log(f"Created stock type {s.logref}")
            td.s.commit()
            messages.success(request, "New stock type created")
            return HttpResponseRedirect(s.get_absolute_url())
    else:
        form = NewStockTypeForm()

    return ('new-stocktype.html', {
        'nav': [("Stock types", info.reverse("tillweb-stocktype-search")),
                ("New", info.reverse("tillweb-create-stocktype"))],
        'form': form,
        'manufacturers': manufacturers,
    })


def _stocktype_to_dict(x, include_stockunits):
    return {'id': str(x.id), 'text': stocktype_widget_label(x),
            'saleprice': x.saleprice,
            'stockunits': [{'id': str(su.id), 'text': str(su.name)}
                           for su in x.unit.stockunits]
            if include_stockunits else []}


@tillweb_view
def stocktype_search_json(request, info, include_stockunits=False):
    if 'q' not in request.GET:
        return JsonResponse({'results': []})
    words = request.GET['q'].split()
    if not words:
        return JsonResponse({'results': []})
    q = td.s.query(StockType)\
            .order_by(StockType.dept_id, StockType.manufacturer,
                      StockType.name)
    if len(words) == 1:
        q = q.filter((StockType.manufacturer.ilike(f"%{words[0]}%"))
                     | (StockType.name.ilike(f"%{words[0]}%")))
    else:
        q = q.filter(StockType.manufacturer.ilike(f"%{words[0]}%"))\
             .filter(StockType.name.ilike(f"%{words[1]}%"))
    if include_stockunits:
        q = q.options(joinedload('unit').joinedload('stockunits'))
    results = q.all()
    return JsonResponse(
        {'results': [_stocktype_to_dict(x, include_stockunits)
                     for x in results]})


@tillweb_view
def stocktype_info_json(request, info):
    if 'id' not in request.GET:
        raise Http404
    try:
        id = int(request.GET['id'])
    except Exception:
        raise Http404
    st = td.s.query(StockType)\
             .options(joinedload('unit').joinedload('stockunits'))\
             .get(id)
    if not st:
        raise Http404
    return JsonResponse(_stocktype_to_dict(st, True))


class EditStockTypeForm(ValidateStockTypeABV, forms.Form):
    manufacturer = forms.CharField(max_length=30)
    name = forms.CharField(max_length=30)
    abv = forms.DecimalField(
        label="ABV",
        required=False,
        decimal_places=abv_decimal_places,
        min_value=min_abv_value,
        max_value=max_abv_value)
    department = SQLAModelChoiceField(
        Department,
        query_filter=lambda q: q.order_by(Department.id),
        required=True)


class RepriceStockTypeForm(forms.Form):
    saleprice = forms.DecimalField(
        label="New sale price inc. VAT",
        required=False, decimal_places=money_decimal_places,
        min_value=zero, max_digits=money_max_digits)


@tillweb_view
def stocktype(request, info, stocktype_id):
    s = td.s.query(StockType)\
            .get(stocktype_id)
    if not s:
        raise Http404
    may_alter = info.user_has_perm("alter-stocktype")
    may_reprice = info.user_has_perm("reprice-stock")

    alter_form = None
    reprice_form = None

    if may_alter:
        if request.method == 'POST' and 'submit_alter' in request.POST:
            alter_form = EditStockTypeForm(request.POST)
            if alter_form.is_valid():
                cd = alter_form.cleaned_data
                try:
                    s.manufacturer = cd['manufacturer']
                    s.name = cd['name']
                    s.abv = cd['abv']
                    s.department = cd['department']
                    user.log(f"Updated stock type {s.logref}")
                    td.s.commit()
                    messages.success(request, "Stock type updated")
                    return HttpResponseRedirect(s.get_absolute_url())
                except sqlalchemy.exc.IntegrityError:
                    td.s.rollback()
                    messages.error(
                        request, "Could not update this stock type: there is "
                        "another stock type that's an exact match for the new "
                        "details.")

        else:
            alter_form = EditStockTypeForm(initial={
                'manufacturer': s.manufacturer.strip(),
                'name': s.name.strip(),
                'abv': s.abv,
                'department': s.department,
            })

    if may_reprice:
        if request.method == 'POST' and 'submit_reprice' in request.POST:
            reprice_form = RepriceStockTypeForm(request.POST)
            if reprice_form.is_valid():
                new_price = reprice_form.cleaned_data['saleprice']
                if new_price != s.saleprice:
                    user.log(
                        f"Changed sale price of {s.logref} from "
                        f"{info.money}{s.saleprice} to {info.money}{new_price}")
                    s.saleprice = new_price
                    s.saleprice_changed = datetime.datetime.now()
                    td.s.commit()
                    messages.success(request, "Sale price changed")
                return HttpResponseRedirect(s.get_absolute_url())
        else:
            reprice_form = RepriceStockTypeForm(initial={
                'saleprice': s.saleprice,
            })

    include_finished = request.GET.get("show_finished", "off") == "on"
    items = td.s.query(StockItem)\
                .filter(StockItem.stocktype == s)\
                .options(undefer_group('qtys'),
                         joinedload('delivery'))\
                .order_by(desc(StockItem.id))
    stocklines = td.s.query(StockLine)\
                     .filter(StockLine.stocktype == s)\
                     .filter(StockLine.linetype != "regular")
    may_delete = may_alter and items.count() == 0 and stocklines.count() == 0

    if may_delete and request.method == 'POST' \
       and 'submit_delete' in request.POST:
        td.s.delete(s)
        td.s.commit()
        messages.success(request, "Stock type deleted")
        return HttpResponseRedirect(info.reverse("tillweb-stocktype-search"))

    if not include_finished:
        items = items.filter(StockItem.finished == None)
    items = items.all()
    return ('stocktype.html', {
        'tillobject': s,
        'stocktype': s,
        'alter_form': alter_form,
        'reprice_form': reprice_form,
        'may_delete': may_delete,
        'items': items,
        'include_finished': include_finished,
    })


class StockSearchForm(StockTypeSearchForm):
    include_finished = forms.BooleanField(
        required=False, label="Include finished items")


@tillweb_view
def stocksearch(request, info):
    form = StockSearchForm(request.GET)
    pager = None
    if form.is_valid() and form.is_filled_in():
        q = td.s.query(StockItem)\
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


class StockAnnotateForm(forms.Form):
    annotation_type = StringIDChoiceField(
        AnnotationType, 'id',
        query_filter=lambda x: x.order_by(AnnotationType.description)
        .filter(~(AnnotationType.id.in_(["start", "stop"]))),
        empty_label="Choose a type of annotation"
    )
    annotation = forms.CharField()


class StockWasteForm(forms.Form):
    waste_type = StringIDChoiceField(
        RemoveCode, 'id',
        query_filter=lambda x: x.order_by(RemoveCode.reason)
        .filter(RemoveCode.id != 'sold'),
        empty_label="Choose the type of waste to record"
    )
    amount = forms.DecimalField(
        max_digits=qty_max_digits, decimal_places=qty_decimal_places)


class EditStockForm(forms.Form):
    def __init__(self, info, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set the URL for the stocktype widget ajax
        self.fields['stocktype'].widget.ajax = {
            'url': info.reverse("tillweb-stocktype-search-stockunits-json"),
            'dataType': 'json',
            'delay': 250,
        }

    stocktype = SQLAModelChoiceField(
        StockType,
        label="Stock type",
        label_function=stocktype_widget_label,
        query_filter=lambda x: x.order_by(StockType.manufacturer,
                                          StockType.name),
        widget=Select2Ajax(min_input_length=2))
    description = forms.CharField()
    size = forms.DecimalField(
        min_value=min_quantity, max_digits=qty_max_digits,
        decimal_places=qty_decimal_places, initial=1)
    costprice = forms.DecimalField(
        label="Cost price",
        required=False, min_value=zero,
        max_digits=money_max_digits, decimal_places=money_decimal_places)
    bestbefore = forms.DateField(label="Best before", required=False,
                                 widget=DateInput)


@tillweb_view
def stock(request, info, stockid):
    s = td.s.query(StockItem)\
            .options(undefer('checked'),
                     joinedload('stocktype').joinedload('department'),
                     joinedload('stocktype').joinedload('stockline_log')
                     .joinedload('stockline'),
                     joinedload('stocktype').joinedload('unit'),
                     joinedload('delivery').joinedload('supplier'),
                     joinedload('stocktake'),
                     subqueryload('annotations').joinedload('type'),
                     subqueryload('annotations').joinedload('user'),
                     subqueryload('out').joinedload('transline')
                     .joinedload('transaction'),
                     subqueryload('out').joinedload('removecode'),
                     subqueryload('out').joinedload('stocktake'),
                     subqueryload('snapshots').joinedload('adjustments')
                     .joinedload('removecode'),
                     subqueryload('snapshots').undefer('newqty'),
                     subqueryload('snapshots').joinedload('stocktake'),
                     subqueryload('logs').joinedload('user'),
                     undefer_group('qtys'))\
            .get(stockid)
    if not s:
        raise Http404

    may_edit = not s.delivery.checked and info.user_has_perm("deliveries")
    may_annotate = s.checked and info.user_has_perm("annotate")
    may_record_waste = s.checked and info.user_has_perm("record-waste")

    sform = None
    aform = None
    wform = None

    if may_annotate:
        if request.method == 'POST' and 'submit_annotate' in request.POST:
            aform = StockAnnotateForm(request.POST)
            if aform.is_valid():
                cd = aform.cleaned_data
                td.s.add(StockAnnotation(
                    stockitem=s, type=cd['annotation_type'],
                    text=cd['annotation'], user=info.user))
                td.s.commit()
                messages.success(request, "Annotation added")
                return HttpResponseRedirect(s.get_absolute_url())
        else:
            aform = StockAnnotateForm()

    if may_record_waste:
        if request.method == 'POST' and 'submit_waste' in request.POST:
            wform = StockWasteForm(request.POST)
            if wform.is_valid():
                cd = wform.cleaned_data
                td.s.add(StockOut(
                    stockitem=s, removecode=cd['waste_type'],
                    qty=cd['amount']))
                user.log(f"Recorded {cd['amount']} {s.stocktype.unit.name}s "
                         f"{cd['waste_type']} against stock item {s.logref}.")
                td.s.commit()
                messages.success(request, "Waste recorded")
                return HttpResponseRedirect(s.get_absolute_url())
        else:
            wform = StockWasteForm()

    if may_edit:
        initial = {
            'stocktype': s.stocktype,
            'description': s.description,
            'size': s.size,
            'costprice': s.costprice,
            'bestbefore': s.bestbefore,
        }
        if request.method == 'POST' and 'submit_update' in request.POST:
            sform = EditStockForm(info, request.POST, initial=initial)
            if sform.is_valid():
                cd = sform.cleaned_data
                s.stocktype = cd['stocktype']
                s.description = cd['description']
                s.size = cd['size']
                s.costprice = cd['costprice']
                s.bestbefore = cd['bestbefore']
                td.s.commit()
                messages.success(request, f"Stock item {s.id} updated")
                return HttpResponseRedirect(s.delivery.get_absolute_url())
        else:
            sform = EditStockForm(info, initial=initial)
        if request.method == 'POST' and 'submit_delete' in request.POST:
            r = s.delivery.get_absolute_url()
            td.s.delete(s)
            td.s.commit()
            messages.success(request, f"Stock item {s.id} deleted")
            return HttpResponseRedirect(r)

    return ('stockitem.html' if s.delivery.checked else 'edit-stockitem.html', {
        'tillobject': s,
        'stock': s,
        'aform': aform,
        'sform': sform,
        'wform': wform,
    })


@tillweb_view
def units(request, info):
    u = td.s.query(Unit).order_by(Unit.description).all()
    may_edit = info.user_has_perm("edit-unit")
    return ('units.html', {
        'units': u,
        'nav': [("Units", info.reverse("tillweb-units"))],
        'may_create_unit': may_edit,
    })


class UnitForm(forms.Form):
    description = forms.CharField()
    base_unit = forms.CharField()
    base_units_per_sale_unit = forms.DecimalField(
        min_value=min_quantity, max_digits=qty_max_digits,
        decimal_places=qty_decimal_places, initial=1)
    sale_unit_name = forms.CharField()
    sale_unit_name_plural = forms.CharField()
    base_units_per_stock_unit = forms.DecimalField(
        min_value=min_quantity, max_digits=qty_max_digits,
        decimal_places=qty_decimal_places, initial=1)
    stock_unit_name = forms.CharField()
    stock_unit_name_plural = forms.CharField()
    stock_take_method = forms.ChoiceField(
        choices=[('items', 'Separate items'),
                 ('stocktype', 'Total quantity in stock')],
        required=True, initial='items')


@tillweb_view
def unit(request, info, unit_id):
    u = td.s.query(Unit).get(unit_id)
    if not u:
        raise Http404

    form = None
    can_delete = False
    if info.user_has_perm("edit-unit"):
        initial = {
            'description': u.description,
            'base_unit': u.name,
            'base_units_per_sale_unit': u.base_units_per_sale_unit,
            'sale_unit_name': u.sale_unit_name,
            'sale_unit_name_plural': u.sale_unit_name_plural,
            'base_units_per_stock_unit': u.base_units_per_stock_unit,
            'stock_unit_name': u.stock_unit_name,
            'stock_unit_name_plural': u.stock_unit_name_plural,
            'stock_take_method': 'items' if u.stocktake_by_items
            else 'stocktype'
        }
        if len(u.stocktypes) == 0 and len(u.stockunits) == 0:
            can_delete = True
        if request.method == "POST":
            if can_delete and 'submit_delete' in request.POST:
                user.log(f"Deleted unit {u.logref}")
                messages.success(request, f"Unit '{u.description}' deleted.")
                td.s.delete(u)
                td.s.commit()
                return HttpResponseRedirect(info.reverse("tillweb-units"))
            form = UnitForm(request.POST, initial=initial)
            if form.is_valid():
                cd = form.cleaned_data
                u.description = cd['description']
                u.name = cd['base_unit']
                u.base_units_per_sale_unit = cd['base_units_per_sale_unit']
                u.sale_unit_name = cd['sale_unit_name']
                u.sale_unit_name_plural = cd['sale_unit_name_plural']
                u.base_units_per_stock_unit = cd['base_units_per_stock_unit']
                u.stock_unit_name = cd['stock_unit_name']
                u.stock_unit_name_plural = cd['stock_unit_name_plural']
                u.stocktake_by_items = cd['stock_take_method'] == 'items'
                user.log(f"Updated unit {u.logref}")
                td.s.commit()
                messages.success(request, f"Unit '{u.description}' updated.")
                return HttpResponseRedirect(info.reverse("tillweb-units"))
        else:
            form = UnitForm(initial=initial)

    return ('unit.html', {
        'tillobject': u,
        'unit': u,
        'form': form,
        'can_delete': can_delete,
    })


@tillweb_view
def create_unit(request, info):
    if not info.user_has_perm("edit-unit"):
        return HttpResponseForbidden(
            "You don't have permission to create new units")

    if request.method == "POST":
        form = UnitForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            u = Unit(
                description=cd['description'],
                name=cd['base_unit'],
                base_units_per_sale_unit=cd['base_units_per_sale_unit'],
                sale_unit_name=cd['sale_unit_name'],
                sale_unit_name_plural=cd['sale_unit_name_plural'],
                base_units_per_stock_unit=cd['base_units_per_stock_unit'],
                stock_unit_name=cd['stock_unit_name'],
                stock_unit_name_plural=cd['stock_unit_name_plural'],
                stocktake_by_items=cd['stock_take_method'] == 'items')
            td.s.add(u)
            td.s.flush()
            user.log(f"Created unit {u.logref}")
            td.s.commit()
            messages.success(request, f"Unit '{u.description}' created.")
            return HttpResponseRedirect(info.reverse("tillweb-units"))
    else:
        form = UnitForm()

    return ('new-unit.html', {
        'nav': [("Units", info.reverse("tillweb-units")),
                ("New", info.reverse("tillweb-create-unit"))],
        'form': form,
    })


@tillweb_view
def stockunits(request, info):
    su = td.s.query(StockUnit)\
             .join(Unit)\
             .order_by(Unit.description, StockUnit.size)\
             .all()
    may_edit = info.user_has_perm("edit-stockunit")
    return ('stockunits.html', {
        'stockunits': su,
        'nav': [("Item sizes", info.reverse("tillweb-stockunits"))],
        'may_create_stockunit': may_edit,
    })


class StockUnitForm(forms.Form):
    description = forms.CharField()
    unit = SQLAModelChoiceField(
        Unit,
        query_filter=lambda x: x.order_by(Unit.name),
        label_function=lambda u: f"{u.description} (base unit: {u.name})")
    size = forms.DecimalField(
        label="Size in base units",
        min_value=min_quantity, max_digits=qty_max_digits,
        decimal_places=qty_decimal_places)
    merge = forms.BooleanField(required=False)


@tillweb_view
def stockunit(request, info, stockunit_id):
    su = td.s.query(StockUnit).get(stockunit_id)
    if not su:
        raise Http404

    form = None
    if info.user_has_perm("edit-stockunit"):
        initial = {
            'description': su.name,
            'unit': su.unit,
            'size': su.size,
            'merge': su.merge,
        }
        if request.method == "POST":
            if 'submit_delete' in request.POST:
                messages.success(request, f"Item size '{su.name}' deleted.")
                td.s.delete(su)
                td.s.commit()
                return HttpResponseRedirect(info.reverse("tillweb-stockunits"))
            form = StockUnitForm(request.POST, initial=initial)
            if form.is_valid():
                cd = form.cleaned_data
                su.name = cd['description']
                su.unit = cd['unit']
                su.size = cd['size']
                su.merge = cd['merge']
                td.s.commit()
                messages.success(request, f"Item size '{su.name}' updated.")
                return HttpResponseRedirect(su.get_absolute_url())
        else:
            form = StockUnitForm(initial=initial)

    return ('stockunit.html', {
        'tillobject': su,
        'stockunit': su,
        'form': form,
    })


@tillweb_view
def create_stockunit(request, info):
    if not info.user_has_perm("edit-stockunit"):
        return HttpResponseForbidden(
            "You don't have permission to create new item sizes")

    if request.method == "POST":
        form = StockUnitForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            su = StockUnit(
                name=cd['description'],
                unit=cd['unit'],
                size=cd['size'],
                merge=cd['merge'])
            td.s.add(su)
            td.s.commit()
            messages.success(request, f"Item size '{su.name}' created.")
            return HttpResponseRedirect(su.get_absolute_url())
    else:
        form = StockUnitForm()

    return ('new-stockunit.html', {
        'nav': [("Item sizes", info.reverse("tillweb-stockunits")),
                ("New", info.reverse("tillweb-create-stockunit"))],
        'form': form,
    })


@tillweb_view
def stocklinelist(request, info):
    regular = td.s.query(StockLine)\
                  .order_by(StockLine.dept_id, StockLine.name)\
                  .filter(StockLine.linetype == "regular")\
                  .options(joinedload("stockonsale"))\
                  .options(joinedload("stockonsale.stocktype"))\
                  .all()
    display = td.s.query(StockLine)\
                  .filter(StockLine.linetype == "display")\
                  .order_by(StockLine.name)\
                  .options(joinedload("stockonsale"))\
                  .options(undefer("stockonsale.used"))\
                  .all()
    continuous = td.s.query(StockLine)\
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
def stockline(request, info, stocklineid):
    s = td.s.query(StockLine)\
            .options(joinedload('stockonsale').joinedload('stocktype')
                     .joinedload('unit'),
                     joinedload('stockonsale').joinedload('delivery'),
                     undefer_qtys('stockonsale'))\
            .get(stocklineid)
    if not s:
        raise Http404
    if s.linetype == "regular":
        return stockline_regular(request, info, s)
    elif s.linetype == "display":
        return stockline_display(request, info, s)
    elif s.linetype == "continuous":
        return stockline_continuous(request, info, s)

    return ('stockline.html', {
        'tillobject': s,
        'stockline': s,
    })


class RegularStockLineForm(forms.Form):
    def __init__(self, info, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set the URL for the stocktype widget ajax
        self.fields['stocktype'].widget.ajax = {
            'url': info.reverse("tillweb-stocktype-search-stockunits-json"),
            'dataType': 'json',
            'delay': 250,
        }

    name = forms.CharField(max_length=30)
    location = forms.CharField(max_length=20, widget=forms.TextInput(
        attrs={'list': 'locations', 'autocomplete': 'off'}))
    stocktype = SQLAModelChoiceField(
        StockType,
        required=False,
        label="Restrict new stock to this type",
        empty_label="Don't restrict by stock type",
        label_function=stocktype_widget_label,
        query_filter=lambda x: x.order_by(StockType.manufacturer,
                                          StockType.name),
        widget=Select2Ajax(min_input_length=2))
    department = SQLAModelChoiceField(
        Department,
        label="Restrict new stock to this department",
        empty_label="Don't restrict by department",
        query_filter=lambda q: q.order_by(Department.id),
        required=False)
    pullthru = forms.DecimalField(
        label="Pull-through amount",
        max_digits=qty_max_digits, decimal_places=qty_decimal_places,
        required=False)


def stockline_regular(request, info, s):
    form = None
    if info.user_has_perm("alter-stockline"):
        if request.method == 'POST' and 'submit_update' in request.POST:
            form = RegularStockLineForm(info, request.POST)
            if form.is_valid():
                cd = form.cleaned_data
                s.name = cd['name']
                s.location = cd['location']
                s.stocktype = cd['stocktype']
                s.department = cd['department']
                s.pullthru = cd['pullthru']
                try:
                    td.s.commit()
                    messages.success(request, "Stock line updated")
                    return HttpResponseRedirect(s.get_absolute_url())
                except sqlalchemy.exc.IntegrityError:
                    td.s.rollback()
                    form.add_error("name", "Name already in use")
                    messages.error(
                        request, "Could not update stock line: the name "
                        "is already in use by another stock line")
        elif request.method == 'POST' and 'submit_delete' in request.POST:
            td.s.delete(s)
            td.s.commit()
            messages.success(request, "Stock line deleted")
            return HttpResponseRedirect(info.reverse("tillweb-stocklines"))
        else:
            form = RegularStockLineForm(info, initial={
                "name": s.name,
                "location": s.location,
                "stocktype": s.stocktype,
                "department": s.department,
                "pullthru": s.pullthru,
            })

    locations = StockLine.locations(td.s) if form else None

    return ('stockline-regular.html', {
        'tillobject': s,
        'stockline': s,
        'form': form,
        'locations': locations,
    })


class DisplayStockLineForm(forms.Form):
    def __init__(self, info, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set the URL for the stocktype widget ajax
        self.fields['stocktype'].widget.ajax = {
            'url': info.reverse("tillweb-stocktype-search-stockunits-json"),
            'dataType': 'json',
            'delay': 250,
        }

    name = forms.CharField(max_length=30)
    location = forms.CharField(max_length=20, widget=forms.TextInput(
        attrs={'list': 'locations', 'autocomplete': 'off'}))
    stocktype = SQLAModelChoiceField(
        StockType,
        required=True,
        label="Type of stock on sale",
        empty_label="Choose a stock type",
        label_function=stocktype_widget_label,
        query_filter=lambda x: x.order_by(StockType.manufacturer,
                                          StockType.name),
        widget=Select2Ajax(min_input_length=2))
    capacity = forms.IntegerField(
        label="Maximum number of items on display", min_value=1)


def stockline_display(request, info, s):
    form = None
    if info.user_has_perm("alter-stockline"):
        if request.method == 'POST' and 'submit_update' in request.POST:
            form = DisplayStockLineForm(info, request.POST)
            if form.is_valid():
                cd = form.cleaned_data
                s.name = cd['name']
                s.location = cd['location']
                s.stocktype = cd['stocktype']
                s.capacity = cd['capacity']
                try:
                    td.s.commit()
                    for item in list(s.stockonsale):
                        if item.stocktype != s.stocktype:
                            messages.info(request,
                                          f"Item {item.id} was removed "
                                          "because it is the wrong type")
                            item.displayqty = None
                            item.stockline = None
                    td.s.commit()
                    messages.success(request, "Stock line updated")
                    return HttpResponseRedirect(s.get_absolute_url())
                except sqlalchemy.exc.IntegrityError:
                    td.s.rollback()
                    form.add_error("name", "Name already in use")
                    messages.error(
                        request, "Could not update stock line: the name "
                        "is already in use by another stock line")
        elif request.method == 'POST' and 'submit_delete' in request.POST:
            td.s.delete(s)
            td.s.commit()
            messages.success(request, "Stock line deleted")
            return HttpResponseRedirect(info.reverse("tillweb-stocklines"))
        else:
            form = DisplayStockLineForm(info, initial={
                "name": s.name,
                "location": s.location,
                "stocktype": s.stocktype,
                "capacity": s.capacity,
            })

    locations = StockLine.locations(td.s) if form else None

    return ('stockline-display.html', {
        'tillobject': s,
        'stockline': s,
        'form': form,
        'locations': locations,
    })


class ContinuousStockLineForm(forms.Form):
    def __init__(self, info, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set the URL for the stocktype widget ajax
        self.fields['stocktype'].widget.ajax = {
            'url': info.reverse("tillweb-stocktype-search-stockunits-json"),
            'dataType': 'json',
            'delay': 250,
        }

    name = forms.CharField(max_length=30)
    location = forms.CharField(max_length=20, widget=forms.TextInput(
        attrs={'list': 'locations', 'autocomplete': 'off'}))
    stocktype = SQLAModelChoiceField(
        StockType,
        required=True,
        label="Type of stock on sale",
        empty_label="Choose a stock type",
        label_function=stocktype_widget_label,
        query_filter=lambda x: x.order_by(StockType.manufacturer,
                                          StockType.name),
        widget=Select2Ajax(min_input_length=2))


def stockline_continuous(request, info, s):
    form = None
    if info.user_has_perm("alter-stockline"):
        if request.method == 'POST' and 'submit_update' in request.POST:
            form = ContinuousStockLineForm(info, request.POST)
            if form.is_valid():
                cd = form.cleaned_data
                s.name = cd['name']
                s.location = cd['location']
                s.stocktype = cd['stocktype']
                try:
                    td.s.commit()
                    messages.success(request, "Stock line updated")
                    return HttpResponseRedirect(s.get_absolute_url())
                except sqlalchemy.exc.IntegrityError:
                    td.s.rollback()
                    form.add_error("name", "Name already in use")
                    messages.error(
                        request, "Could not update stock line: the name "
                        "is already in use by another stock line")
        elif request.method == 'POST' and 'submit_delete' in request.POST:
            td.s.delete(s)
            td.s.commit()
            messages.success(request, "Stock line deleted")
            return HttpResponseRedirect(info.reverse("tillweb-stocklines"))
        else:
            form = ContinuousStockLineForm(info, initial={
                "name": s.name,
                "location": s.location,
                "stocktype": s.stocktype,
            })

    locations = StockLine.locations(td.s) if form else None

    return ('stockline-continuous.html', {
        'tillobject': s,
        'stockline': s,
        'form': form,
        'locations': locations,
    })


@tillweb_view
def plulist(request, info):
    plus = td.s.query(PriceLookup)\
               .order_by(PriceLookup.dept_id, PriceLookup.description)\
               .all()

    may_create_plu = info.user_has_perm("create-plu")

    return ('plus.html', {
        'nav': [("Price lookups", info.reverse("tillweb-plus"))],
        'plus': plus,
        'may_create_plu': may_create_plu,
    })


class PLUForm(forms.Form):
    description = forms.CharField()
    department = SQLAModelChoiceField(
        Department,
        query_filter=lambda q: q.order_by(Department.id),
        required=True)
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
def plu(request, info, pluid):
    p = td.s.query(PriceLookup).get(pluid)
    if not p:
        raise Http404

    form = None
    if info.user_has_perm("alter-plu"):
        initial = {
            'description': p.description,
            'note': p.note,
            'department': p.department,
            'price': p.price,
            'altprice1': p.altprice1,
            'altprice2': p.altprice2,
            'altprice3': p.altprice3,
        }
        if request.method == "POST":
            if 'submit_delete' in request.POST:
                messages.success(
                    request, f"Price lookup '{p.description}' deleted.")
                td.s.delete(p)
                td.s.commit()
                return HttpResponseRedirect(info.reverse("tillweb-plus"))
            form = PLUForm(request.POST, initial=initial)
            if form.is_valid():
                cd = form.cleaned_data
                p.description = cd['description']
                p.note = cd['note']
                p.department = cd['department']
                p.price = cd['price']
                p.altprice1 = cd['altprice1']
                p.altprice2 = cd['altprice2']
                p.altprice3 = cd['altprice3']
                td.s.commit()
                messages.success(
                    request, "Price lookup '{p.description}' updated.")
                return HttpResponseRedirect(p.get_absolute_url())
        else:
            form = PLUForm(initial=initial)

    return ('plu.html', {
        'tillobject': p,
        'plu': p,
        'form': form,
    })


@tillweb_view
def create_plu(request, info):
    if not info.user_has_perm("create-plu"):
        return HttpResponseForbidden(
            "You don't have permission to create new price lookups")

    if request.method == "POST":
        form = PLUForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            p = PriceLookup(
                description=cd['description'],
                note=cd['note'],
                department=cd['department'],
                price=cd['price'],
                altprice1=cd['altprice1'],
                altprice2=cd['altprice2'],
                altprice3=cd['altprice3'])
            td.s.add(p)
            td.s.commit()
            messages.success(
                request, f"Price lookup '{p.description}' created.")
            return HttpResponseRedirect(p.get_absolute_url())
    else:
        form = PLUForm()

    return ('new-plu.html', {
        'nav': [("Price lookups", info.reverse("tillweb-plus")),
                ("New", info.reverse("tillweb-create-plu"))],
        'form': form,
    })


class BarcodeSearchForm(forms.Form):
    barcode = forms.CharField()


@tillweb_view
def barcodelist(request, info):
    if request.method == 'POST':
        form = BarcodeSearchForm(request.POST)

        if form.is_valid():
            cd = form.cleaned_data
            barcode = td.s.query(Barcode).get(cd['barcode'])
            if barcode:
                return HttpResponseRedirect(barcode.get_absolute_url())
            messages.error(request, f"Barcode {cd['barcode']} is not known")
            return HttpResponseRedirect(info.reverse("tillweb-barcodes"))
    else:
        form = BarcodeSearchForm()

    barcodes = td.s.query(Barcode)\
                   .options(joinedload('stocktype'),
                            joinedload('stockline'),
                            joinedload('plu'))\
                   .order_by(Barcode.id)

    pager = Pager(request, barcodes)

    return ('barcodes.html', {
        'nav': [
            ("Barcodes", info.reverse("tillweb-barcodes")),
        ],
        'form': form,
        'recent': pager.items,
        'pager': pager,
        'nextlink': pager.nextlink(),
        'prevlink': pager.prevlink(),
    })


@tillweb_view
def barcode(request, info, barcode):
    b = td.s.query(Barcode).get(barcode)

    return ('barcode.html', {
        'barcode': b,
        'tillobject': b,
    })


@tillweb_view
def departmentlist(request, info):
    depts = td.s.query(Department)\
                .options(joinedload('vat'))\
                .order_by(Department.id)\
                .all()
    return ('departmentlist.html', {
        'nav': [("Departments", info.reverse("tillweb-departments"))],
        'depts': depts,
        'may_create_department': info.user_has_perm("edit-department"),
    })


class DepartmentForm(forms.Form):
    description = forms.CharField(
        max_length=20, help_text="Used in web interface, printed on "
        "price lists and session total lists")
    vatband = StringIDChoiceField(
        VatBand, 'band',
        label="VAT band", empty_label="Choose a VAT band",
        label_function=lambda x: f"{x.band} ({x.description})",
        help_text="VAT rate and business; see note below")
    notes = forms.CharField(
        widget=forms.Textarea(), required=False,
        help_text="Printed on price lists")
    min_price = forms.DecimalField(
        label="Minimum price", required=False, min_value=zero,
        max_digits=money_max_digits, decimal_places=money_decimal_places,
        help_text="Minimum price per item when price is entered manually")
    max_price = forms.DecimalField(
        label="Maximum price", required=False, min_value=zero,
        max_digits=money_max_digits, decimal_places=money_decimal_places,
        help_text="Maximum price per item when price is entered manually")
    min_abv = forms.DecimalField(
        label="Minimum ABV", required=False, min_value=min_abv_value,
        max_digits=abv_max_digits, decimal_places=abv_decimal_places,
        help_text="Minimum ABV for stock types in this department; if "
        "present, stock types with null ABV are not allowed")
    max_abv = forms.DecimalField(
        label="Maximum ABV", required=False, min_value=min_abv_value,
        max_digits=abv_max_digits, decimal_places=abv_decimal_places,
        help_text="Maximum ABV for stock types in this department")
    sales_account = forms.CharField(
        required=False,
        help_text="Name of sales account in accounting system")
    purchases_account = forms.CharField(
        required=False,
        help_text="Name of purchases account in accounting system")


class DepartmentNumberForm(forms.Form):
    number = forms.IntegerField(
        min_value=1, help_text="Must be unique")

    def clean_number(self):
        n = self.cleaned_data['number']
        d = td.s.query(Department).get(n)
        if d:
            raise ValidationError(f"Department {n} already exists")
        return n


class NewDepartmentForm(DepartmentForm, DepartmentNumberForm):
    pass


@tillweb_view
def create_department(request, info):
    if not info.user_has_perm("edit-department"):
        return HttpResponseForbidden(
            "You don't have permission to create new departments")

    if request.method == 'POST':
        form = NewDepartmentForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            d = Department(id=cd['number'], description=cd['description'],
                           vat=cd['vatband'],
                           notes=cd['notes'] or None,
                           minprice=cd['min_price'],
                           maxprice=cd['max_price'],
                           minabv=cd['min_abv'],
                           maxabv=cd['max_abv'],
                           sales_account=cd['sales_account'],
                           purchases_account=cd['purchases_account'])
            td.s.add(d)
            td.s.flush()
            user.log(f"Created department {d.logref}")
            td.s.commit()
            messages.success(request, f"Department {cd['number']} created")
            return HttpResponseRedirect(info.reverse("tillweb-departments"))
    else:
        form = NewDepartmentForm()

    return ('new-department.html', {
        'nav': [("Departments", info.reverse("tillweb-departments")),
                ("New", info.reverse("tillweb-create-department"))],
        'form': form,
    })


@tillweb_view
def department(request, info, departmentid, as_spreadsheet=False):
    d = td.s.query(Department)\
            .get(departmentid)
    if d is None:
        raise Http404

    may_edit = info.user_has_perm("edit-department")
    form = None

    if may_edit:
        initial = {
            'description': d.description,
            'vatband': d.vat,
            'notes': d.notes,
            'min_price': d.minprice,
            'max_price': d.maxprice,
            'min_abv': d.minabv,
            'max_abv': d.maxabv,
            'sales_account': d.sales_account,
            'purchases_account': d.purchases_account,
        }
        if request.method == 'POST' and 'submit_update' in request.POST:
            form = DepartmentForm(request.POST, initial=initial)
            if form.is_valid():
                if form.has_changed():
                    cd = form.cleaned_data
                    d.description = cd['description']
                    d.vat = cd['vatband']
                    d.notes = cd['notes']
                    d.minprice = cd['min_price']
                    d.maxprice = cd['max_price']
                    d.minabv = cd['min_abv']
                    d.maxabv = cd['max_abv']
                    d.sales_account = cd['sales_account']
                    d.purchases_account = cd['purchases_account']
                    user.log(f"Updated department {d.logref}")
                    td.s.commit()
                    messages.success(request, "Department details updated")
                return HttpResponseRedirect(d.get_absolute_url())
        else:
            form = DepartmentForm(initial=initial)

        # Can we delete this department? There must be no translines,
        # no PLUs, no stocklines, no stocktypes referencing it. Let's
        # consider adding this feature in the future.

    include_finished = request.GET.get("show_finished", "off") == "on"
    items = td.s.query(StockItem)\
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
            items.all(), tillname=info.tillname,
            filename="{}-dept{}-stock.ods".format(
                info.tillname, departmentid))

    pager = Pager(request, items, preserve_query_parameters=["show_finished"])

    return ('department.html', {
        'tillobject': d,
        'department': d,
        'pager': pager,
        'include_finished': include_finished,
        'may_edit': may_edit,
        'form': form,
    })


class StockCheckForm(forms.Form):
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
    department = SQLAModelChoiceField(
        Department,
        query_filter=lambda q: q.order_by(Department.id))


@tillweb_view
def stockcheck(request, info):
    buylist = []
    if request.method == 'POST':
        form = StockCheckForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            ahead = datetime.timedelta(days=cd['weeks_ahead'] * 7)
            behind = datetime.timedelta(days=cd['months_behind'] * 30.4)
            min_sale = cd['minimum_sold']
            dept = cd['department']
            r = td.s.query(StockType, func.sum(StockOut.qty) / behind.days)\
                    .select_from(StockType)\
                    .join(StockItem)\
                    .join(StockOut)\
                    .options(lazyload(StockType.department),
                             lazyload(StockType.unit),
                             undefer(StockType.all_instock))\
                    .filter(StockOut.removecode_id == 'sold')\
                    .filter((func.now() - StockOut.time) < behind)\
                    .filter(StockType.department == dept)\
                    .having(func.sum(StockOut.qty) / behind.days > min_sale)\
                    .group_by(StockType)\
                    .all()
            buylist = sorted(
                ((st, sold / st.unit.base_units_per_stock_unit,
                  st.all_instock / st.unit.base_units_per_stock_unit,
                  (sold * ahead.days - st.all_instock)
                  / st.unit.base_units_per_stock_unit)
                 for st, sold in r),
                key=lambda x: x[3], reverse=True)
    else:
        form = StockCheckForm()
    return ('stockcheck.html', {
        'nav': [
            ("Reports", info.reverse("tillweb-reports")),
            ("Buying list", info.reverse("tillweb-stockcheck"))],
        'form': form,
        'buylist': buylist,
    })


@tillweb_view
def userlist(request, info):
    return ('userlist.html', {
        'nav': [("Users", info.reverse("tillweb-till-users"))],
    })


class EditUserForm(forms.Form):
    fullname = forms.CharField()
    shortname = forms.CharField()
    web_username = forms.CharField(required=False)
    enabled = forms.BooleanField(required=False)
    groups = StringIDMultipleChoiceField(
        Group, 'id',
        query_filter=lambda q: q.order_by(Group.id),
        required=False)


@tillweb_view
def userdetail(request, info, userid):
    u = td.s.query(User).get(userid)
    if not u:
        raise Http404

    form = None
    if (u == info.user or not u.superuser) and info.user_has_perm("edit-user"):
        initial = {
            'fullname': u.fullname,
            'shortname': u.shortname,
            'web_username': u.webuser,
            'enabled': u.enabled,
            'groups': u.groups,
        }
        if request.method == "POST":
            form = EditUserForm(request.POST, initial=initial)
            if form.is_valid():
                cd = form.cleaned_data
                u.fullname = cd['fullname']
                u.shortname = cd['shortname']
                u.webuser = cd['web_username'] if cd['web_username'] else None
                u.enabled = cd['enabled']
                u.groups = cd['groups']
                try:
                    td.s.commit()
                    messages.success(request, "User '{}' updated.".format(
                        u.fullname))
                    return HttpResponseRedirect(u.get_absolute_url())
                except sqlalchemy.exc.IntegrityError:
                    td.s.rollback()
                    form.add_error("web_username", "Username already in use")
                    messages.error(
                        request, "Could not update user: the web username "
                        "is already in use by another till user")
        else:
            form = EditUserForm(initial=initial)

    sales = td.s.query(Transline)\
                .filter(Transline.user == u)\
                .options(joinedload('transaction'),
                         joinedload('stockref').joinedload('stockitem')
                         .joinedload('stocktype').joinedload('unit'))\
                .order_by(desc(Transline.time))[:50]

    payments = td.s.query(Payment)\
                   .filter(Payment.user == u)\
                   .options(joinedload('transaction'),
                            joinedload('paytype'))\
                   .order_by(desc(Payment.time))[:50]

    annotations = td.s.query(StockAnnotation)\
                      .options(joinedload('stockitem').joinedload('stocktype'),
                               joinedload('type'))\
                      .filter(StockAnnotation.user == u)\
                      .order_by(desc(StockAnnotation.time))[:50]

    logs = td.s.query(LogEntry)\
               .filter(LogEntry.loguser == u)\
               .order_by(desc(LogEntry.id))[:50]

    return ('user.html', {
        'tillobject': u,
        'tuser': u,
        'sales': sales,
        'payments': payments,
        'annotations': annotations,
        'logs': logs,
        'form': form,
    })


@tillweb_view
def grouplist(request, info):
    groups = td.s.query(Group)\
                 .order_by(Group.id)\
                 .all()

    return ('grouplist.html', {
        'nav': [("Groups", info.reverse("tillweb-till-groups"))],
        'groups': groups,
        'may_create_group': info.user_has_perm("edit-user"),
    })


class EditGroupForm(forms.Form):
    name = forms.CharField()
    description = forms.CharField()
    permissions = StringIDMultipleChoiceField(
        Permission, 'id',
        query_filter=lambda q: q.order_by(Permission.id),
        required=False)


@tillweb_view
def group(request, info, groupid):
    g = td.s.query(Group).get(groupid)
    if not g:
        raise Http404

    form = None

    # XXX may want to introduce a permission for editing groups?
    # edit-user is the closest I could find
    if info.user_has_perm("edit-user"):
        initial = {
            'name': g.id,
            'description': g.description,
            'permissions': g.permissions,
        }
        if request.method == "POST":
            if 'submit_delete' in request.POST:
                messages.success(request, f"Group '{g.id}' deleted.")
                td.s.delete(g)
                td.s.commit()
                return HttpResponseRedirect(
                    info.reverse("tillweb-till-groups"))
            form = EditGroupForm(request.POST, initial=initial)
            if form.is_valid():
                cd = form.cleaned_data
                g.id = cd['name']
                g.description = cd['description']
                g.permissions = cd['permissions']
                td.s.commit()
                messages.success(request, f"Group '{g.id}' updated.")
                return HttpResponseRedirect(
                    info.reverse("tillweb-till-groups") + "#row-" + g.id)
        else:
            form = EditGroupForm(initial=initial)

    return ('group.html', {
        'tillobject': g,
        'group': g,
        'form': form,
        'can_delete': len(g.users) == 0,
    })


@tillweb_view
def create_group(request, info):
    # XXX may want to introduce a permission for editing groups?
    # edit-user is the closest I could find
    if not info.user_has_perm("edit-user"):
        return HttpResponseForbidden(
            "You don't have permission to create new groups")

    if request.method == "POST":
        form = EditGroupForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            g = Group(id=cd['name'],
                      description=cd['description'],
                      permissions=cd['permissions'])
            td.s.add(g)
            try:
                td.s.commit()
                messages.success(request, "Group '{}' created.".format(g.id))
                return HttpResponseRedirect(
                    info.reverse("tillweb-till-groups") + "#row-" + g.id)
            except sqlalchemy.exc.IntegrityError:
                td.s.rollback()
                form.add_error("name", "There is another group with this name")
                messages.error(
                    request, "Could not create the group: there is "
                    "another group with this name")
    else:
        form = EditGroupForm()

    return ('new-group.html', {
        'form': form,
        'nav': [("Groups", info.reverse("tillweb-till-groups")),
                ("New", info.reverse("tillweb-create-till-group"))],
    })


@tillweb_view
def logsindex(request, info):
    return ('logs.html', {
        'nav': [("Logs", info.reverse("tillweb-logs"))],
    })


@tillweb_view
def logdetail(request, info, logid):
    l = td.s.query(LogEntry)\
            .get(logid)
    if not l:
        raise Http404
    return ('logentry.html', {
        'log': l,
        'tillobject': l,
    })


@tillweb_view
def configindex(request, info):
    c = td.s.query(Config).order_by(Config.key).all()
    return ('configindex.html', {
        'config': c,
        'nav': [("Config", info.reverse("tillweb-config-index"))],
    })


class ConfigItemUpdateForm(forms.Form):
    def __init__(self, datatype, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if datatype == "multiline text":
            self.fields['value'].widget = forms.Textarea()

    value = forms.CharField(required=False)


@tillweb_view
def configitem(request, info, key):
    c = td.s.query(Config).get(key)
    if not c:
        raise Http404
    may_edit = info.user_has_perm("edit-config")

    form = None
    if may_edit:
        initial = {'value': c.value}
        if request.method == 'POST':
            form = ConfigItemUpdateForm(c.type, request.POST, initial=initial)
            if form.is_valid():
                oldvalue = c.value
                c.value = form.cleaned_data['value']
                if c.type == "multiline text":
                    user.log(f"Changed config item '{c.logref}'")
                else:
                    user.log(f"Changed config item '{c.logref}' "
                             f"from '{oldvalue}' to '{c.value}'")
                messages.success(request, f"{c.display_name} updated")
                td.s.commit()
                if 'submit_update' in request.POST:
                    return HttpResponseRedirect(
                        info.reverse("tillweb-config-index"))
                else:
                    return HttpResponseRedirect(c.get_absolute_url())
        else:
            form = ConfigItemUpdateForm(c.type, initial=initial)

    return ('configitem.html', {
        'config': c,
        'tillobject': c,
        'form': form,
    })


@tillweb_view
def reportindex(request, info):
    return ('reports.html', {
        'nav': [("Reports", info.reverse("tillweb-reports"))],
    })


class WasteReportForm(DatePeriodForm):
    columns = forms.ChoiceField(label="Columns show", choices=[
        ("depts", "Departments"),
        ("waste", "Waste type"),
    ])


@tillweb_view
def waste_report(request, info):
    if request.method == 'POST' and "submit_waste" in request.POST:
        wasteform = WasteReportForm(request.POST, prefix="waste")
        if wasteform.is_valid():
            cd = wasteform.cleaned_data
            return spreadsheets.waste(
                start=cd['startdate'],
                end=cd['enddate'],
                cols=cd['columns'],
                tillname=info.tillname)
    else:
        wasteform = WasteReportForm(prefix="waste")

    return ('wasted-stock-report.html', {
        'nav': [
            ("Reports", info.reverse("tillweb-reports")),
            ("Wasted stock", info.reverse("tillweb-report-wasted-stock")),
        ],
        'wasteform': wasteform,
    })


class StockSoldReportForm(DatePeriodForm):
    dates = forms.ChoiceField(label="Based on", choices=[
        ("transaction", "Transaction Date"),
        ("stockusage", "Date entered"),
    ])


@tillweb_view
def stock_sold_report(request, info):
    if request.method == 'POST' and "submit_stocksold" in request.POST:
        stocksoldform = StockSoldReportForm(request.POST, prefix="stocksold")
        if stocksoldform.is_valid():
            cd = stocksoldform.cleaned_data
            return spreadsheets.stocksold(
                start=cd['startdate'],
                end=cd['enddate'],
                dates=cd['dates'],
                tillname=info.tillname)
    else:
        stocksoldform = StockSoldReportForm(prefix="stocksold")

    return ('stock-sold-report.html', {
        'nav': [
            ("Reports", info.reverse("tillweb-reports")),
            ("Stock sold", info.reverse("tillweb-report-stock-sold")),
        ],
        'stocksoldform': stocksoldform,
    })
