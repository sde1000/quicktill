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

def execone(cur,c,*args):
    "Execute c and return the single result. Does not commit."
    cur.execute(c,*args)
    r=cur.fetchone()
    if not r: return None
    return r[0]

def ticket(cur,seq):
    "Fetch a new serial number from the named sequence"
    return execone(cur,"SELECT nextval(%s)",(seq,))

def trans_getlines(trans):
    "Retrieve lines and payments for a transaction"
    cur=cursor()
    cur.execute("SELECT translineid FROM translines WHERE transid=%s "
                "ORDER BY translineid",(trans,))
    lines=[x[0] for x in cur.fetchall()]
    cur.execute("SELECT p.amount,p.paytype,pt.description,p.ref "
                "FROM payments p "
                "LEFT JOIN paytypes pt ON p.paytype=pt.paytype "
                "WHERE transid=%s ORDER BY time ",(trans,))
    payments=cur.fetchall()
    return (lines,payments)

def trans_multiband(trans):
    "Determine whether a transaction has lines in more than one VAT band."
    cur=cursor()
    cur.execute("SELECT DISTINCT vat.band FROM translines tl "
                "LEFT JOIN departments d ON tl.dept=d.dept "
                "LEFT JOIN vat ON d.vatband=vat.band "
                "WHERE transid=%s",(trans,))
    bands=cur.fetchall()
    return len(bands)>1

def trans_paid_by_bitcoin(trans):
    "Determine whether a transaction includes a Bitcoin payment."
    cur=cursor()
    cur.execute("SELECT count(*)>0 FROM payments WHERE transid=%s "
                "AND paytype='BTC'",(trans,))
    return cur.fetchone()[0]

def trans_merge(t1,t2):
    """Merge t1 into t2, and delete t1.

    """
    cur=cursor()
    cur.execute("UPDATE translines SET transid=%s WHERE transid=%s",
                (t2,t1))
    cur.execute("DELETE FROM transactions WHERE transid=%s",(t1,))
    commit()

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

def trans_makefree(transid,removecode):
    """Converts all stock sold in this transaction to 'removecode', and
    deletes the transaction.  Usually used when converting an open transaction
    to 'free drinks'.

    """
    cur=cursor()
    cur.execute("UPDATE stockout SET removecode=%s,translineid=NULL "
                "WHERE translineid IN (SELECT translineid FROM translines "
                "WHERE transid=%s)",(removecode,transid))
    cur.execute("DELETE FROM translines WHERE transid=%s",(transid,))
    cur.execute("DELETE FROM transactions WHERE transid=%s",(transid,))
    commit()

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

def stock_info(stockid_list):
    """Return lots of information on stock items in the list."""
    if len(stockid_list)==0: return []
    cur=cursor()
    # Q: Does psycopg2 deal with lists?
    # A: lists are turned into ARRAY types.  Tuples are turned into
    # something suitable for the IN operator.  The documentation says
    # that empty tuples are not supported so must be guarded against
    # (already done, above).  The psycopg2.extensions module MUST be
    # imported to register support for this.
    cur.execute("SELECT * FROM stockinfo WHERE stockid IN %s",
                (tuple(stockid_list),))
    r=cur.fetchall()
    # Q: This is a real candidate for returning a dict! Does pgdb support it?
    # A: not explicitly, but we can do something like:
    cn=[x[0] for x in cur.description]
    from . import stock
    def mkdict(r):
        d={}
        for i in cn:
            d[i]=r[0]
            r=r[1:]
        d['abvstr']=stock.abvstr(d['abv'])
        if d['used'] is None: d['used']=Decimal("0.0")
        d['remaining']=d['size']-d['used']
        return d
    # At this point we have a list of results, but that list is not
    # necessarily in the order of the input list.  We must sort it
    # into the appropriate order.  Note that we may have been passed
    # stockids that do not exist!
    sid={}
    for i in r:
        sid[i[0]]=mkdict(i)
    return [sid[x] for x in stockid_list if x in sid]

def stock_checkpullthru(stockid,maxtime):
    """Did this stock item require pulling through?"""
    cur=cursor()
    r=execone(cur,"SELECT now()-max(stockout.time)>%s FROM stockout "
              "WHERE stockid=%s AND removecode IN ('sold','pullthru')",
              (maxtime,stockid))
    if r is None: r=False
    return r

def stock_search(dept=None,exclude_stock_on_sale=True,
                 finished_stock_only=False,stockline=None,stocktype=None):
    """Return a list of stock numbers that fit the criteria."""
    cur=cursor()
    if stockline is None:
        order="s.stockid"
    else:
        order="(s.stocktype IN (SELECT stocktype FROM stockline_stocktype_log stl WHERE stl.stocklineid=%d)) DESC,s.stockid"%stockline
    if dept is None:
        deptq=""
    else:
        deptq="AND st.dept=%d"%dept
    if exclude_stock_on_sale:
        sosq="AND s.stockid NOT IN (SELECT stockid FROM stockonsale)"
    else:
        sosq=""
    if finished_stock_only:
        finq="not null"
    else:
        finq="null"
    if stocktype:
        stq="AND s.stocktype=%d"%stocktype
    else:
        stq=""
    cur.execute("SELECT s.stockid FROM stock s INNER JOIN deliveries d ON "
                "s.deliveryid=d.deliveryid INNER JOIN stocktypes st ON "
                "st.stocktype=s.stocktype "
                "WHERE finishcode is %s AND "
                "d.checked=true %s %s %s ORDER BY %s"%(
            finq,sosq,deptq,stq,order))
    return [x[0] for x in cur.fetchall()]

def stock_putonsale(stockid,stocklineid):
    """Connect a stock item to a particular line.  Additionally, create
    an annotation that records the line name.

    """
    cur=cursor()
    cur.execute("UPDATE stock SET onsale=now() WHERE stockid=%s",(stockid,))
    cur.execute("INSERT INTO stockonsale (stocklineid,stockid) VALUES "
                "(%s,%s)",(stocklineid,stockid))
    cur.execute("INSERT INTO stock_annotations (stockid,atype,text) "
                "SELECT %s,'start',(SELECT name FROM stocklines "
                "WHERE stocklineid=%s)",(stockid,stocklineid))
    commit()
    return True

def stock_autoallocate_candidates(deliveryid=None):
    """
    Return a list of (stockline,stockid,displayqty) tuples, ordered
    by stockid.  List is suitable for passing to stock_allocate() once
    duplicate stockids have been resolved.

    """
    cur=cursor()
    ds="AND deliveryid=%s"%deliveryid if deliveryid is not None else ""
    cur.execute(
        "SELECT sl.stocklineid,si.stockid,si.used AS displayqty "
        "FROM (SELECT * FROM stocklines WHERE capacity IS NOT NULL) AS sl "
        "CROSS JOIN (SELECT * FROM stockinfo WHERE deliverychecked "
        "AND finished IS NULL %s AND stockid NOT IN ( "
        "SELECT stockid FROM stockonsale)) AS si "
        "WHERE si.stocktype IN "
        "(SELECT stocktype FROM stockline_stocktype_log ssl "
        "WHERE ssl.stocklineid=sl.stocklineid) "
        "ORDER BY si.stockid"%ds)
    return cur.fetchall()

def stock_allocate(aal):
    """
    Allocate stock to stocklines; expects a list of
    (stockline,stockid,displayqty) tuples, as produced by
    stock_autoallocate_candidates() and then filtered for duplicate
    stockids.

    """
    cur=cursor()
    for i in aal:
        cur.execute("INSERT INTO stockonsale VALUES (%s,%s,%s)",i)
    commit()

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

def stock_onsale(line):
    """Find out what's on sale on a particular [beer] line.  This function
    returns a list of all the stock items allocated to the line, in order
    of best before date and then stock number, earliest dates/lowest numbers
    first.

    """
    cur=cursor()
    cur.execute(
        "SELECT sos.stockid,sos.displayqty "
        "FROM stockonsale sos "
        "LEFT JOIN stock s ON s.stockid=sos.stockid "
        "WHERE sos.stocklineid=%s "
        "ORDER BY coalesce(sos.displayqty,0) DESC,"
        "s.bestbefore,sos.stockid",(line,))
    return cur.fetchall()

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

def stockline_restock(stocklineid,changes):
    cur=cursor()
    for sd,move,newdisplayqty,stockqty_after_move in changes:
        cur.execute("UPDATE stockonsale SET displayqty=%s WHERE "
                    "stocklineid=%s AND stockid=%s",(
            newdisplayqty,stocklineid,sd['stockid']))
    commit()

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
