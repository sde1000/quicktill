# This module originally contained all the SQL needed to access the
# database - the name was an acronym for "Table Definitions".  Now all
# of the database structure and almost all of the methods for
# accessing it are declared in the models module.

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.pool import Pool
from sqlalchemy import event, exc
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import scoped_session
from sqlalchemy.sql.expression import func
from sqlalchemy.sql import select
import threading
import sys
from . import models
from .models import (
    StockType,
    StockOut,
    foodorder_seq,
)

import logging
log = logging.getLogger(__name__)

engine = None
_configured_databases = {}


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
    foodorder_seq.drop(engine)
    foodorder_seq.create(engine)


def foodorder_ticket():
    return s.execute(select(foodorder_seq.next_value())).scalar()


def db_version():
    return s.execute(select(func.version())).scalar()


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


def dict_to_sqlalchemy(csdict, source):
    allowable_keys = ('user', 'password', 'host', 'port', 'dbname')
    bad_keys = set(csdict.keys()) - set(allowable_keys)
    if bad_keys:
        print(f"Unrecognised database connection details in {source}:",
              file=sys.stderr)
        for k in bad_keys:
            print(f"  - {k} = {csdict[k]}", file=sys.stderr)
        print(f"Allowable keys are: {', '.join(allowable_keys)}",
              file=sys.stderr)
        print("Or supply a sqlalchemy engine URL")
        sys.exit(1)

    return URL.create(
        "postgresql+psycopg2",
        username=csdict.get('user'),
        password=csdict.get('password'),
        host=csdict.get('host'),
        port=int(csdict.get('port')) if 'port' in csdict else None,
        database=csdict.get('dbname'))


def libpq_to_sqlalchemy(database, source):
    """Create a sqlalchemy engine URL from a libpq connection string
    """
    return dict_to_sqlalchemy(
        dict([x.split('=', 1) for x in database.split(' ')]), source)


def parse_database_name(database):
    """Parse database connection details

    Output a sqlalchemy engine URL for the database. The input can be
    a sqlalchemy engine url, libpq connection string, or the name of
    a database defined in the global configuration file.
    """
    if database[0] == ":":
        database = f"dbname={database[1:]}"
    if '://' not in database:
        if '=' in database:
            database = libpq_to_sqlalchemy(
                database, "site config or on command line")
        else:
            # Look up in configuration file
            if database in _configured_databases:
                database = _configured_databases[database]
            else:
                print(f"Database '{database}' not defined in configuration",
                      file=sys.stderr)
                sys.exit(1)
    return database


def register_databases(configfile, databases):
    for name, details in databases.items():
        if 'sqlalchemy_url' in details:
            conf = details['sqlalchemy_url']
        else:
            conf = dict_to_sqlalchemy(details, configfile)
        _configured_databases[name] = conf


def init(database):
    """Initialise the database subsystem.

    database can be a libpq connection string or a sqlalchemy URL

    """
    global s, engine
    log.info("init database \'%s\'", database)
    database = parse_database_name(database)
    log.info("sqlalchemy engine URL \'%s\'", database)
    engine = create_engine(database, future=True)
    session_factory = sessionmaker(bind=engine, future=True)
    s = scoped_session(session_factory)


def create_tables():
    """Add any database tables that are missing.

    NB does not update tables that don't match our model!
    """
    models.metadata.create_all(engine)


def remove_tables():
    """Removes all our database tables.
    """
    models.metadata.drop_all(engine)
