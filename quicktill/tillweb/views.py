from django.http import HttpResponse,Http404
from django.contrib.auth.decorators import login_required
from django.shortcuts import render_to_response
from django.template import RequestContext,Context
from django.template.loader import get_template
from django.views.generic import list_detail
from django.conf import settings
from models import *
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import subqueryload_all,joinedload,subqueryload
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql import desc
from sqlalchemy.sql.expression import tuple_
from quicktill.models import *

@login_required
def publist(request):
    access=Access.objects.filter(user=request.user)
    return render_to_response('tillweb/publist.html',
                              {'access':access,},
                              context_instance=RequestContext(request))

# A lot of the view functions in this file follow a similar pattern.
# They are kept separate rather than implemented as a generic view so
# that page-specific optimisations (the ".options()" clauses in the
# queries) can be added.  The common operations have been moved into
# the @tillweb_view decorator.

def tillweb_view(view):
    @login_required
    def new_view(request,pubname,*args,**kwargs):
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
        try:
            t,d=view(request,till,access,session,*args,**kwargs)
            defaults={'object':till,'till':till,'access':access,
                      'u':till.get_absolute_url()}
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
    return new_view

@tillweb_view
def pubroot(request,till,access,session):
    currentsession=Session.current(session)
    barsummary=location_summary(session,"Bar")
    stillage=session.query(StockAnnotation).\
        join(StockItem).\
        filter(tuple_(StockAnnotation.text,StockAnnotation.time).in_(
            select([StockAnnotation.text,func.max(StockAnnotation.time)],
                   StockAnnotation.atype=='location').\
                group_by(StockAnnotation.text))).\
        filter(StockItem.finished==None).\
        order_by(StockAnnotation.text).\
        options(joinedload('stockitem')).\
        options(joinedload('stockitem.stocktype')).\
        options(joinedload('stockitem.stockonsale')).\
        options(joinedload('stockitem.stockonsale.stockline')).\
        all()
    return ('index.html',
            {'currentsession':currentsession,
             'barsummary':barsummary,
             'stillage':stillage,
             })

@tillweb_view
def session(request,till,access,session,sessionid):
    try:
        # The subqueryload_all() significantly improves the speed of loading
        # the transaction totals
        s=session.query(Session).\
            filter_by(id=int(sessionid)).\
            options(subqueryload_all('transactions.lines')).\
            one()
    except NoResultFound:
        raise Http404
    nextsession=session.query(Session).\
        filter(Session.id>s.id).\
        order_by(Session.id).\
        first()
    nextlink=(
        till.get_absolute_url()+nextsession.tillweb_url if nextsession
        else None)
    prevsession=session.query(Session).\
        filter(Session.id<s.id).\
        order_by(desc(Session.id)).\
        first()
    prevlink=(
        till.get_absolute_url()+prevsession.tillweb_url if prevsession
        else None)
    return ('session.html',{'session':s,'nextlink':nextlink,
                            'prevlink':prevlink})

@tillweb_view
def sessiondept(request,till,access,session,sessionid,dept):
    try:
        s=session.query(Session).filter_by(id=int(sessionid)).one()
    except NoResultFound:
        raise Http404
    try:
        dept=session.query(Department).filter_by(id=int(dept)).one()
    except NoResultFound:
        raise Http404
    translines=session.query(Transline).\
        join(Transaction).\
        filter(Transaction.sessionid==s.id).\
        filter(Transline.dept_id==dept.id).\
        order_by(Transline.time).\
        all()
    # XXX really need to joinedload stockout and related tables, but
    # there's no relation for that in the model at the moment.  Need
    # to resolve that circular dependency for creating stockout and
    # transline that mutually refer to each other.
    
    # Short version: this adds a database round-trip for every line in
    # the output.  Ick!
    return ('sessiondept.html',{'session':s,'department':dept,
                                'translines':translines})

@tillweb_view
def transaction(request,till,access,session,transid):
    try:
        t=session.query(Transaction).\
            filter_by(id=int(transid)).\
            options(subqueryload_all('lines')).\
            options(subqueryload_all('payments')).\
            one()
    except NoResultFound:
        raise Http404
    return ('transaction.html',{'transaction':t,})

@tillweb_view
def supplier(request,till,access,session,supplierid):
    try:
        s=session.query(Supplier).\
            filter_by(id=int(supplierid)).\
            one()
    except NoResultFound:
        raise Http404
    return ('supplier.html',{'supplier':s,})

@tillweb_view
def delivery(request,till,access,session,deliveryid):
    try:
        d=session.query(Delivery).\
            filter_by(id=int(deliveryid)).\
            one()
    except NoResultFound:
        raise Http404
    return ('delivery.html',{'delivery':d,})

@tillweb_view
def stocktype(request,till,access,session,stocktype_id):
    try:
        s=session.query(StockType).\
            filter_by(id=int(stocktype_id)).\
            one()
    except NoResultFound:
        raise Http404
    return ('stocktype.html',{'stocktype':s,})

@tillweb_view
def stock(request,till,access,session,stockid):
    try:
        s=session.query(StockItem).\
            filter_by(id=int(stockid)).\
            options(joinedload('stocktype')).\
            options(joinedload('stocktype.department')).\
            options(joinedload('stocktype.stockline_log')).\
            options(joinedload('stocktype.stockline_log.stockline')).\
            options(joinedload('delivery')).\
            options(joinedload('delivery.supplier')).\
            options(joinedload('stockunit')).\
            options(joinedload('stockunit.unit')).\
            options(subqueryload_all('out.transline.transaction')).\
            one()
    except NoResultFound:
        raise Http404
    return ('stock.html',{'stock':s,})

@tillweb_view
def stockline(request,till,access,session,stocklineid):
    try:
        s=session.query(StockLine).\
            filter_by(id=int(stocklineid)).\
            one()
    except NoResultFound:
        raise Http404
    return ('stockline.html',{'stockline':s,})
