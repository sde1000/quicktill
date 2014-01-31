# Till database handling routines

# Various parts of the UI call on these routines to work out what the
# hell is going on.  We try to ensure the database constraints are
# never broken here, but that's not really a substitute for
# implementing them in the database itself.

import datetime

from sqlalchemy import create_engine
from sqlalchemy.pool import Pool
from sqlalchemy import event,exc
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
log=logging.getLogger(__name__)

# ORM session; most database access will go through this
s=None
# Sessionmaker, set up during init()
sm=None
class SessionLifecycleError(Exception):
    pass
class orm_session(object):
    @staticmethod
    def __enter__():
        """
        Change td.s from None to an active session object, or raise an
        exception if td.s is not None.
        
        """
        global s,sm
        if s is not None: raise SessionLifecycleError()
        s=sm()
        log.debug("Start session")
    @staticmethod
    def __exit__(type,value,traceback):
        """
        Change td.s from an active session object to None, or raise an
        exception if td.s is already None.  Calls s.close().
        
        """
        global s
        if s is None: raise SessionLifecycleError()
        if value is None:
            s.commit()
        else:
            # An exception happened - roll back the database session
            log.debug("Session rollback")
            s.rollback()
        s.close()
        s=None
        log.debug("End session")

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

### Functions related to the stock,stockout tables

def stock_checkpullthru(stockid,maxtime):
    """Did this stock item require pulling through?"""
    global s
    return s.execute(
        select([func.now()-func.max(StockOut.time)>maxtime]).\
            where(StockOut.stockid==stockid).\
            where(StockOut.removecode_id.in_(['sold','pullthru']))
        ).scalar()

def stock_purge():
    """Stock items that have been completely used up through the
    display mechanism should be marked as 'finished' in the stock
    table, and disconnected from the stockline.  This is usually
    done automatically at the end of each session because stock items
    may be put back on display through the voiding mechanism during
    the session, but is also available as an option on the till
    management menu.

    """
    global s
    # Find stockonsale that is ready for purging: used==size on a
    # stockline that has a display capacity
    finished=s.query(StockItem).\
        join(StockLine).\
        filter(not_(StockLine.capacity==None)).\
        filter(StockItem.remaining==0.0).\
        all()

    # Mark all these stockitems as finished, removing them from being
    # on sale as we go
    for item in finished:
        item.finished=datetime.datetime.now()
        item.finishcode_id='empty' # guaranteed to exist
        item.displayqty=None
        item.stocklineid=None
    s.flush()

def foodorder_reset():
    foodorder_seq.drop()
    foodorder_seq.create()

def foodorder_ticket():
    global s
    return s.execute(select([foodorder_seq.next_value()])).scalar()

def db_version():
    global s
    return s.execute("select version()").scalar()

# This is "pessimistic disconnect handling" as described in the
# sqlalchemy documentation.  A "ping" select is issued on every
# connection checkout before the connection is used, and a failure of
# the ping causes a reconnection.  This enables the till software to
# keep running even after a database restart.
@event.listens_for(Pool, "checkout")
def ping_connection(dbapi_connection, connection_record, connection_proxy):
    cursor=dbapi_connection.cursor()
    try:
        cursor.execute("SELECT 1")
    except:
        raise exc.DisconnectionError()
    cursor.close()

def libpq_to_sqlalchemy(database):
    """
    Create a sqlalchemy engine URL from a libpq connection string

    """
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
    return estring

def init(database):
    """
    Initialise the database subsystem.

    database can be a libpq connection string or a sqlalchemy URL

    """
    global sm
    log.info("init database \'%s\'",database)
    if database[0]==":":
        database="dbname=%s"%database[1:]

    if '://' not in database: database=libpq_to_sqlalchemy(database)

    log.info("sqlalchemy engine URL \'%s\'",database)
    engine=create_engine(database)
    models.metadata.bind=engine # for DDL, eg. to recreate foodorder_seq
    sm=sessionmaker(bind=engine)

def create_tables():
    """
    Adds any database tables that are missing.  NB does not update
    tables that don't match our model!

    """
    models.metadata.create_all()

def remove_tables():
    """
    Removes all our database tables.

    """
    models.metadata.drop_all()
