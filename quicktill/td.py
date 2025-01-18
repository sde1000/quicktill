# This module originally contained all the SQL needed to access the
# database - the name was an acronym for "Table Definitions".  Now all
# of the database structure and almost all of the methods for
# accessing it are declared in the models module.

from sqlalchemy import create_engine
from sqlalchemy.pool import Pool
from sqlalchemy import event, exc
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import scoped_session
from sqlalchemy.sql.expression import func
from sqlalchemy.sql import select
import threading
from . import models
from .models import (
    StockType,
    StockOut,
    foodorder_seq,
)

import logging
log = logging.getLogger(__name__)

engine = None


class NoDatabase(Exception):
    """Attempt to use database before it's initialised
    """
    pass


class fake_session:
    def query(self, *args, **kwargs):
        raise NoDatabase()

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass

    def remove(self):
        pass


# ORM session; although this is a scoped_session it should only be
# accessed within a "with orm_session()" block
s = fake_session()
_s_guard = threading.local()


class SessionLifecycleError(Exception):
    pass


class orm_session:
    @staticmethod
    def __enter__():
        """Start a database session
        """
        # Check / set a variable in thread-local storage regarding
        # whether the session is started yet.  The scoped_session will
        # start one automatically if we say it's ok.
        l = _s_guard.__dict__
        session_started = l.get("session_started", False)
        if session_started:
            raise SessionLifecycleError()
        log.debug("Start session")
        l["session_started"] = True

    @staticmethod
    def __exit__(type, value, traceback):
        """Finish a database session
        """
        # Check/set the flag in thread-local storage.  Commit or
        # rollback the session; the scoped_session will make sure
        # we're operating on the correct one.  At the end, call
        # remove() on the scoped_session.
        l = _s_guard.__dict__
        session_started = l.get("session_started", False)
        if not session_started:
            raise SessionLifecycleError()
        if value is None:
            s.commit()
        else:
            # An exception happened - roll back the database session
            log.debug("Session rollback")
            s.rollback()
        s.remove()
        log.debug("End session")
        l["session_started"] = False


# Functions related to the stocktypes table

def stocktype_completemanufacturer(m):
    result = s.execute(
        select(StockType.manufacturer)
        .where(StockType.manufacturer.ilike(m + '%'))
        .group_by(StockType.manufacturer)
        .order_by(func.length(StockType.manufacturer), StockType.manufacturer)
    )
    return [x[0] for x in result]


def stocktype_completename(m, n):
    result = s.execute(
        select(StockType.name)
        .where(StockType.manufacturer == m)
        .where(StockType.name.ilike(n + '%'))
        .group_by(StockType.name)
        .order_by(func.length(StockType.name), StockType.name)
    )
    return [x[0] for x in result]


# Functions related to the stock,stockout tables

def stock_checkpullthru(stockid, maxtime):
    """Did this stock item require pulling through?"""
    return s.execute(
        select(func.now() - func.max(StockOut.time) > maxtime)
        .where(StockOut.stockid == stockid)
        .where(StockOut.removecode_id.in_(['sold', 'pullthru']))
    ).scalar()


def foodorder_reset():
    # XXX SQLAlchemy 2.0 will require engine to be passed explicitly
    foodorder_seq.drop()
    foodorder_seq.create()


def foodorder_ticket():
    return s.execute(select(foodorder_seq.next_value())).scalar()


def db_version():
    # XXX needs update for SQLAlchemy 2.0
    return s.execute("select version()").scalar()


# This is "pessimistic disconnect handling" as described in the
# sqlalchemy documentation.  A "ping" select is issued on every
# connection checkout before the connection is used, and a failure of
# the ping causes a reconnection.  This enables the till software to
# keep running even after a database restart.
@event.listens_for(Pool, "checkout")
def ping_connection(dbapi_connection, connection_record, connection_proxy):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("SELECT 1")
    except Exception:
        raise exc.DisconnectionError()
    cursor.close()


def libpq_to_sqlalchemy(database):
    """Create a sqlalchemy engine URL from a libpq connection string
    """
    csdict = dict([x.split('=', 1) for x in database.split(' ')])
    estring = "postgresql+psycopg2://"
    if 'user' in csdict:
        estring += csdict['user']
        if 'password' in csdict:
            estring += f":{csdict['password']}"
        estring += '@'
    if 'host' in csdict:
        estring += csdict['host']
    if 'port' in csdict:
        estring += f":{csdict['port']}"
    estring += f"/{csdict['dbname']}"
    return estring


def parse_database_name(database):
    if database[0] == ":":
        database = f"dbname={database[1:]}"
    if '://' not in database:
        if '=' not in database:
            database = f"dbname={database}"
        database = libpq_to_sqlalchemy(database)
    return database


def init(database):
    """Initialise the database subsystem.

    database can be a libpq connection string or a sqlalchemy URL

    """
    global s, engine
    log.info("init database \'%s\'", database)
    database = parse_database_name(database)
    log.info("sqlalchemy engine URL \'%s\'", database)
    engine = create_engine(database)
    # XXX no longer supported in SQLAlchemy 2.0; pass engine to
    # create_all() etc. instead
    models.metadata.bind = engine  # for DDL, eg. to recreate foodorder_seq
    session_factory = sessionmaker(bind=engine)
    s = scoped_session(session_factory)


def create_tables():
    """Add any database tables that are missing.

    NB does not update tables that don't match our model!
    """
    models.metadata.create_all()


def remove_tables():
    """Removes all our database tables.
    """
    models.metadata.drop_all()
