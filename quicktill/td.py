# Till database handling routines

# Various parts of the UI call on these routines to work out what the
# hell is going on.  We try to ensure the database constraints are
# never broken here, but that's not really a substitute for
# implementing them in the database itself.

import time
#from . import stock
import psycopg2 as db
import psycopg2.extensions
from decimal import Decimal
import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import subqueryload_all,joinedload,subqueryload
from sqlalchemy.orm import undefer
from sqlalchemy.sql.expression import tuple_,func,null
from sqlalchemy.sql import select,not_
from sqlalchemy.exc import IntegrityError
from sqlalchemy import distinct
from . import models
from .models import *

import logging
log=logging.getLogger()

# psycopg converted database numeric() types into float() types.

# By default, psycopg2 converts them into decimal.Decimal() types -
# arguably more correct, but not what the rest of this package is
# expecting.

# Until the rest of the package is updated to expect Decimal()s,
# convert to float()s instead:
#DEC2FLOAT = psycopg2.extensions.new_type(
#    db._psycopg.DECIMAL.values,
#    'DEC2FLOAT',
#    lambda value, curs: float(value) if value is not None else None)
#psycopg2.extensions.register_type(DEC2FLOAT)
# If psycopg2._psycopg.DECIMAL stops working, use
# psycopg2.extensions.DECIMAL instead.

database=None

con=None
def cursor():
    con.commit()
    return con.cursor()
def commit():
    con.commit()

# ORM session; most database access will go through this
s=None
# Sessionmaker, set up during init()
sm=None
class SessionLifecycleError(Exception):
    pass
def start_session():
    """
    Change td.s from None to an active session object, or raise an
    exception if td.s is not None.

    """
    global s,sm
    if s is not None: raise SessionLifecycleError()
    s=sm()
    log.debug("Start session")
def end_session():
    """
    Change td.s from an active session object to None, or raise an
    exception if td.s is already None.  Calls s.close().

    """
    global s
    if s is None: raise SessionLifecycleError()
    s.commit()
    s.close()
    s=None
    log.debug("End session")

### Convenience functions

def trans_restore():
    """Restores all deferred transactions.

    """
    global s
    sc=Session.current(s)
    if sc is None: return 0
    deferred=s.query(Transaction).filter(Transaction.sessionid==None).all()
    for i in deferred:
        i.session=sc
    s.flush()

### Functions related to the stocktypes table

def stocktype_completemanufacturer(m):
    global s
    result=s.execute(
        select([StockType.manufacturer]).\
            where(StockType.manufacturer.ilike(m+'%'))
        )
    return [x[0] for x in result]

def stocktype_completename(m,n):
    global s
    result=s.execute(
        select([distinct(StockType.name)]).\
            where(StockType.manufacturer==m).\
            where(StockType.name.ilike(n+'%'))
        )
    return [x[0] for x in result]

### Functions related to the stock,stockout,stockonsale tables

def stock_checkpullthru(stockid,maxtime):
    """Did this stock item require pulling through?"""
    global s
    return s.execute(
        select([func.now()-func.max(StockOut.time)>maxtime]).\
            where(StockOut.stockid==stockid).\
            where(StockOut.removecode_id.in_(['sold','pullthru']))
        ).scalar()

def stock_autoallocate_candidates(deliveryid=None):
    """
    Return a list of (stockitem,stockline) tuples.

    """
    global s
    q=s.query(StockItem,StockLine).\
        join(StockType).\
        join(Delivery).\
        outerjoin(StockOnSale).\
        filter(StockLine.id.in_(
            select([StockLineTypeLog.stocklineid],
                   whereclause=(
                        StockLineTypeLog.stocktype_id==StockItem.stocktype_id)).\
                correlate(StockItem.__table__))).\
        filter(StockItem.finished==None).\
        filter(StockOnSale.stockline==None).\
        filter(Delivery.checked==True).\
        filter(StockLine.capacity!=None).\
        order_by(StockItem.id)
    if deliveryid is not None:
        q=q.filter(Delivery.id==deliveryid)
    return q.all()

def stock_purge():
    """Stock items that have been completely used up through the
    display mechanism should be marked as 'finished' in the stock
    table, and purged from the stockonsale table.  This is usually
    done automatically at the end of each session because stock items
    may be put back on display through the voiding mechanism during
    the session, but is also available as an option on the till
    management menu.

    """
    global s
    # Find stockonsale that is ready for purging: used==size on a
    # stockline that has a display capacity
    finished=s.query(StockOnSale).\
        join(StockOnSale.stockline).\
        join(StockOnSale.stockitem).\
        filter(not_(StockLine.capacity==None)).\
        filter(StockItem.remaining==0.0).\
        all()

    # Mark all these stockitems as finished, removing them from being
    # on sale as we go
    for sos in finished:
        sos.stockitem.finished=datetime.datetime.now()
        sos.stockitem.finishcode_id='empty' # guaranteed to exist
        s.delete(sos)
    s.flush()

def stock_recordwaste(stock,reason,amount,update_displayqty):
    """Record wastage of a stock item.  If update_displayqty is set then
    the displayqty field in the stockonsale table will be increased by the
    same amount, so that the quantity on display remains unchanged.  (If
    there is no entry for the stockid in stockonsale then nothing happens.)

    """
    global s
    so=StockOut(stockid=stock,qty=amount,removecode_id=reason)
    s.add(so)
    if update_displayqty:
        sos=s.query(StockOnSale).get(stock) # stockid is primary key here!
        if sos: sos.displayqty=sos.displayqty+1
    s.flush()

### Find out what's on the stillage by checking annotations

def stillage_summary(session):
    stillage=session.query(StockAnnotation).\
        join(StockItem).\
        outerjoin(StockOnSale).\
        outerjoin(StockLine).\
        filter(tuple_(StockAnnotation.text,StockAnnotation.time).in_(
            select([StockAnnotation.text,func.max(StockAnnotation.time)],
                   StockAnnotation.atype=='location').\
                group_by(StockAnnotation.text))).\
        filter(StockItem.finished==None).\
        order_by(StockLine.name!=null(),StockAnnotation.time).\
        options(joinedload('stockitem')).\
        options(joinedload('stockitem.stocktype')).\
        options(joinedload('stockitem.stockonsale')).\
        options(joinedload('stockitem.stockonsale.stockline')).\
        all()
    return stillage

### Check stock levels

def stocklevel_check(dept=None,period='3 weeks'):
    cur=cursor()
    deptstr="" if dept==None else "AND dept=%d"%dept
    cur.execute(
        "SELECT st.stocktype,st.shortname,sum(qty) as sold,"
        "sum(qty)-coalesce((select sum(size-coalesce(used,0)) "
        "FROM stockinfo WHERE stocktype=st.stocktype "
        "AND finished is null),0) as understock "
        "FROM stocktypes st "
        "LEFT JOIN stock s ON st.stocktype=s.stocktype "
        "LEFT JOIN stockout so ON so.stockid=s.stockid "
        "WHERE (removecode='sold' or removecode is null) "
        "%s "
        "AND now()-so.time<'%s' "
        "GROUP BY st.stocktype,st.shortname "
        "ORDER BY understock DESC"%(deptstr,period))
    return cur.fetchall()

### Functions related to food order numbers

def foodorder_reset():
    foodorder_seq.drop()
    foodorder_seq.create()

def foodorder_ticket():
    global s
    return s.execute(select([foodorder_seq.next_value()])).scalar()

### Functions related to stock lines

def stockline_summary(session,locations):
    s=session.query(StockLine).\
        filter(StockLine.location.in_(locations)).\
        filter(StockLine.capacity==None).\
        order_by(StockLine.name).\
        options(joinedload('stockonsale')).\
        options(joinedload('stockonsale.stockitem')).\
        options(joinedload('stockonsale.stockitem.stocktype')).\
        all()
    return s

### Functions relating to till keyboards

def keyboard_checklines(layout,keycode):
    """keycode is a string.  Returns a list of (linename,qty,dept,
    pullthru,menukey,stocklineid,location,capacity) tuples (possibly
    empty).  The list may be in any order; it's up to the caller to
    sort it (eg. by menukey numeric keycode).

    """
    cur=cursor()
    cur.execute("SELECT sl.name,k.qty,sl.dept,sl.pullthru,"
                "k.menukey,k.stocklineid,sl.location,sl.capacity "
                "FROM keyboard k "
                "LEFT JOIN stocklines sl ON sl.stocklineid=k.stocklineid "
                "WHERE k.layout=%s AND k.keycode=%s",(layout,keycode))
    return cur.fetchall()

def keyboard_checkstockline(layout,stocklineid):
    """Return all the key bindings in this keyboard layout for the
    specified stock line.

    """
    cur=cursor()
    cur.execute("SELECT keycode,menukey,qty FROM keyboard "
                "WHERE layout=%s AND stocklineid=%s",(layout,stocklineid))
    return cur.fetchall()

def keyboard_addbinding(layout,keycode,menukey,stocklineid,qty):
    cur=cursor()
    cur.execute("INSERT INTO keyboard (layout,keycode,menukey,stocklineid,qty) "
                "VALUES (%s,%s,%s,%s,%s)",(layout,keycode,menukey,stocklineid,qty))
    commit()

def keyboard_delbinding(layout,keycode,menukey):
    cur=cursor()
    cur.execute("DELETE FROM keyboard WHERE layout=%s AND keycode=%s AND menukey=%s",
                (layout,keycode,menukey))
    commit()

### Functions relating to the sessions,sessiontotals tables

def session_list(session,unpaidonly,closedonly):
    """Return the list of sessions.  Explicitly undefers loading of
    the total column property so that we don't have to make a
    round-trip to the database for each object returned.

    """
    q=session.query(Session).\
        order_by(desc(Session.id)).\
        options(undefer('total'))
    if unpaidonly:
        q=q.filter(select([func.count(SessionTotal.sessionid)],
                          whereclause=SessionTotal.sessionid==Session.id).\
                       correlate(Session.__table__).as_scalar()==0)
    if closedonly:
        q=q.filter(Session.endtime!=None)
    return q.all()

def session_bitcoin_translist(session):
    """Returns the list of transactions involving Bitcoin payment in
    a session."""
    cur=cursor()
    cur.execute("SELECT p.transid FROM payments p "
                "LEFT JOIN transactions t ON t.transid=p.transid "
                "WHERE p.paytype='BTC' AND t.sessionid=%s",(session,))
    return [x[0] for x in cur.fetchall()]

def db_version():
    global s
    return s.execute("select version()").scalar()

def init():
    global con,database,engine,sm
    if database is None:
        raise Exception("No database defined")
    if database[0]==":":
        database="dbname=%s"%database[1:]
    # Conversion to sqlalchemy: create sqlalchemy engine URL from
    # libpq connection string
    csdict=dict([x.split('=',1) for x in database.split(' ')])
    estring="postgresql+psycopg2://"
    if 'user' in csdict:
        estring+=csdict[user]
        if 'password' in csdict:
            estring+=":%s"%(csdict['password'],)
        estring+='@'
    if 'host' in csdict:
        estring+=csdict['host']
    if 'port' in csdict:
        estring+=":%s"%(csdict['port'],)
    estring+="/%s"%(csdict['dbname'],)
    engine=create_engine(estring)
    # We might like to consider adding expire_on_commit=False to the
    # sessionmaker at some point; let's not do that for now so we can
    # spot potentially expired objects more easily while we're
    # converting the code.
    models.metadata.bind=engine # for DDL, eg. to recreate foodorder_seq
    sm=sessionmaker(bind=engine)
    con=db.connect(database)
