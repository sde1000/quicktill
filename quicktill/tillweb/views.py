from __future__ import unicode_literals
from django.http import HttpResponse,Http404,HttpResponseRedirect
from django.contrib.auth.decorators import login_required
from django.shortcuts import render_to_response
from django.template import RequestContext,Context
from django.template.loader import get_template
from django.conf import settings
from django import forms
from django.forms.util import ErrorList
from models import *
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import subqueryload,subqueryload_all
from sqlalchemy.orm import joinedload,joinedload_all
from sqlalchemy.orm import lazyload
from sqlalchemy.orm import undefer,defer,undefer_group
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql import desc
from sqlalchemy.sql.expression import tuple_,func,null
from sqlalchemy import distinct
from quicktill.models import *
from quicktill.version import version
from . import spreadsheets

# We use this date format in templates - defined here so we don't have
# to keep repeating it.  It's available in templates as 'dtf'
dtf="Y-m-d H:i"

# This view is only used when the tillweb is integrated into another
# django-based website.
@login_required
def publist(request):
    access=Access.objects.filter(user=request.user)
    return render_to_response('tillweb/publist.html',
                              {'access':access,},
                              context_instance=RequestContext(request))

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
    single_site=getattr(settings,'TILLWEB_SINGLE_SITE',False)
    tillweb_login_required=getattr(settings,'TILLWEB_LOGIN_REQUIRED',True)
    def new_view(request,pubname,*args,**kwargs):
        if single_site:
            till=None
            tillname=settings.TILLWEB_PUBNAME
            access=settings.TILLWEB_DEFAULT_ACCESS
            session=settings.TILLWEB_DATABASE()
            base='/'
        else:
            try:
                till=Till.objects.get(slug=pubname)
            except Till.DoesNotExist:
                raise Http404
            try:
                access=Access.objects.get(user=request.user,till=till)
            except Access.DoesNotExist:
                # Pretend it doesn't exist!
                raise Http404
            try:
                session=settings.SQLALCHEMY_SESSIONS[till.database]()
            except ValueError:
                # The database doesn't exist
                raise Http404
            base=till.get_absolute_url()
            tillname=till.name
            access=access.permission
        try:
            info={
                'base':base,
                'access':access,
                'tillname':tillname,
                }
            result=view(request,info,session,*args,**kwargs)
            if isinstance(result,HttpResponse): return result
            t,d=result
            # object is the Till object, possibly used for a nav menu
            # (it's None if we are set up for a single site)
            # till is the name of the till
            # access is 'R','M','F'
            # u is the base URL for the till website including trailing /
            defaults={'object':till,
                      'till':tillname,'access':access,'u':base,
                      'dtf':dtf,'pubname':pubname,
                      'version':version}
            defaults.update(d)
            return render_to_response(
                'tillweb/'+t,defaults,
                context_instance=RequestContext(request))
        except OperationalError as oe:
            t=get_template('tillweb/operationalerror.html')
            return HttpResponse(
                t.render(RequestContext(
                        request,{'object':till,'access':access,'error':oe})),
                status=503)
        finally:
            session.close()
    if tillweb_login_required or not single_site:
        new_view=login_required(new_view)
    return new_view

def business_totals(session,firstday,lastday):
    # This query is wrong in that it ignores the 'business' field in
    # VatRate objects.  Fixes that don't involve a database round-trip
    # per session are welcome!
    return session.query(Business,func.sum(Transline.items*Transline.amount)).\
        join(VatBand).\
        join(Department).\
        join(Transline).\
        join(Transaction).\
        join(Session).\
        filter(Session.date<=lastday).\
        filter(Session.date>=firstday).\
        order_by(Business.id).\
        group_by(Business).\
        all()

@tillweb_view
def pubroot(request,info,session):
    date=datetime.date.today()
    # If it's the early hours of the morning, it's more useful for us
    # to consider it still to be yesterday.
    if datetime.datetime.now().hour<4: date=date-datetime.timedelta(1)
    thisweek_start=date-datetime.timedelta(date.weekday())
    thisweek_end=thisweek_start+datetime.timedelta(6)
    lastweek_start=thisweek_start-datetime.timedelta(7)
    lastweek_end=thisweek_end-datetime.timedelta(7)
    weekbefore_start=lastweek_start-datetime.timedelta(7)
    weekbefore_end=lastweek_end-datetime.timedelta(7)

    weeks=[("Current week",thisweek_start,thisweek_end,
            business_totals(session,thisweek_start,thisweek_end)),
           ("Last week",lastweek_start,lastweek_end,
            business_totals(session,lastweek_start,lastweek_end)),
           ("The week before last",weekbefore_start,weekbefore_end,
            business_totals(session,weekbefore_start,weekbefore_end))]

    currentsession=Session.current(session)
    barsummary=session.query(StockLine).\
        filter(StockLine.location=="Bar").\
        order_by(StockLine.dept_id,StockLine.name).\
        options(joinedload_all('stockonsale.stocktype.unit')).\
        options(undefer_group('qtys')).\
        all()
    stillage=session.query(StockAnnotation).\
        join(StockItem).\
        outerjoin(StockLine).\
        filter(tuple_(StockAnnotation.text,StockAnnotation.time).in_(
            select([StockAnnotation.text,func.max(StockAnnotation.time)],
                   StockAnnotation.atype=='location').\
                group_by(StockAnnotation.text))).\
        filter(StockItem.finished==None).\
        order_by(StockLine.name!=null(),StockAnnotation.time).\
        options(joinedload_all('stockitem.stocktype.unit')).\
        options(joinedload_all('stockitem.stockline')).\
        options(undefer_group('qtys')).\
        all()
    return ('index.html',
            {'currentsession':currentsession,
             'barsummary':barsummary,
             'stillage':stillage,
             'weeks':weeks,
             })

@tillweb_view
def locationlist(request,info,session):
    locations=[x[0] for x in session.query(distinct(StockLine.location)).\
                   order_by(StockLine.location).all()]
    return ('locations.html',{'locations':locations})

@tillweb_view
def location(request,info,session,location):
    lines=session.query(StockLine).\
        filter(StockLine.location==location).\
        order_by(StockLine.dept_id,StockLine.name).\
        options(joinedload('stockonsale')).\
        options(joinedload('stockonsale.stocktype')).\
        all()
    return ('location.html',{'location':location,'lines':lines})

class SessionFinderForm(forms.Form):
    # django-1.6 uses forms.NumberInput by default for integer fields;
    # this is only valid in HTML5, which we are not using yet.
    # Specify the TextInput widget explicitly for now.
    session=forms.IntegerField(label="Session ID",widget=forms.TextInput)

class SessionRangeForm(forms.Form):
    startdate=forms.DateField(label="Start date",required=False)
    enddate=forms.DateField(label="End date",required=False)

@tillweb_view
def sessionfinder(request,info,session):
    if request.method=='POST' and "submit_find" in request.POST:
        form=SessionFinderForm(request.POST)
        if form.is_valid():
            s=session.query(Session).get(form.cleaned_data['session'])
            if s:
                return HttpResponseRedirect(info['base']+s.tillweb_url)
            errors=form._errors.setdefault("session",ErrorList())
            errors.append("This session does not exist.")
    else:
        form=SessionFinderForm()
    if request.method=='POST' and "submit_sheet" in request.POST:
        rangeform=SessionRangeForm(request.POST)
        if rangeform.is_valid():
            cd=rangeform.cleaned_data
            return spreadsheets.sessionrange(
                session,
                start=cd['startdate'],end=cd['enddate'],
                tillname=info['tillname'])
    else:
        rangeform=SessionRangeForm()
    recent=session.query(Session).\
        options(undefer('total')).\
        options(undefer('actual_total')).\
        order_by(desc(Session.id))[:30]
    return ('sessions.html',{'recent':recent,'form':form,'rangeform':rangeform})

@tillweb_view
def session(request,info,session,sessionid):
    try:
        # The subqueryload_all() significantly improves the speed of loading
        # the transaction totals
        s=session.query(Session).\
            filter_by(id=int(sessionid)).\
            options(undefer('transactions.total')).\
            options(undefer('total')).\
            options(undefer('closed_total')).\
            options(undefer('actual_total')).\
            options(joinedload('transactions.payments')).\
            one()
    except NoResultFound:
        raise Http404
    nextsession=session.query(Session).\
        filter(Session.id>s.id).\
        order_by(Session.id).\
        first()
    nextlink=info['base']+nextsession.tillweb_url if nextsession else None
    prevsession=session.query(Session).\
        filter(Session.id<s.id).\
        order_by(desc(Session.id)).\
        first()
    prevlink=info['base']+prevsession.tillweb_url if prevsession else None
    return ('session.html',{'session':s,'nextlink':nextlink,
                            'prevlink':prevlink})

@tillweb_view
def sessiondept(request,info,session,sessionid,dept):
    try:
        s=session.query(Session).filter_by(id=int(sessionid)).one()
    except NoResultFound:
        raise Http404
    try:
        dept=session.query(Department).filter_by(id=int(dept)).one()
    except NoResultFound:
        raise Http404
    nextsession=session.query(Session).\
        filter(Session.id>s.id).\
        order_by(Session.id).\
        first()
    nextlink=info['base']+nextsession.tillweb_url+"dept{}/".format(dept.id) \
        if nextsession else None
    prevsession=session.query(Session).\
        filter(Session.id<s.id).\
        order_by(desc(Session.id)).\
        first()
    prevlink=info['base']+prevsession.tillweb_url+"dept{}/".format(dept.id) \
        if prevsession else None
    translines=session.query(Transline).\
        join(Transaction).\
        options(joinedload('transaction')).\
        options(joinedload('user')).\
        options(joinedload_all('stockref.stockitem.stocktype.unit')).\
        filter(Transaction.sessionid==s.id).\
        filter(Transline.dept_id==dept.id).\
        order_by(Transline.id).\
        all()
    return ('sessiondept.html',{'session':s,'department':dept,
                                'translines':translines,
                                'nextlink':nextlink,'prevlink':prevlink})

@tillweb_view
def transaction(request,info,session,transid):
    try:
        t=session.query(Transaction).\
            filter_by(id=int(transid)).\
            options(subqueryload_all('payments')).\
            options(joinedload_all('lines.stockref.stockitem.stocktype')).\
            options(joinedload('lines.user')).\
            options(undefer('total')).\
            one()
    except NoResultFound:
        raise Http404
    return ('transaction.html',{'transaction':t,})

@tillweb_view
def supplierlist(request,info,session):
    sl=session.query(Supplier).order_by(Supplier.name).all()
    return ('suppliers.html',{'suppliers':sl})

@tillweb_view
def supplier(request,info,session,supplierid):
    try:
        s=session.query(Supplier).\
            filter_by(id=int(supplierid)).\
            one()
    except NoResultFound:
        raise Http404
    return ('supplier.html',{'supplier':s,})

@tillweb_view
def deliverylist(request,info,session):
    dl=session.query(Delivery).order_by(desc(Delivery.id)).\
        options(joinedload('supplier')).\
        all()
    return ('deliveries.html',{'deliveries':dl})

@tillweb_view
def delivery(request,info,session,deliveryid):
    try:
        d=session.query(Delivery).\
            filter_by(id=int(deliveryid)).\
            options(joinedload_all('items.stocktype.unit')).\
            options(joinedload_all('items.stockline')).\
            options(undefer_group('qtys')).\
            one()
    except NoResultFound:
        raise Http404
    return ('delivery.html',{'delivery':d,})

class StockTypeForm(forms.Form):
    manufacturer=forms.CharField(required=False)
    name=forms.CharField(required=False)
    shortname=forms.CharField(required=False)
    def is_filled_in(self):
        cd=self.cleaned_data
        return cd['manufacturer'] or cd['name'] or cd['shortname']
    def filter(self,q):
        cd=self.cleaned_data
        if cd['manufacturer']:
            q=q.filter(StockType.manufacturer.ilike("%{}%".format(cd['manufacturer'])))
        if cd['name']:
            q=q.filter(StockType.name.ilike("%{}%".format(cd['name'])))
        if cd['shortname']:
            q=q.filter(StockType.shortname.ilike("%{}%".format(cd['shortname'])))
        return q

@tillweb_view
def stocktypesearch(request,info,session):
    form=StockTypeForm(request.GET)
    result=[]
    q=session.query(StockType).order_by(
        StockType.dept_id,StockType.manufacturer,StockType.name)
    if form.is_valid():
        if form.is_filled_in():
            q=form.filter(q)
            result=q.all()
    return ('stocktypesearch.html',{'form':form,'stocktypes':result})

@tillweb_view
def stocktype(request,info,session,stocktype_id):
    try:
        s=session.query(StockType).\
            filter_by(id=int(stocktype_id)).\
            one()
    except NoResultFound:
        raise Http404
    include_finished=request.GET.get("show_finished","off")=="on"
    items=session.query(StockItem).\
        filter(StockItem.stocktype==s).\
        options(undefer_group('qtys')).\
        order_by(desc(StockItem.id))
    if not include_finished:
        items=items.filter(StockItem.finished==None)
    items=items.all()
    return ('stocktype.html',{'stocktype':s,'items':items,
                              'include_finished':include_finished})

class StockForm(StockTypeForm):
    include_finished=forms.BooleanField(
        required=False,label="Include finished items")

@tillweb_view
def stocksearch(request,info,session):
    form=StockForm(request.GET)
    result=[]
    q=session.query(StockItem).join(StockType).order_by(StockItem.id).\
        options(joinedload_all('stocktype.unit')).\
        options(joinedload('stockline')).\
        options(undefer_group('qtys'))
    if form.is_valid():
        if form.is_filled_in():
            q=form.filter(q)
            if not form.cleaned_data['include_finished']:
                q=q.filter(StockItem.finished==None)
            result=q.all()
    return ('stocksearch.html',{'form':form,'stocklist':result})

@tillweb_view
def stock(request,info,session,stockid):
    try:
        s=session.query(StockItem).\
            filter_by(id=int(stockid)).\
            options(joinedload_all('stocktype.department')).\
            options(joinedload_all('stocktype.stockline_log.stockline')).\
            options(joinedload_all('delivery.supplier')).\
            options(joinedload_all('stockunit.unit')).\
            options(joinedload_all('annotations.type')).\
            options(subqueryload_all('out.transline.transaction')).\
            options(undefer_group('qtys')).\
            one()
    except NoResultFound:
        raise Http404
    return ('stock.html',{'stock':s,})

@tillweb_view
def stocklinelist(request,info,session):
    lines=session.query(StockLine).\
        order_by(StockLine.dept_id,StockLine.name).\
        all()
    return ('stocklines.html',{'lines':lines,})

@tillweb_view
def stockline(request,info,session,stocklineid):
    try:
        s=session.query(StockLine).\
            filter_by(id=int(stocklineid)).\
            options(joinedload_all('stockonsale.stocktype.unit')).\
            options(undefer_group('qtys')).\
            one()
    except NoResultFound:
        raise Http404
    return ('stockline.html',{'stockline':s,})

@tillweb_view
def plulist(request,info,session):
    plus=session.query(PriceLookup).\
        order_by(PriceLookup.dept_id,PriceLookup.description).\
        all()
    return ('plus.html',{'plus':plus,})

@tillweb_view
def plu(request,info,session,pluid):
    try:
        p=session.query(PriceLookup).\
            filter_by(id=int(pluid)).\
            one()
    except NoResultFound:
        raise Http404
    return ('plu.html',{'plu':p,})

@tillweb_view
def departmentlist(request,info,session):
    depts=session.query(Department).order_by(Department.id).all()
    return ('departmentlist.html',{'depts':depts})

@tillweb_view
def department(request,info,session,departmentid):
    d=session.query(Department).get(int(departmentid))
    if d is None: raise Http404
    include_finished=request.GET.get("show_finished","off")=="on"
    items=session.query(StockItem).\
        join(StockType).\
        filter(StockType.department==d).\
        order_by(desc(StockItem.id)).\
        options(joinedload_all('stocktype.unit')).\
        options(undefer_group('qtys')).\
        options(joinedload('stockline')).\
        options(joinedload('finishcode'))
    if not include_finished:
        items=items.filter(StockItem.finished==None)
    items=items.all()
    return ('department.html',{'department':d,'items':items,
                               'include_finished':include_finished})

class StockCheckForm(forms.Form):
    def __init__(self,depts,*args,**kwargs):
        super(StockCheckForm,self).__init__(*args,**kwargs)
        self.fields['department'].choices=[(d.id,d.description) for d in depts]
    # django-1.6 uses forms.NumberInput by default for integer fields;
    # this is only valid in HTML5, which we are not using yet.
    # Specify the TextInput widget explicitly for now.
    short=forms.TextInput(attrs={'size':3,'maxlength':3})
    weeks_ahead=forms.IntegerField(
        label="Weeks ahead",widget=short,
        min_value=0)
    months_behind=forms.IntegerField(
        label="Months behind",widget=short,
        min_value=0)
    minimum_sold=forms.FloatField(
        label="Minimum sold",widget=short,
        min_value=0.0, initial=1.0)
    department=forms.ChoiceField()

@tillweb_view
def stockcheck(request,info,session):
    buylist=[]
    depts=session.query(Department).order_by(Department.id).all()
    if request.method == 'POST':
        form=StockCheckForm(depts,request.POST)
        if form.is_valid():
            cd=form.cleaned_data
            ahead=datetime.timedelta(days=cd['weeks_ahead']*7)
            behind=datetime.timedelta(days=cd['months_behind']*30.4)
            min_sale=cd['minimum_sold']
            dept=int(cd['department'])
            q=session.query(StockType,func.sum(StockOut.qty)/behind.days).\
               join(StockItem).\
               join(StockOut).\
               options(lazyload(StockType.department)).\
               options(lazyload(StockType.unit)).\
               options(undefer(StockType.instock)).\
               filter(StockOut.removecode_id=='sold').\
               filter((func.now()-StockOut.time)<behind).\
               filter(StockType.dept_id == dept).\
               having(func.sum(StockOut.qty)/behind.days>min_sale).\
               group_by(StockType)
            r=q.all()
            buylist=[(st,'{:0.1f}'.format(sold),
                      '{:0.1f}'.format(sold*ahead.days-st.instock))
                     for st,sold in r]
            buylist.sort(key=lambda l:float(l[2]),reverse=True)
    else:
        form=StockCheckForm(depts)
    return ('stockcheck.html',{'form':form,'buylist':buylist})

@tillweb_view
def userlist(request,info,session):
    q=session.query(User).order_by(User.fullname)
    include_inactive=request.GET.get("include_inactive","off")=="on"
    if not include_inactive:
        q=q.filter(User.enabled==True)
    users=q.all()
    return ('userlist.html',{'users':users,'include_inactive':include_inactive})

@tillweb_view
def user(request,info,session,userid):
    try:
        u=session.query(User).\
            options(joinedload('permissions')).\
            options(joinedload('tokens')).\
            get(int(userid))
    except NoResultFound:
        raise Http404
    sales=session.query(Transline).filter(Transline.user==u).\
        options(joinedload('transaction')).\
        options(joinedload_all('stockref.stockitem.stocktype.unit')).\
        order_by(desc(Transline.time))[:50]
    payments=session.query(Payment).filter(Payment.user==u).\
        options(joinedload('transaction')).\
        options(joinedload('paytype')).\
        order_by(desc(Payment.time))[:50]
    annotations=session.query(StockAnnotation).\
        options(joinedload_all('stockitem.stocktype')).\
        options(joinedload('type')).\
        filter(StockAnnotation.user==u).\
        order_by(desc(StockAnnotation.time))[:50]
    return ('user.html',{'tuser':u,'sales':sales,'payments':payments,
                         'annotations':annotations})

import matplotlib
matplotlib.use("SVG")
import matplotlib.pyplot as plt

@tillweb_view
def session_sales_pie_chart(request,info,session,sessionid):
    try:
        s = session.query(Session).\
            filter_by(id=int(sessionid)).\
            one()
    except NoResultFound:
        raise Http404
    dt = s.dept_totals
    fig = plt.figure(figsize=(5,5))
    ax = fig.add_subplot(1,1,1)
    patches,texts = ax.pie(
        [x[1] for x in dt], labels=[x[0].description for x in dt],
        colors=['r','g','b','c','y','m','olive','brown','orchid',
                'royalblue','sienna','steelblue'])
    for t in texts:
        t.set_fontsize(8)
    response = HttpResponse(content_type="image/svg+xml")
    fig.savefig(response,transparent=True)
    return response

@tillweb_view
def session_users_pie_chart(request,info,session,sessionid):
    try:
        s = session.query(Session).\
            filter_by(id=int(sessionid)).\
            one()
    except NoResultFound:
        raise Http404
    ut = s.user_totals
    fig = plt.figure(figsize=(5,5))
    ax = fig.add_subplot(1,1,1)
    patches,texts = ax.pie(
        [x[2] for x in ut], labels=[x[0].fullname for x in ut],
        colors=['r','g','b','c','y','m','olive','brown','orchid',
                'royalblue','sienna','steelblue'])
    for t in texts:
        t.set_fontsize(8)
    response = HttpResponse(content_type="image/svg+xml")
    fig.savefig(response,transparent=True)
    return response
