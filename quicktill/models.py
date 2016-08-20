from __future__ import unicode_literals
from __future__ import division

from sqlalchemy.ext.declarative import declarative_base,declared_attr
from sqlalchemy import Column,Integer,String,DateTime,Date,ForeignKey,Numeric,CHAR,Boolean,Text
from sqlalchemy.schema import Sequence,Index,MetaData,DDL,CheckConstraint,Table
from sqlalchemy.sql.expression import text,alias
from sqlalchemy.orm import relationship,backref,object_session,sessionmaker
from sqlalchemy.orm import subqueryload_all,joinedload,subqueryload,lazyload
from sqlalchemy.orm import contains_eager,column_property
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql import select,func,desc,and_
from sqlalchemy import event

import datetime
import hashlib
from decimal import Decimal

# Used for quantization of money
zero = Decimal("0.00")
penny = Decimal("0.01")

# Common column types
money = Numeric(10, 2)
quantity = Numeric(8, 1)

metadata = MetaData()

class _unistr(object):
    def __str__(self):
        return str(self.__unicode__())

Base = declarative_base(metadata=metadata, cls=_unistr)

# Rules that depend on the existence of more than one table must be
# added to the metadata rather than the table - they will be created
# after all tables, and dropped before any tables.
def add_ddl(target, create, drop):
    """Add DDL explicitly

    Convenience function to add CREATE and DROP statements for
    postgresql database rules; can also be used to create nonstandard
    indexes.
    """
    if create:
        event.listen(target, "after_create",
                     DDL(create).execute_if(dialect='postgresql'))
    if drop:
        event.listen(target, "before_drop",
                     DDL(drop).execute_if(dialect='postgresql'))

class Business(Base):
    __tablename__ = 'businesses'
    id = Column('business', Integer, primary_key=True, autoincrement=False)
    name = Column(String(80), nullable=False)
    abbrev = Column(String(20), nullable=False)
    address = Column(String(), nullable=False)
    vatno = Column(String(30))
    show_vat_breakdown = Column(Boolean(),nullable=False,default=False)
    def __unicode__(self):
        return "%s" % (self.abbrev,)
    def __repr__(self):
        return "<Business('%s')>" % (self.name,)

# This is intended to be a mixin for both VatBand and VatRate.  It's
# not intended to be instantiated.
class Vat(object):
    @declared_attr
    def rate(cls):
        return Column(Numeric(5, 2), nullable=False)
    @declared_attr
    def businessid(cls):
        return Column('business', Integer, ForeignKey('businesses.business'),
                      nullable=False)
    @property
    def rate_fraction(self):
        return self.rate / Decimal(100)
    def inc_to_exc(self, n):
        return (n / (self.rate_fraction + Decimal(1))).quantize(penny)
    def inc_to_vat(self, n):
        return n - self.inc_to_exc(n)
    def exc_to_vat(self, n):
        return (n * self.rate_fraction).quantize(penny)
    def exc_to_inc(self, n):
        return n + self.exc_to_vat(n)
    def at(self, date):
        """VatRate at specified date

        Return the VatRate object that replaces this one at the
        specified date.  If there is no suitable VatRate object,
        returns self.
        """
        return object_session(self).\
            query(VatRate).\
            filter_by(band=self.band).\
            filter(VatRate.active <= date).\
            order_by(desc(VatRate.active)).\
            first() or self
    @property
    def current(self):
        """VatRate at current date

        Return the VatRate object that replaces this one at the
        current date.  If there is no suitable VatRate object, returns
        self.
        """
        return self.at(datetime.datetime.now())

class VatBand(Base, Vat):
    __tablename__ = 'vat'
    band = Column(CHAR(1), primary_key=True)
    business = relationship(Business, backref='vatbands')
    def __repr__(self):
        return "<VatBand('%s')>" % (self.band,)

# Note that the tillweb index page code ignores the 'business' field
# in VatRate and only uses VatBand.  Until this is fixed you should
# not use a VatRate entry to change the business for a VatBand -
# create a new department instead.
class VatRate(Base, Vat):
    __tablename__ = 'vatrates'
    band = Column(CHAR(1), ForeignKey('vat.band'), primary_key=True)
    active = Column(Date, nullable=False, primary_key=True)
    business = relationship(Business, backref='vatrates')
    def __repr__(self):
        return "<VatRate('%s',%s,'%s')>" % (self.band, self.rate, self.active)

class PayType(Base):
    __tablename__ = 'paytypes'
    paytype = Column(String(8), nullable=False, primary_key=True)
    description = Column(String(10), nullable=False)
    def __unicode__(self):
        return "%s" % (self.description,)
    def __repr__(self):
        return "<PayType('%s')>" % (self.paytype,)

sessions_seq = Sequence('sessions_seq')

class Session(Base):
    """A group of transactions with an accounting date

    As well as a start and end time, sessions have an accounting date.
    This is to cope with sessions being closed late (eg. subsequent
    date) or started early.  In the accounts, the session takings will
    be recorded against the session date.
    """
    __tablename__ = 'sessions'

    id = Column('sessionid', Integer, sessions_seq, primary_key=True)
    starttime = Column(DateTime, nullable=False)
    endtime = Column(DateTime)
    date = Column('sessiondate', Date, nullable=False)

    def __init__(self, date):
        self.date=date
        self.starttime = datetime.datetime.now()

    def __repr__(self):
        return "<Session(%s,'%s')>" % (self.id, self.date,)
    def __unicode__(self):
        return "Session %d" % self.id
    @property
    def tillweb_url(self):
        return "session/%d/" % self.id
    incomplete_transactions = relationship(
        "Transaction",
        primaryjoin="and_(Transaction.sessionid==Session.id,Transaction.closed==False)")
    @property
    def dept_totals(self):
        "Transaction lines broken down by Department."
        return object_session(self).\
            query(Department, func.sum(
                Transline.items * Transline.amount)).\
            select_from(Session).\
            filter(Session.id == self.id).\
            join(Transaction, Transline, Department).\
            order_by(Department.id).\
            group_by(Department).all()
    @property
    def dept_totals_closed(self):
        """Transaction lines broken down by Department and closed status.

        Returns list of (Department,total,closed_total,pending_total).
        The list always includes all departments, even if both totals
        are None.
        """
        s = object_session(self)
        tot_all = s.query(func.sum(Transline.items * Transline.amount)).\
                  select_from(Transline.__table__).\
                  join(Transaction).\
                  filter(Transaction.sessionid == self.id).\
                  filter(Transline.dept_id == Department.id)
        tot_closed = tot_all.filter(Transaction.closed)
        totals = object_session(self).\
                 query(Department,
                       tot_all.label("total"),
                       tot_closed.label("closed")).\
                       order_by(Department.id).\
                       group_by(Department).all()
        return [(d, t, c, (t or zero) - (c or zero)) for d, t, c in totals]
    @property
    def user_totals(self):
        "Transaction lines broken down by User; also count of items sold."
        return object_session(self).\
            query(User, func.sum(Transline.items), func.sum(
                Transline.items*Transline.amount)).\
            filter(Transaction.sessionid == self.id).\
            join(Transline, Transaction).\
            order_by(desc(func.sum(
                Transline.items * Transline.amount))).\
            group_by(User).all()
    @property
    def payment_totals(self):
        "Transactions broken down by payment type."
        return object_session(self).\
            query(PayType, func.sum(Payment.amount)).\
            select_from(Session).\
            filter(Session.id == self.id).\
            join(Transaction, Payment, PayType).\
            group_by(PayType).all()
    # total and closed_total are declared after Transline
    # actual_total is declared after SessionTotal
    @property
    def pending_total(self):
        "Total of open transactions"
        return self.total - self.closed_total
    @property
    def error(self):
        "Difference between actual total and transaction line total."
        return self.actual_total - self.total
    @property
    def vatband_totals(self):
        """Transaction lines broken down by VatBand.

        Returns (VatRate, amount, ex-vat amount, vat)
        """
        vt = object_session(self).\
            query(VatBand, func.sum(Transline.items * Transline.amount)).\
            select_from(Session).\
            filter(Session.id == self.id).\
            join(Transaction, Transline, Department, VatBand).\
            order_by(VatBand.band).\
            group_by(VatBand).\
            all()
        vt=[(a.at(self.date), b) for a, b in vt]
        return [(a, b, a.inc_to_exc(b), a.inc_to_vat(b)) for a, b in vt]
    # It may become necessary to add a further query here that returns
    # transaction lines broken down by Business.  Must take into
    # account multiple VAT rates per business - probably best to do
    # the summing client side using the methods in the VatRate object.
    @property
    def stock_sold(self):
        "Returns a list of (StockType, quantity) tuples."
        return object_session(self).\
            query(StockType, func.sum(StockOut.qty)).\
            join(UnitType).\
            join(StockItem).\
            join(StockOut).\
            join(Transline).\
            join(Transaction).\
            filter(Transaction.sessionid == self.id).\
            options(lazyload(StockType.department)).\
            options(contains_eager(StockType.unit)).\
            group_by(StockType, UnitType).\
            order_by(StockType.dept_id, desc(func.sum(StockOut.qty))).\
            all()
    @classmethod
    def current(cls, session):
        """Current session

        Return the currently open session, or None if no session is
        open.  Must be passed a suitable sqlalchemy session in which
        to run the query.
        """
        return session.query(Session).filter_by(endtime=None).first()

add_ddl(Session.__table__, """
CREATE OR REPLACE FUNCTION check_max_one_session_open() RETURNS trigger AS $$
BEGIN
  IF (SELECT count(*) FROM sessions WHERE endtime IS NULL)>1 THEN
    RAISE EXCEPTION 'there is already an open session';
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;
CREATE CONSTRAINT TRIGGER max_one_session_open
  AFTER INSERT OR UPDATE ON sessions
  FOR EACH ROW EXECUTE PROCEDURE check_max_one_session_open();
""", """
DROP TRIGGER max_one_session_open ON sessions;
DROP FUNCTION check_max_one_session_open();
""")

class SessionTotal(Base):
    __tablename__ = 'sessiontotals'
    sessionid = Column(Integer, ForeignKey('sessions.sessionid'),
                       primary_key=True)
    paytype_id = Column('paytype', String(8), ForeignKey('paytypes.paytype'),
                      primary_key=True)
    amount = Column(money, nullable=False)
    session = relationship(Session, backref=backref(
        'actual_totals', order_by=desc('paytype')))
    paytype = relationship(PayType)
    def __repr__(self):
        return "<SessionTotal(%s,'%s','%s')>" % (
            self.sessionid, self.paytype, self.amount)

Session.actual_total = column_property(
    select([func.sum(SessionTotal.amount)],
           whereclause=and_(SessionTotal.sessionid == Session.id)).\
        correlate(Session.__table__).\
        label('actual_total'),
    deferred=True,
    doc="Actual recorded total")

transactions_seq = Sequence('transactions_seq')

class Transaction(Base):
    __tablename__ = 'transactions'
    id = Column('transid', Integer, transactions_seq, nullable=False,
                primary_key=True)
    sessionid = Column(Integer, ForeignKey('sessions.sessionid'),
                       nullable=True) # Null sessionid for deferred transactions
    notes = Column(String(60), nullable=False, default='')
    closed = Column(Boolean, nullable=False, default=False)
    session = relationship(Session, backref=backref('transactions', order_by=id))
    # total is a column property defined below
    @hybrid_property
    def payments_total(self):
        """Payments total
        """
        return sum((p.amount for p in self.payments), zero)
    def payments_summary(self):
        """List of (paytype, amount) tuples.
        """
        pts={}
        for p in self.payments:
            pts[p.paytype] = pts.get(p.paytype, zero) + p.amount
        return list(pts.items())
    @property
    def balance(self):
        """Transaction balance
        """
        return self.total - self.payments_total
    @property
    def tillweb_url(self):
        return "transaction/%d/" % self.id
    @property
    def age(self):
        """How old is the transaction?

        The age of the transaction's oldest line in days, or zero if
        the transaction has no lines.
        """
        if len(self.lines) == 0:
            return 0
        first = min(tl.time for tl in self.lines)
        age = datetime.datetime.now() - first
        return age.days
    def __unicode__(self):
        return "Transaction %d" % self.id
    def __repr__(self):
        return "<Transaction(%s,%s,%s)>" % (self.id, self.sessionid, self.closed)

add_ddl(Transaction.__table__, """
CREATE OR REPLACE FUNCTION check_transaction_balances() RETURNS trigger AS $$
BEGIN
  IF NEW.closed=true
    AND (SELECT sum(amount*items) FROM translines
      WHERE transid=NEW.transid)!=
      (SELECT sum(amount) FROM payments WHERE transid=NEW.transid)
  THEN RAISE EXCEPTION 'transaction %% does not balance', NEW.transid;
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;
CREATE CONSTRAINT TRIGGER close_only_if_balanced
  AFTER INSERT OR UPDATE ON transactions
  FOR EACH ROW EXECUTE PROCEDURE check_transaction_balances();
""", """
DROP TRIGGER close_only_if_balanced ON transactions;
DROP FUNCTION check_transaction_balances();
""")

user_seq = Sequence('user_seq')

class User(Base):
    """A till user.

    When the web-based admin system is in use, the web server may
    supply a username which can be correlated to 'webuser' here.  This
    is optional.
    """
    __tablename__ = 'users'
    id = Column(Integer, user_seq, nullable=False, primary_key=True)
    fullname = Column(String(), nullable=False, doc="Full name of the user")
    shortname = Column(String(), nullable=False,
                       doc="Abbreviated name of the user")
    webuser = Column(String(), nullable=True, unique=True,
                     doc="Username of this user on the web-based admin system")
    enabled = Column(Boolean, nullable=False, default=False)
    superuser = Column(Boolean, nullable=False, default=False)
    trans_id = Column('transid', Integer, ForeignKey('transactions.transid',
                                                     ondelete='SET NULL'),
                      nullable=True, unique=True,
                      doc="Transaction being worked on by this user")
    register = Column(String(), nullable=True,
                      doc="Terminal most recently used by this user")
    message = Column(String(), nullable=True,
                     doc="Message to present to user on their next keypress")
    permissions = relationship("Permission", secondary="permission_grants",
                               backref="users")
    transaction = relationship(Transaction, backref=backref(
        'user', uselist=False))
    @property
    def tillweb_url(self):
        return "user/{}/".format(self.id)
    def __repr__(self):
        return "<User({0.id},'{0.fullname}')>".format(self)

class UserToken(Base):
    """A token used by a till user to identify themselves

    These will typically be NFC cards or iButton tags.  This table
    aims to be technology-neutral.
    """
    __tablename__ = 'usertokens'
    token = Column(String(), primary_key=True)
    authdata = Column(String(), nullable=True)
    description = Column(String())
    user_id = Column('user', Integer, ForeignKey('users.id'), nullable=False)
    last_seen = Column(DateTime)
    user = relationship(User, backref='tokens')

class Permission(Base):
    """Permission to do something

    Permission to perform an operation on the till or on the web
    interface.  Permissions are identified by name; the description
    here is just for convenience.  Permissions are defined in the code
    and a record is created here the first time the permission is
    referred to.  Permissions may also be groups; the list of
    permissions held by a group is defined in the till configuration
    file.
    """
    __tablename__ = 'permissions'
    id = Column(String(), nullable=False, primary_key=True,
                doc="Name of the permission")
    description = Column(String(), nullable=False,
                         doc="Brief description of the permission")

# There is no need to access this table directly; it is handled through
# the relationships on User and Permission.
permission_association_table = Table(
    'permission_grants', Base.metadata,
    Column('user', Integer, ForeignKey('users.id'), primary_key=True),
    Column('permission', String(), ForeignKey('permissions.id'),
           primary_key=True))

payments_seq = Sequence('payments_seq', start=1)

class Payment(Base):
    __tablename__ = 'payments'
    id = Column('paymentid', Integer, payments_seq, nullable=False,
                primary_key=True)
    transid = Column(Integer, ForeignKey('transactions.transid'),
                     nullable=False)
    amount = Column(money, nullable=False)
    paytype_id = Column('paytype', String(8), ForeignKey('paytypes.paytype'),
                        nullable=False)
    ref = Column(String())
    time = Column(DateTime, nullable=False,
                  server_default=func.current_timestamp())
    user_id = Column('user', Integer, ForeignKey('users.id'), nullable=True,
                     doc="User who created this payment")
    transaction = relationship(Transaction,
                               backref=backref('payments', order_by=id))
    paytype = relationship(PayType)
    user = relationship(User)
    def __repr__(self):
        return "<Payment(%s,%s,%s,'%s')>" % (
            self.id, self.transid, self.amount, self.paytype_id)

add_ddl(Payment.__table__, """
CREATE OR REPLACE FUNCTION check_modify_closed_trans_payment() RETURNS trigger AS $$
BEGIN
  IF (SELECT closed FROM transactions WHERE transid=NEW.transid)=true
  THEN RAISE EXCEPTION 'attempt to modify closed transaction %% payment', NEW.transid;
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;
CREATE CONSTRAINT TRIGGER no_modify_closed
  AFTER INSERT OR UPDATE ON payments
  FOR EACH ROW EXECUTE PROCEDURE check_modify_closed_trans_payment();
""", """
DROP TRIGGER no_modify_closed ON payments;
DROP FUNCTION check_modify_closed_trans_payment();
""")

class Department(Base):
    __tablename__ = 'departments'
    id = Column('dept', Integer, nullable=False, primary_key=True,
                autoincrement=False)
    description = Column(String(20), nullable=False)
    vatband = Column(CHAR(1), ForeignKey('vat.band'), nullable=False)
    notes = Column(Text, nullable=True, doc="Information on this department "
                   "for printing on price lists.")
    minprice = Column(money, nullable=True, doc="Minimum price of a "
                      "single item in this department.")
    maxprice = Column(money, nullable=True, doc="Maximum price of a "
                      "single item in this department.")
    accinfo = Column(String(), nullable=True, doc="Accounting system info")
    vat = relationship(VatBand)
    def __unicode__(self):
        return "%s" % (self.description,)
    def __repr__(self):
        return "<Department(%s,'%s')>" % (self.id, self.description)
    @property
    def tillweb_url(self):
        return "department/{}/".format(self.id)

class TransCode(Base):
    __tablename__ = 'transcodes'
    code = Column('transcode', CHAR(1), nullable=False, primary_key=True)
    description = Column(String(20), nullable=False)
    def __unicode__(self):
        return "%s" % (self.description,)
    def __repr__(self):
        return "<TransCode('%s','%s')>" % (self.code, self.description)

translines_seq = Sequence('translines_seq', start=1)

class Transline(Base):
    __tablename__ = 'translines'
    id = Column('translineid', Integer, translines_seq, nullable=False,
                primary_key=True)
    transid = Column(Integer, ForeignKey('transactions.transid'),
                     nullable=False)
    items = Column(Integer, nullable=False)
    amount = Column(money, nullable=False)
    dept_id = Column('dept', Integer, ForeignKey('departments.dept'),
                     nullable=False)
    user_id = Column('user', Integer, ForeignKey('users.id'), nullable=True,
                     doc="User who created this transaction line")
    transcode = Column(CHAR(1), ForeignKey('transcodes.transcode'),
                       nullable=False)
    time = Column(DateTime, nullable=False,
                  server_default=func.current_timestamp())
    text = Column(Text)
    transaction = relationship(Transaction,
                               backref=backref('lines', order_by=id))
    department = relationship(Department)
    user = relationship(User)
    @hybrid_property
    def total(self):
        return self.items * self.amount
    def __repr__(self):
        return "<Transline(%s,%s)>" % (self.id, self.transid)
    @property
    def tillweb_url(self):
        return "transline/{}/".format(self.id)
    @property
    def description(self):
        if self.text is not None:
            return self.text
        # If there is more than one entry in stockref then the text
        # field should already have been filled in.
        if self.stockref and len(self.stockref) == 1:
            stockout = self.stockref[0]
            qty = stockout.qty / self.items
            unitname = stockout.stockitem.stocktype.unit.name
            # The following section is for legacy databases that do not have
            # self.text filled in on old transactions.
            qty = Decimal(qty).quantize(Decimal("0.1"))
            if qty == Decimal("1.0"):
                qtys = unitname
            elif qty == Decimal("0.5"):
                qtys = "half %s" % unitname
            else:
                qtys = "%s %s" % (qty, unitname)
            if qtys == '4.0 pint':
                qtys = '4pt jug'
            if qtys == '2.0 25ml':
                qtys = 'double 25ml'
            if qtys == '2.0 50ml':
                qtys = 'double 50ml'
            return "%s %s" % (stockout.stockitem.stocktype.format(), qtys)
        return self.department.description
    def regtotal(self, currency):
        """Formatted version of items and price

        The number of items and price formatted nicely for display in
        the register or on a receipt.
        """
        if self.amount == zero:
            return ""
        if self.items == 1:
            return "%s%s" % (currency, self.amount)
        return "%d @ %s%s = %s%s" % (
            self.items, currency, self.amount, currency,
            self.items * self.amount)

add_ddl(Transline.__table__, """
CREATE FUNCTION check_modify_closed_trans_line() RETURNS trigger AS $$
BEGIN
  IF (SELECT closed FROM transactions WHERE transid=NEW.transid)=true
  THEN RAISE EXCEPTION 'attempt to modify closed transaction %% line', NEW.transid;
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;
CREATE CONSTRAINT TRIGGER no_modify_closed
  AFTER INSERT OR UPDATE ON translines
  FOR EACH ROW EXECUTE PROCEDURE check_modify_closed_trans_line();
""", """
DROP TRIGGER no_modify_closed ON translines;
DROP FUNCTION check_modify_closed_trans_line();
""")

# Add "total" column property to the Session class now that
# transactions and translines are defined
Session.total = column_property(
    select([func.coalesce(func.sum(Transline.items * Transline.amount),
                          text("0.00"))],
           whereclause=and_(Transline.transid == Transaction.id,
                            Transaction.sessionid == Session.id)).\
        correlate(Session.__table__).\
        label('total'),
    deferred=True,
    doc="Transaction lines total")
Session.closed_total = column_property(
    select([func.coalesce(func.sum(Transline.items * Transline.amount),
                          text("0.00"))],
           whereclause=and_(Transline.transid == Transaction.id,
                            Transaction.closed,
                            Transaction.sessionid == Session.id)).\
        correlate(Session.__table__).\
        label('closed_total'),
    deferred=True,
    doc="Transaction lines total, closed transactions only")

# Add "total" column property to the Transaction class now that
# transactions and translines are defined
Transaction.total = column_property(
    select([func.coalesce(func.sum(Transline.items * Transline.amount),
                          text("0.00"))],
           whereclause=and_(Transline.transid == Transaction.id)).\
        correlate(Transaction.__table__).\
        label('total'),
    deferred=True,
    doc="Transaction lines total")

stocklines_seq = Sequence('stocklines_seq', start=100)
class StockLine(Base):
    """A place where stock is sold

    All stock is sold through stocklines.  An item of stock is "on
    sale" if its stocklineid column points to a stockline.  Keyboard
    bindings on the till keyboard can point to stocklines, and
    modifiers specified either explicitly by the till user of
    implicitly in the keyboard binding can alter things like quantity
    and price.

    There are currently three types of stockline:

    1. "Regular" stocklines.  These can have at most one stock item on
    sale at any one time.  Finishing that stock item and putting
    another item on sale are done explicitly by the staff.  They are
    typically used where units are dispensed directly from the stock
    item to the customer and it's obvious to the member of staff when
    the stock item is empty, for example casks/kegs through a pump,
    bottles of spirits, cards or boxes of snacks, and so on.

    If a regular stockline has dept and/or stocktype set then these
    are used to filter the list of stock available to be put on sale.

    If the "pullthru" field is set, then whenever the stock item is
    sold the time of the last use of the item is checked and if it's
    too large then the user is prompted to throw away a quantity of
    stock and record it as waste.

    2. "Display" stocklines.  These can have several stock items on
    sale at once.  Moving from one stock item to the next is
    automatic; when one item is empty the next is used.  These
    stocklines have a "capacity", and the system keeps track of how
    many units of each stock item are "on display" and available to be
    sold; the "capacity" is the number of units that can be on display
    at any one time (for example, in a fridge).  Display stocklines
    are typically used where it isn't obvious to the member of staff
    where one stock item finishes and another one starts; for example,
    the bottles on display in a fridge may come from several different
    stock items.

    Display stocklines must have the stocktype field set; this is used
    to put new items of stock on display automatically.  Stock can
    only be sold through a display stockline in whole numbers of
    units.

    3. "Continuous" stocklines.  These never have any stock items on
    sale.  Instead, when a sale is made the stockline searches for
    stock of the specified type that is not already on sale on another
    stockline, and uses that.  If a particular stock item doesn't have
    enough stock left for the whole sale, multiple stock items are
    used.  Continuous stocklines are typically used where a single
    sale (for example of a glass of wine) can come from multiple stock
    items (eg. where a wine bottle finishes, and the next bottle is
    from a different case).
    """
    __tablename__ = 'stocklines'
    id = Column('stocklineid', Integer, stocklines_seq,
                nullable=False, primary_key=True)
    name = Column(String(30), nullable=False, unique=True,
                  doc="User-visible name of this stockline")
    location = Column(String(20), nullable=False,
                      doc="Used for grouping stocklines together in the UI")
    linetype = Column(String(20), nullable=False,
                      doc="Type of the stockline as a string")
    capacity = Column(Integer, doc='If a "Display" stockline, the number of '
                      'units of stock that can be ready to sell to customers '
                      'at once, for example space in a fridge.')
    dept_id = Column('dept', Integer, ForeignKey('departments.dept'),
                     nullable=True)
    pullthru = Column(quantity, doc='If a "Regular" stockline, the amount '
                      'of stock that should be disposed of the first time the '
                      'stock is sold each day.')
    stocktype_id = Column(
        'stocktype', Integer, ForeignKey('stocktypes.stocktype'), nullable=True)
    department = relationship(
        Department, lazy='joined',
        doc="Stock items put on sale on this line are restricted to this "
        "department.")
    stocktype = relationship(
        "StockType", backref=backref('stocklines', order_by=id),
        doc="Stock items put on sale on this line are restricted to this "
        "stocktype.")
    # capacity and pullthru can't both be non-null at the same time
    __table_args__ = (
        CheckConstraint(
            "linetype='regular' OR linetype='display' OR linetype='continuous'",
            name="linetype_name_constraint"),
        # linetype != 'display' implies capacity is null
        CheckConstraint(
            "NOT(linetype!='display') OR (capacity IS NULL)",
            name="capacity_constraint"),
        # linetype != 'regular' implies pullthru and dept are null
        CheckConstraint(
            "NOT(linetype!='regular') OR (pullthru IS NULL "
            "AND dept IS NULL)",
            name="pullthru_and_dept_constraint"),
        # linetype == 'display' implies capacity and stocktype both not null
        CheckConstraint(
            "NOT(linetype='display') OR (capacity IS NOT NULL "
            "AND stocktype IS NOT NULL)",
            name="linetype_display_constraint"),
        # linetype == 'continuous' implies stocktype not null
        CheckConstraint(
            "NOT(linetype='continuous') OR (stocktype IS NOT NULL)",
            name="linetype_continuous_constraint"),
        )
    @property
    def sale_stocktype(self):
        """Return the type of stock that is currently sold through this
        stockline.
        """
        if self.linetype == "regular":
            if len(self.stockonsale) == 0:
                return None
            return self.stockonsale[0].stocktype
        return self.stocktype
    @property
    def tillweb_url(self):
        return "stockline/%d/" % self.id
    def __repr__(self):
        return "<StockLine(%s,'%s')>" % (self.id, self.name)
    @property
    def ondisplay(self):
        """Number of units of stock on display

        For "Display" stocklines, the total number of units of stock
        on display for sale across all the stock items on sale on this
        line.  For other stocklines, returns None.
        """
        if self.linetype != "display":
            return None
        return sum(sos.ondisplay for sos in self.stockonsale)
    @property
    def instock(self):
        """Number of units of stock available

        For "Display" stocklines, the total number of units of stock
        available to be put on display for sale across all the stock
        items on sale on this line.  For other stocklines, returns
        None.
        """
        if self.linetype != "display":
            return None
        return sum(sos.instock for sos in self.stockonsale)
    @property
    def remaining(self):
        """Amount of unsold stock on the stock line."""
        if self.linetype == "regular":
            if self.stockonsale:
                return self.stockonsale[0].remaining
            else:
                return Decimal("0.0")
        elif self.linetype == "display":
            return self.ondisplay + self.instock
        elif self.linetype == "continuous":
            return self.stocktype.remaining

    def calculate_restock(self, target=None):
        """Prepare list of stock movements

        For "Display" stocklines, calculate the stock movements
        required to set the displayed quantity of this stockline to
        the target (which is the display capacity if not specified as
        an argument).  This function DOES NOT commit the movements to
        the database.  Returns a list of (stockitem, fetchqty,
        newdisplayqty, qtyremain) tuples for the affected stock items.
        For other types of stockline, returns None.
        """
        if self.linetype != "display":
            return None
        target = self.capacity if target is None else target
        sos = list(self.stockonsale) # copy because we may reverse it later
        needed = target - self.ondisplay
        # If needed is negative we need to return some stock!  The list
        # returned via the stockonsale backref is sorted by best before
        # date and delivery date, so if we're returning stock we need to
        # reverse the list to return stock with the latest best before
        # date / latest delivery first.
        if needed < 0:
            sos.reverse()
        sm = []
        for i in sos:
            move = 0
            if needed > 0:
                move = min(needed, i.instock)
            if needed < 0:
                # We can only put back what is already on display!
                move = max(needed, 0 - i.ondisplay)
            needed = needed - move
            newdisplayqty = i.displayqty_or_zero + move
            instock_after_move = int(i.stockunit.size) - newdisplayqty
            if move != 0:
                sm.append((i, move, newdisplayqty, instock_after_move))
        return sm

    def continuous_stockonsale(self):
        return object_session(self)\
            .query(StockItem)\
            .join(Delivery)\
            .filter(Delivery.checked == True)\
            .filter(StockItem.stocktype == self.stocktype)\
            .filter(StockItem.finished == None)\
            .order_by(StockItem.id)\
            .all()

    def calculate_sale(self, qty):
        """Work out a plan to remove a quantity of stock from the stock line.

        They may be sold, wasted, etc. - this is not just for
        calculating a sale!

        Returns (list of (stockitem, qty) pairs, the number of items
        that could not be allocated, remaining stock).  For display
        stocklines the remaining stock is a tuple (ondisplay,
        instock)).

        With display stock lines, only considers the stock that is
        "ondisplay"; will not take from the stock "instock".  On other
        types of stock line, will let the stock go into negative
        amounts "remaining".
        """
        # Reject negative quantities
        if qty < Decimal("0.0"):
            return ([], qty, None)
        if self.linetype == "regular":
            if len(self.stockonsale) == 0:
                return ([], qty, Decimal("0.0"))
            return ([(self.stockonsale[0], qty)], Decimal("0.0"),
                    self.stockonsale[0].remaining - qty)
        elif self.linetype == "display":
            unallocated = qty
            leftondisplay = Decimal("0.0")
            totalinstock = Decimal("0.0")
            sell = []
            for item in self.stockonsale:
                ondisplay = item.ondisplay
                sellqty = min(unallocated, ondisplay)
                unallocated = unallocated - sellqty
                leftondisplay = leftondisplay + ondisplay - sellqty
                totalinstock = totalinstock + item.remaining - sellqty
                if sellqty > Decimal("0.0"):
                    sell.append((item, sellqty))
            return (sell, unallocated, (leftondisplay,
                                        totalinstock - leftondisplay))
        elif self.linetype == "continuous":
            stock = self.continuous_stockonsale()
            if len(stock) == 0:
                # There's no unfinished stock of the appropriate type
                # at all - we can't do anything.
                return ([], qty, Decimal("0.0"))
            unallocated = qty
            sell = []
            remaining = Decimal("0.0")
            for item in stock:
                sellqty = min(unallocated, max(item.remaining, Decimal("0.0")))
                unallocated = unallocated - sellqty
                remaining += item.remaining - sellqty
                if sellqty > Decimal("0.0"):
                    sell.append((item, sellqty))
            # If there wasn't enough, sell some more of the last item
            # anyway putting it into negative "remaining"
            if unallocated > Decimal("0.0"):
                sell.append((item, unallocated))
                remaining -= unallocated
                unallocated = Decimal("0.0")
            return (sell, unallocated, remaining)

    def other_lines_same_stocktype(self):
        """Return other stocklines with the same linetype and stocktype."""
        return object_session(self)\
            .query(StockLine)\
            .filter(StockLine.linetype == self.linetype)\
            .filter(StockLine.stocktype == self.stocktype)\
            .filter(StockLine.id != self.id)\
            .all()

plu_seq = Sequence('plu_seq')

class PriceLookup(Base):
    """A PriceLookup enables an item or service to be sold that is not
    covered by the stock management system.

    The description is used in menus and is copied to the transaction
    line when the PLU is used.  The department and price are also used
    in the transaction line.

    The note field and alternate price fields are not used by default,
    but may be accessed by modifiers that can override the default
    description and price.
    """
    __tablename__ = 'pricelookups'
    id = Column('id', Integer, plu_seq, nullable=False, primary_key=True)
    description = Column(String(), nullable=False, unique=True,
                         doc="Descriptive text for this PLU")
    note = Column(String(), nullable=False,
                  doc="Additional information for this PLU")
    dept_id = Column('dept', Integer, ForeignKey('departments.dept'),
                     nullable=False)
    # A PLU with a null price will act very much like a department key
    price = Column(money)
    altprice1 = Column(money)
    altprice2 = Column(money)
    altprice3 = Column(money)
    department = relationship(Department, lazy='joined')
    @property
    def name(self):
        return self.description
    @property
    def tillweb_url(self):
        return "plu/%d/" % self.id

suppliers_seq = Sequence('suppliers_seq')

class Supplier(Base):
    __tablename__ = 'suppliers'
    id = Column('supplierid', Integer, suppliers_seq,
                nullable=False, primary_key=True)
    name = Column(String(60), nullable=False)
    tel = Column(String(20))
    email = Column(String(60))
    web = Column(String())
    def __repr__(self):
        return "<Supplier(%s,'%s')>" % (self.id, self.name)
    def __unicode__(self):
        return "%s" % (self.name,)
    @property
    def tillweb_url(self):
        return "supplier/%d/" % (self.id,)

deliveries_seq = Sequence('deliveries_seq')

class Delivery(Base):
    __tablename__ = 'deliveries'
    id = Column('deliveryid', Integer, deliveries_seq,
                nullable=False, primary_key=True)
    supplierid = Column(Integer, ForeignKey('suppliers.supplierid'),
                        nullable=False)
    docnumber = Column(String(40))
    date = Column(Date, nullable=False, server_default=func.current_timestamp())
    checked = Column(Boolean, nullable=False, server_default=text('false'))
    supplier = relationship(Supplier, backref=backref(
        'deliveries', order_by=desc(id)),
                            lazy="joined")
    @property
    def tillweb_url(self):
        return "delivery/%d/" % (self.id,)
    def __repr__(self):
        return "<Delivery(%s)>" % (self.id,)

class UnitType(Base):
    __tablename__ = 'unittypes'
    id = Column('unit', String(10), nullable=False, primary_key=True)
    name = Column(String(30), nullable=False)
    def __unicode__(self):
        return "%s" % (self.name,)
    def __repr__(self):
        return "<UnitType('%s','%s')>" % (self.id, self.name)

class StockUnit(Base):
    __tablename__ = 'stockunits'
    id = Column('stockunit', String(8), nullable=False, primary_key=True)
    name = Column(String(30), nullable=False)
    unit_id = Column('unit', String(10), ForeignKey('unittypes.unit'),
                     nullable=False)
    size = Column(quantity, nullable=False)
    unit = relationship(UnitType)
    def __repr__(self):
        return "<StockUnit('%s',%s)>" % (self.id, self.size)
    def __unicode__(self):
        return self.name

stocktypes_seq = Sequence('stocktypes_seq')

class StockType(Base):
    __tablename__ = 'stocktypes'
    id = Column('stocktype', Integer, stocktypes_seq, nullable=False,
                primary_key=True)
    dept_id = Column('dept', Integer, ForeignKey('departments.dept'),
                     nullable=False)
    manufacturer = Column(String(30), nullable=False)
    name = Column(String(30), nullable=False)
    shortname = Column(String(25), nullable=False)
    abv = Column(Numeric(3, 1))
    unit_id = Column('unit', String(10), ForeignKey('unittypes.unit'),
                     nullable=False)
    saleprice = Column(money, nullable=True) # inc VAT
    saleprice_units = Column(quantity, nullable=False, default=Decimal("1.0"))
    pricechanged = Column(DateTime, nullable=True) # Last time price was changed
    department = relationship(Department, lazy="joined")
    unit = relationship(UnitType, lazy="joined")
    @hybrid_property
    def fullname(self):
        return self.manufacturer + ' ' + self.name
    @property
    def tillweb_url(self):
        return "stocktype/%d/" % self.id
    def __unicode__(self):
        return "%s %s" % (self.manufacturer, self.name)
    def __repr__(self):
        return "<StockType(%s,'%s','%s')>" % (
            self.id, self.manufacturer, self.name)
    @property
    def abvstr(self):
        if self.abv:
            return "{}%".format(self.abv)
        return ""
    @property
    def pricestr(self):
        if self.saleprice is not None:
            if self.saleprice_units == 1:
                return "{}/{}".format(self.saleprice, self.unit.name)
            return "{}/{} {}s".format(
                self.saleprice, self.saleprice_units, self.unit.name)
        return ""
    @property
    def descriptions(self):
        """List of possible descriptions

        Various possible descriptions of this stocktype, returned in
        descending order of string length.
        """
        if self.abv:
            return [
                '%s (%0.1f%% ABV)' % (self.fullname, self.abv),
                self.fullname,
                '%s (%0.1f%% ABV)' % (self.shortname, self.abv),
                self.shortname,]
        return [self.fullname, self.shortname]

    def format(self, maxw=None):
        """Format this stocktype with optional maximum width

        maxw can be an integer specifying the maximum number of
        characters, or a function with a single string argument that
        returns True if the string will fit.  Note that if maxw is a
        function, we do not _guarantee_ to return a string that will fit.
        """
        d = self.descriptions
        if maxw is None:
            return d[0]
        if isinstance(maxw, int):
            maxwf = lambda x: len(x) <= maxw
        else:
            maxwf = maxw
        
        while len(d) > 1:
            if maxwf(d[0]):
                return d[0]
            d = d[1:]
        if isinstance(maxw, int):
            return d[0][:maxw]
        return d[0]

class FinishCode(Base):
    __tablename__ = 'stockfinish'
    id = Column('finishcode', String(8), nullable=False, primary_key=True)
    description = Column(String(50), nullable=False)
    def __unicode__(self):
        return "%s" % self.description
    def __repr__(self):
        return "<FinishCode('%s','%s')>" % (self.id, self.description)

stock_seq = Sequence('stock_seq')
class StockItem(Base):
    """An item of stock - a cask, keg, case of bottles, card of snacks,
    and so on.

    When this item is prepared for sale, it is linked to a StockLine.
    If the stockline type is "display", the item will have a
    displayqty.  For all other stockline types, displayqty will be
    null.

    On "Display" StockLines, a null displayqty should be read as zero.

    This diagram shows how displayqty works in relation to the size of
    the stock item and how much of it has already been used:

    0     1     2     3     4     5     6     7     8     9    10
    |-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|
    <--------------------- stockunit.size ----------------------> = 10
    <-------- used -------->|<------------ remaining ----------->
                            |<-- ondisplay -->|<--- instock ---->
    <-------------- displayqty -------------->|
    """

    __tablename__ = 'stock'
    id = Column('stockid', Integer, stock_seq, nullable=False, primary_key=True)
    deliveryid = Column(Integer, ForeignKey('deliveries.deliveryid'),
                        nullable=False)
    stocktype_id = Column('stocktype', Integer,
                          ForeignKey('stocktypes.stocktype'), nullable=False)
    stockunit_id = Column('stockunit', String(8),
                          ForeignKey('stockunits.stockunit'), nullable=False)
    costprice = Column(money) # ex VAT
    onsale = Column(DateTime)
    finished = Column(DateTime)
    finishcode_id = Column('finishcode', String(8),
                           ForeignKey('stockfinish.finishcode'))
    bestbefore = Column(Date)
    delivery = relationship(Delivery, backref=backref('items', order_by=id))
    stocktype = relationship(StockType, backref=backref('items', order_by=id))
    stockunit = relationship(StockUnit, lazy="joined")
    finishcode = relationship(FinishCode, lazy="joined")
    stocklineid = Column(Integer, ForeignKey('stocklines.stocklineid',
                                             ondelete='SET NULL'),
                         nullable=True)
    displayqty = Column(quantity, nullable=True)
    __table_args__ = (
        CheckConstraint(
            "not(stocklineid is null) or displayqty is null",
            name="displayqty_null_if_no_stockline"),
        CheckConstraint(
            "(finished is null)=(finishcode is null)",
            name="finished_and_finishcode_null_together"),
        CheckConstraint(
            "not(finished is not null) or stocklineid is null",
            name="stocklineid_null_if_finished"),
    )
    stockline = relationship(StockLine, backref=backref(
            'stockonsale',
            order_by=lambda: (
                desc(func.coalesce(StockItem.displayqty, 0)),
                StockItem.id)))

    @property
    def shelflife(self):
        """The shelf-life of the item, in days.

        None if the best-before date is not known.  Negative if the
        item is out of date.
        """
        if self.bestbefore is None:
            return None
        return (self.bestbefore - datetime.date.today()).days
    @property
    def displayqty_or_zero(self):
        """displayqty is always null when a stockline has no display
        capacity.

        On lines with a display capacity, a displayqty of null should
        be read as zero.

        This is needed for compatibility with legacy till databases.
        """
        if self.displayqty is None:
            return 0
        return self.displayqty
    @property
    def ondisplay(self):
        """The number of units of stock on display waiting to be sold.
        """
        if self.stockline.capacity is None:
            return None
        return self.displayqty_or_zero - self.used
    @property
    def instock(self):
        """The number of units of stock not yet on display.
        """
        if self.stockline.capacity is None:
            return None
        return self.stockunit.size - self.displayqty_or_zero

    # used and remaining column properties are added after the
    # StockOut class is defined
    @property
    def checkdigits(self):
        """Three digits that will annoy lazy staff

        Return three digits derived from the stock ID number.  These
        digits can be printed on stock labels; knowledge of the digits
        can be used to confirm that a member of staff really does have
        a particular item of stock in front of them.
        """
        a = hashlib.sha1(("quicktill-%d-quicktill" % self.id).encode('utf-8'))
        return str(int(a.hexdigest(), 16))[-3:]
    @property
    def removed(self):
        """Amount of stock removed from this item under all the
        various RemoveCodes.

        Returns a list of (RemoveCode, qty) tuples.
        """
        return object_session(self).\
            query(RemoveCode, func.sum(StockOut.qty)).\
            select_from(StockOut.__table__).\
            join(RemoveCode).\
            filter(StockOut.stockid == self.id).\
            group_by(RemoveCode).\
            order_by(desc(func.sum(StockOut.qty))).\
            all()
    @property
    def remaining_units(self):
        """Quantity remaining as a string with the unit name

        eg. 2 pints, 1 pint, 3 bottles
        """
        return "%s %s%s" % (
            self.remaining, self.stocktype.unit.name,
            "s" if self.remaining != Decimal(1) else "")
    @property
    def tillweb_url(self):
        return "stock/%d/" % self.id
    def __repr__(self):
        return "<StockItem(%s)>" % (self.id,)

class AnnotationType(Base):
    __tablename__ = 'annotation_types'
    id = Column('atype', String(8), nullable=False, primary_key=True)
    description = Column(String(20), nullable=False)
    def __unicode__(self):
        return "%s" % (self.description,)
    def __repr__(self):
        return "<AnnotationType('%s','%s')>" % (self.id,self.description)

stock_annotation_seq = Sequence('stock_annotation_seq');

class StockAnnotation(Base):
    __tablename__ = 'stock_annotations'
    id = Column(Integer, stock_annotation_seq, nullable=False, primary_key=True)
    stockid = Column(Integer, ForeignKey('stock.stockid'), nullable=False)
    atype = Column(String(8), ForeignKey('annotation_types.atype'),
                   nullable=False)
    time = Column(DateTime, nullable=False,
                  server_default=func.current_timestamp())
    text = Column(String(), nullable=False)
    user_id = Column('user', Integer, ForeignKey('users.id'), nullable=True,
                     doc="User who created this annotation")
    stockitem = relationship(StockItem, backref=backref(
        'annotations', order_by=time))
    type = relationship(AnnotationType)
    user = relationship(User, backref=backref("annotations", order_by=time))
    def __repr__(self):
        return "<StockAnnotation(%s,%s,'%s','%s')>" % (
            self.id, self.stockitem, self.atype, self.text)

class RemoveCode(Base):
    __tablename__ = 'stockremove'
    id = Column('removecode', String(8), nullable=False, primary_key=True)
    reason = Column(String(80))
    def __unicode__(self):
        return "%s" % (self.reason,)
    def __repr__(self):
        return "<RemoveCode('%s','%s')>" % (self.id, self.reason)

stockout_seq = Sequence('stockout_seq')

class StockOut(Base):
    __tablename__ = 'stockout'
    id = Column('stockoutid', Integer, stockout_seq,
                nullable=False, primary_key=True)
    stockid = Column(Integer, ForeignKey('stock.stockid'), nullable=False)
    qty = Column(quantity, nullable=False)
    removecode_id = Column('removecode', String(8),
                           ForeignKey('stockremove.removecode'), nullable=False)
    translineid = Column(Integer, ForeignKey('translines.translineid',
                                             ondelete='CASCADE'),
                         nullable=True)
    time = Column(DateTime, nullable=False,
                  server_default=func.current_timestamp())
    stockitem = relationship(StockItem, backref=backref('out', order_by=id))
    removecode = relationship(RemoveCode, lazy="joined")
    transline = relationship(Transline,
                             backref=backref('stockref', cascade="all,delete"))
    def __repr__(self):
        return "<StockOut(%s,%s)>" % (self.id, self.stockid)

# These are added to the StockItem class here because they refer
# directly to the StockOut class, defined just above.
StockItem.used = column_property(
    select([func.coalesce(func.sum(StockOut.qty), text("0.0"))]).\
        correlate(StockItem.__table__).\
        where(StockOut.stockid == StockItem.id).\
        label('used'),
    deferred=True,
    group="qtys",
    doc="Amount of this item that has been used for any reason")
StockItem.sold = column_property(
    select([func.coalesce(func.sum(StockOut.qty), text("0.0"))]).\
        correlate(StockItem.__table__).\
        where(StockOut.stockid == StockItem.id).\
        where(StockOut.removecode_id == "sold").\
        label('sold'),
    deferred=True,
    group="qtys",
    doc="Amount of this item that has been used by being sold")
StockItem.remaining = column_property(
    select([select([StockUnit.size], StockUnit.id == StockItem.stockunit_id
                   ).correlate(StockItem.__table__) -
                func.coalesce(func.sum(StockOut.qty), text("0.0"))]).\
        where(StockOut.stockid == StockItem.id).\
        label('remaining'),
    deferred=True,
    group="qtys",
    doc="Amount of this item remaining")
StockItem.firstsale = column_property(
    select([func.min(StockOut.time)]).\
        correlate(StockItem.__table__).\
        where(StockOut.stockid == StockItem.id).\
        where(StockOut.removecode_id == 'sold').\
        label('firstsale'),
    deferred=True,
    doc="Time of first sale of this item")
StockItem.lastsale = column_property(
    select([func.max(StockOut.time)]).\
        correlate(StockItem.__table__).\
        where(StockOut.stockid == StockItem.id).\
        where(StockOut.removecode_id == 'sold').\
        label('lastsale'),
    deferred=True,
    doc="Time of last sale of this item")

# Similarly, this is added to the StockType class here because it
# refers to Stock

# XXX should this be renamed to StockType.remaining?  It appears to be
# doing that job.  Let's add an alias.
StockType.instock = column_property(
    select([func.coalesce(func.sum(
                    select([func.sum(StockUnit.size)],
                           StockUnit.id == StockItem.stockunit_id,
                           ).as_scalar() -
                    select([func.coalesce(func.sum(StockOut.qty), text("0.0"))],
                           StockOut.stockid == StockItem.id,
                           ).as_scalar()
                    ), text("0.0"))],
           and_(StockItem.stocktype_id == StockType.id,
                StockItem.finished == None,
                Delivery.id == StockItem.deliveryid,
                Delivery.checked == True)).\
        correlate(StockType.__table__).\
        label('instock'),
    deferred=True,
    doc="Amount remaining in stock")
StockType.remaining = StockType.instock
StockType.lastsale = column_property(
    select([func.max(StockOut.time)],
           and_(StockItem.stocktype_id == StockType.id,
                StockOut.stockid == StockItem.id,
                Delivery.id == StockItem.deliveryid,
                Delivery.checked == True)).\
        correlate(StockType.__table__).\
        label('lastsale'),
    deferred=True,
    doc="Date of last sale")

class KeyboardBinding(Base):
    __tablename__ = 'keyboard'
    keycode = Column(String(20), nullable=False, primary_key=True)
    menukey = Column(String(20), nullable=False, primary_key=True)
    stocklineid = Column(Integer, ForeignKey(
            'stocklines.stocklineid', ondelete='CASCADE'))
    pluid = Column(Integer, ForeignKey(
        'pricelookups.id', ondelete='CASCADE'))
    modifier = Column(String(), nullable=True)
    stockline = relationship(StockLine,
                             backref=backref('keyboard_bindings', cascade='all'))
    plu = relationship(PriceLookup,
                       backref=backref('keyboard_bindings', cascade='all'))
    # At least one of stocklineid, pluid and modifier must be non-NULL
    # At most one of stocklineid and pluid can be non-NULL
    __table_args__ = (
        CheckConstraint(
            "stocklineid IS NOT NULL OR pluid IS NOT NULL "
            "OR modifier IS NOT NULL",
            name="be_useful_constraint"),
        CheckConstraint(
            "stocklineid IS NULL OR pluid IS NULL",
            name="be_unambiguous_constraint"),
    )
    def __repr__(self):
        return "<KeyboardBinding({},{})>".format(self.keycode, self.menukey)
    @property
    def name(self):
        """Look up the name of this binding

        Since the binding doesn't have an explicit name, we use the
        stockline name, PLU name, or modifer name as appropriate.
        """
        if self.stockline:
            return self.stockline.name
        if self.plu:
            return self.plu.description
        return self.modifier
    @property
    def keycap(self):
        """Look up the keycap corresponding to the keycode of this binding.

        This is intended for use in the web interface, not in the main
        part of the till software; that should be looking at the
        keycap attribute of the keyboard.linekey object, if that
        object exists.  (It is not guaranteed to exist, because line
        keys can be removed from the keyboard definition if they are
        repurposed.)
        """
        return object_session(self).query(KeyCap).get(self.keycode)

class KeyCap(Base):
    __tablename__ = 'keycaps'
    keycode = Column(String(20), nullable=False, primary_key=True)
    keycap = Column(String(30))
    def __repr__(self):
        return "<KeyCap('%s','%s')>" % (self.keycode, self.keycap)

class StockLineTypeLog(Base):
    """Association table for stocklines to stocktypes

    This table records all the stocktypes that have been used on each
    stockline.  This information is used in the "auto-allocate stock
    to display stocklines" function, and is also used to sort sensible
    defaults to the top of the list when displaying lists of stock
    that can be put on sale on a stockline.
    """
    __tablename__ = 'stockline_stocktype_log'
    stocklineid = Column(
        Integer, ForeignKey('stocklines.stocklineid', ondelete='CASCADE'),
        nullable=False, primary_key=True)
    stocktype_id = Column(
        'stocktype', Integer,
        ForeignKey('stocktypes.stocktype', ondelete='CASCADE'),
        nullable=False, primary_key=True)
    stockline = relationship(
        StockLine, backref=backref('stocktype_log', passive_deletes=True),
        lazy='joined')
    stocktype = relationship(
        StockType, backref=backref('stockline_log', passive_deletes=True),
        lazy='joined')
    def __repr__(self):
        return "<StockLineTypeLog(%s,%s)>" % (
            self.stocklineid, self.stocktype_id)

add_ddl(StockLineTypeLog.__table__, """
CREATE OR REPLACE RULE ignore_duplicate_stockline_types AS
       ON INSERT TO stockline_stocktype_log
       WHERE (NEW.stocklineid,NEW.stocktype)
       IN (SELECT stocklineid,stocktype FROM stockline_stocktype_log)
       DO INSTEAD NOTHING
""", """
DROP RULE ignore_duplicate_stockline_types ON stockline_stocktype_log
""")

add_ddl(metadata, """
CREATE OR REPLACE RULE log_stocktype AS ON UPDATE TO stock
       WHERE NEW.stocklineid is not null
       DO ALSO
       INSERT INTO stockline_stocktype_log VALUES
       (NEW.stocklineid,NEW.stocktype);
""", """
DROP RULE log_stocktype ON stock
""")

# Add indexes here
Index('translines_transid_key', Transline.transid)
Index('payments_transid_key', Payment.transid)
Index('transactions_sessionid_key', Transaction.sessionid)
Index('stock_annotations_stockid_key', StockAnnotation.stockid)
Index('stockout_stockid_key', StockOut.stockid)
Index('translines_time_key', Transline.time)

# The "find free drinks on this day" function is speeded up
# considerably by an index on stockout.time::date.
Index('stockout_date_key', func.cast(StockOut.time, Date))

foodorder_seq = Sequence('foodorder_seq', metadata=metadata)
