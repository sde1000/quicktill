from sqlalchemy.ext.declarative import declarative_base, declared_attr
from sqlalchemy import Column, Integer, String, DateTime, Date
from sqlalchemy.dialects import postgresql
from sqlalchemy import ForeignKey, Numeric, CHAR, Boolean, Text, Interval
from sqlalchemy.schema import Sequence, Index, MetaData, DDL
from sqlalchemy.schema import CheckConstraint, Table
from sqlalchemy.schema import UniqueConstraint
from sqlalchemy.schema import ForeignKeyConstraint
from sqlalchemy.sql.expression import text, alias, case, literal
from sqlalchemy.orm import relationship, backref, object_session
from sqlalchemy.orm import joinedload, subqueryload, lazyload
from sqlalchemy.orm import contains_eager, column_property
from sqlalchemy.orm import undefer
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql import select, func, desc, and_
from sqlalchemy import event
from sqlalchemy import distinct
from sqlalchemy import inspect

import datetime
import hashlib
from decimal import Decimal
from inspect import isclass
import re

# Configuration of money
money_max_digits = 10
money_decimal_places = 2

# Configuration of quantities
qty_max_digits = 8
qty_decimal_places = 1

# Used for quantization of money
zero = Decimal("0.{}".format("0" * money_decimal_places))
penny = Decimal("0.{}1".format("0" * (money_decimal_places - 1)))

# Common column types
money = Numeric(money_max_digits, money_decimal_places)
max_money = Decimal("9" * (money_max_digits - money_decimal_places)
                    + "."
                    + "9" * money_decimal_places)

quantity = Numeric(qty_max_digits, qty_decimal_places)
min_quantity = Decimal("0." + "0" * (qty_decimal_places - 1) + "1")
max_quantity = Decimal("9" * (qty_max_digits - qty_decimal_places)
                       + "."
                       + "9" * qty_decimal_places)

metadata = MetaData()

# Methods common to all models
class Base:
    def get_view_url(self, viewname, *args, **kwargs):
        s = object_session(self)
        reverse = s.info["reverse"]
        kwargs['pubname'] = s.info["pubname"]
        return reverse(viewname, args=args, kwargs=kwargs)

    def get_absolute_url(self):
        return self.get_view_url(self.tillweb_viewname,
                                 **{self.tillweb_argname: self.id})

    # repr() of an instance is used in log entries
    def __repr__(self):
        insp = inspect(self)
        if insp.identity:
            return f"{self.__class__.__name__}"\
                f"({','.join(str(x) for x in insp.identity)})"
        else:
            return f"{self.__class__.__name__}(no-identity)"

    # What to use as the 'text' part of a log reference?  Override in
    # models as required.
    @property
    def logtext(self):
        return ""

    @property
    def logref(self):
        """A suitable log reference for this model
        """
        # Log references look like [text]ModelName(pk1,pk2,...)
        # If text is absent, the primary key is used instead.
        # Text may not contain ']'!
        return f"[{str(self.logtext).replace(']', '')}]{self!r}"

    # What name does the relationship to this model have, in the log
    # model?
    @classmethod
    def _log_relationship_name(cls):
        return cls.__name__.lower()

Base = declarative_base(metadata=metadata, cls=Base)

# Use this class as a mixin to request a foreign key relationship from
# the 'log' table.  Log entries are accessible using the 'logs'
# relationship.
class Logged:
    pass

# Rules that depend on the existence of more than one table must be
# added to the metadata rather than the table - they will be created
# after all tables, and dropped before any tables.
def add_ddl(target, create, drop):
    """Add DDL explicitly

    Convenience function to add CREATE and DROP statements for
    postgresql database rules.
    """
    if create:
        event.listen(target, "after_create",
                     DDL(create).execute_if(dialect='postgresql'))
    if drop:
        event.listen(target, "before_drop",
                     DDL(drop).execute_if(dialect='postgresql'))

class Business(Base, Logged):
    __tablename__ = 'businesses'
    id = Column('business', Integer, primary_key=True, autoincrement=False)
    name = Column(String(80), nullable=False)
    abbrev = Column(String(20), nullable=False)
    address = Column(String(), nullable=False)
    vatno = Column(String(30))
    show_vat_breakdown = Column(Boolean(),nullable=False,default=False)
    def __str__(self):
        return "%s" % (self.abbrev,)

# This is intended to be a mixin for both VatBand and VatRate.  It's
# not intended to be instantiated.
class Vat:
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

class VatBand(Base, Vat, Logged):
    __tablename__ = 'vat'
    band = Column(CHAR(1), primary_key=True)
    business = relationship(Business, backref='vatbands')

# Note that the tillweb index page code ignores the 'business' field
# in VatRate and only uses VatBand.  Until this is fixed you should
# not use a VatRate entry to change the business for a VatBand -
# create a new department instead.
class VatRate(Base, Vat, Logged):
    __tablename__ = 'vatrates'
    band = Column(CHAR(1), ForeignKey('vat.band'), primary_key=True)
    active = Column(Date, nullable=False, primary_key=True)
    business = relationship(Business, backref='vatrates')

class PayType(Base):
    __tablename__ = 'paytypes'
    paytype = Column(String(8), nullable=False, primary_key=True)
    description = Column(String(10), nullable=False)
    def __str__(self):
        return "%s" % (self.description,)

sessions_seq = Sequence('sessions_seq')

class Session(Base, Logged):
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
    accinfo = Column(String(), nullable=True, doc="Accounting system info")

    def __init__(self, date):
        self.date=date
        self.starttime = datetime.datetime.now()

    def __str__(self):
        return "Session %d" % self.id

    tillweb_viewname = "tillweb-session"
    tillweb_argname = "sessionid"
    def tillweb_nav(self):
        return [("Sessions", self.get_view_url("tillweb-sessions")),
                ("{} ({})".format(self.id, self.date), self.get_absolute_url())]
    
    incomplete_transactions = relationship(
        "Transaction",
        primaryjoin="and_(Transaction.sessionid==Session.id,Transaction.closed==False)")

    @property
    def accounts_url(self):
        """Accounting system URL for this session
        """
        if not self.accinfo:
            return
        s = object_session(self)
        accounts = s.info.get("accounts") if s else None
        if accounts:
            return accounts.url_for_invoice(self.accinfo)

    @property
    def dept_totals(self):
        """Transaction lines broken down by Department.

        Returns list of (Department, total) keyed tuples.
        """
        return object_session(self).\
            query(Department, func.sum(
                Transline.items * Transline.amount).label("total")).\
            select_from(Session).\
            filter(Session.id == self.id).\
            join(Transaction, Transline, Department).\
            order_by(Department.id).\
            group_by(Department).all()

    @property
    def dept_totals_closed(self):
        """Transaction lines broken down by Department and closed status.

        Returns list of (Department, total, paid, pending,
        discount_total) keyed tuples.  The list always includes all
        departments, even if all totals are None.  Access the tuples
        using keys not indices, so that
        """
        s = object_session(self)
        tot_all = s.query(func.sum(Transline.items * Transline.amount))\
                   .select_from(Transline.__table__)\
                   .join(Transaction)\
                   .filter(Transaction.sessionid == self.id)\
                   .filter(Transline.dept_id == Department.id)
        tot_closed = tot_all.filter(Transaction.closed == True)
        tot_open = tot_all.filter(Transaction.closed == False)
        tot_discount = s.query(func.sum(Transline.items * Transline.discount))\
                        .select_from(Transline.__table__)\
                        .join(Transaction)\
                        .filter(Transaction.sessionid == self.id)\
                        .filter(Transline.dept_id == Department.id)
        return s.query(Department,
                       tot_all.label("total"),
                       tot_closed.label("paid"),
                       tot_open.label("pending"),
                       tot_discount.label("discount_total"))\
                .order_by(Department.id)\
                .group_by(Department).all()

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
    @hybrid_property
    def pending_total(self):
        "Total of open transactions"
        return self.total - self.closed_total

    @hybrid_property
    def error(self):
        "Difference between actual total and transaction line total."
        return self.actual_total - self.total if self.actual_total else None
    @error.expression
    def error(cls):
        return cls.actual_total - cls.total

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
            join(Unit).\
            join(StockItem).\
            join(StockOut).\
            join(Transline).\
            join(Transaction).\
            filter(Transaction.sessionid == self.id).\
            options(lazyload(StockType.department)).\
            options(contains_eager(StockType.unit)).\
            group_by(StockType, Unit).\
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

    @property
    def next(self):
        """Next session

        Return the subsequent session, or None.
        """
        if hasattr(self, "_nextsession"):
            return self._nextsession
        self._nextsession = object_session(self)\
            .query(Session)\
            .filter(Session.id > self.id)\
            .order_by(Session.id)\
            .first()
        return self._nextsession

    @property
    def previous(self):
        """Previous session

        Return the previous session, or None.
        """
        if hasattr(self, "_prevsession"):
            return self._prevsession
        self._prevsession = object_session(self)\
            .query(Session)\
            .filter(Session.id < self.id)\
            .order_by(desc(Session.id))\
            .first()
        return self._prevsession

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

Session.actual_total = column_property(
    select([func.sum(SessionTotal.amount)],
           whereclause=and_(SessionTotal.sessionid == Session.id)).\
        correlate(Session.__table__).\
        label('actual_total'),
    deferred=True,
    doc="Actual recorded total")

transactions_seq = Sequence('transactions_seq')

class Transaction(Base, Logged):
    __tablename__ = 'transactions'
    id = Column('transid', Integer, transactions_seq, nullable=False,
                primary_key=True)
    sessionid = Column(Integer, ForeignKey('sessions.sessionid'),
                       nullable=True) # Null sessionid for deferred transactions
    notes = Column(String(60), nullable=False, default='')
    closed = Column(Boolean, nullable=False, default=False)
    # The discount policy column is used when transactions are open to
    # store the name of the discount policy to apply whenever a
    # transaction line is added or changed.  Closed transactions are
    # immutable, so discount policies can no longer be applied.  A
    # record of which policy was used is stored per transaction line.
    discount_policy = Column(String(), nullable=True)

    __table_args__ = (
        # closed implies discount_policy is null
        CheckConstraint(
            "NOT(closed) OR (discount_policy IS NULL)",
            name="discount_policy_closed_constraint"),
    )

    session = relationship(Session, backref=backref('transactions', order_by=id))

    # total is a column property defined below

    # payments_total is a column property defined below

    def payments_summary(self):
        """List of (paytype, amount) tuples.

        Used by the web interface.
        """
        pts = {}
        for p in self.payments:
            pts[p.paytype] = pts.get(p.paytype, zero) + p.amount
        return list(pts.items())

    @property
    def balance(self):
        """Transaction balance
        """
        return self.total - self.payments_total

    tillweb_viewname = "tillweb-transaction"
    tillweb_argname = "transid"

    def tillweb_nav(self):
        if self.session:
            return self.session.tillweb_nav() \
                + [(str(self), self.get_absolute_url())]
        return [("Deferred transactions",
                 self.get_view_url("tillweb-deferred-transactions")),
                (str(self), self.get_absolute_url())]

    # age is now a column property, defined below

    def __str__(self):
        return "Transaction %d" % self.id

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

class User(Base, Logged):
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
    groups = relationship("Group", secondary="group_grants", backref="users")
    permissions = relationship(
        "Permission",
        secondary="join(group_membership, group_grants, group_membership.c.group == group_grants.c.group)"
        ".join(Permission, group_membership.c.permission == Permission.id)",
        viewonly=True)
    transaction = relationship(Transaction, backref=backref(
        'user', uselist=False))

    tillweb_viewname = "tillweb-till-user"
    tillweb_argname = "userid"
    def tillweb_nav(self):
        return [("Users", self.get_view_url("tillweb-till-users")),
                (self.fullname, self.get_absolute_url())]

    def __str__(self):
        return self.fullname

class UserToken(Base, Logged):
    """A token used by a till user to identify themselves

    These will typically be NFC cards or iButton tags.  This table
    aims to be technology-neutral.
    """
    __tablename__ = 'usertokens'
    token = Column(String(), primary_key=True)
    authdata = Column(String(), nullable=True)
    description = Column(String())
    user_id = Column('user', Integer, ForeignKey('users.id'))
    last_seen = Column(DateTime)
    user = relationship(User, backref='tokens')

class Permission(Base):
    """Permission to do something

    Permission to perform an operation on the till or on the web
    interface.  Permissions are identified by name; the description
    here is just for convenience.  Permissions are defined in the code
    and a record is created here the first time the till loads any
    user information after startup.
    """
    __tablename__ = 'permissions'
    id = Column(String(), nullable=False, primary_key=True,
                doc="Name of the permission")
    description = Column(String(), nullable=False,
                         doc="Brief description of the permission")

    def __str__(self):
        return f"{self.id} — {self.description}"

class Group(Base, Logged):
    """A group of permissions

    The groups 'basic-user', 'skilled-user' and 'manager' get newly
    implemented permissions added to them automatically according to
    the defaults in the 'user' module.  All other groups are managed
    entirely by the users.
    """
    __tablename__ = 'groups'
    id = Column(String(), nullable=False, primary_key=True,
                doc="Name of the group")
    description = Column(String(), nullable=False,
                         doc="Brief description of the group")
    permissions = relationship("Permission", secondary="group_membership",
                               backref="groups")

    tillweb_viewname = "tillweb-till-group"
    tillweb_argname = "groupid"
    def tillweb_nav(self):
        return [("Groups", self.get_view_url("tillweb-till-groups")),
                (self.id, self.get_absolute_url())]

    def __str__(self):
        return f"{self.id} — {self.description}"

# Accessed through Group.permissions and Permission.groups
group_membership_table = Table(
    'group_membership', Base.metadata,
    Column('group', String(),
           ForeignKey('groups.id', ondelete='CASCADE', onupdate='CASCADE'),
           primary_key=True),
    Column('permission', String(),
           ForeignKey('permissions.id', ondelete='CASCADE'),
           primary_key=True)
)
add_ddl(group_membership_table, """
CREATE OR REPLACE FUNCTION notify_group_membership_change() RETURNS trigger AS $$
DECLARE
BEGIN
  PERFORM pg_notify('group_membership_changed', '');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER group_membership_changed
  AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON group_membership
  EXECUTE PROCEDURE notify_group_membership_change();
""", """
DROP TRIGGER group_membership_changed ON group_membership;
DROP FUNCTION notify_group_membership_change();
""")

# Accessed through User.groups and Group.users
group_grants_table = Table(
    'group_grants', Base.metadata,
    Column('user', Integer, ForeignKey('users.id'), primary_key=True),
    Column('group', String(),
           ForeignKey('groups.id', ondelete='CASCADE', onupdate='CASCADE'),
           primary_key=True)
)
add_ddl(group_grants_table, """
CREATE OR REPLACE FUNCTION notify_group_grants_change() RETURNS trigger AS $$
DECLARE
BEGIN
  PERFORM pg_notify('group_grants_changed', '');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER group_grants_changed
  AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON group_grants
  EXECUTE PROCEDURE notify_group_grants_change();
""", """
DROP TRIGGER group_grants_changed ON group_grants;
DROP FUNCTION notify_group_grants_change();
""")

payments_seq = Sequence('payments_seq', start=1)

class Payment(Base, Logged):
    __tablename__ = 'payments'
    id = Column('paymentid', Integer, payments_seq, nullable=False,
                primary_key=True)
    transid = Column(
        Integer,
        ForeignKey('transactions.transid', ondelete='CASCADE'),
        nullable=False)
    amount = Column(money, nullable=False)
    paytype_id = Column('paytype', String(8), ForeignKey('paytypes.paytype'),
                        nullable=False)
    ref = Column(String())
    time = Column(DateTime, nullable=False,
                  server_default=func.current_timestamp())
    user_id = Column('user', Integer, ForeignKey('users.id'), nullable=True,
                     doc="User who created this payment")
    transaction = relationship(
        Transaction,
        backref=backref('payments', order_by=id,
                        passive_deletes="all"))
    paytype = relationship(PayType)
    user = relationship(User)

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

class Department(Base, Logged):
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

    def __str__(self):
        return "%s" % (self.description,)

    @property
    def logtext(self):
        return self.description

    tillweb_viewname = "tillweb-department"
    tillweb_argname = "departmentid"
    def tillweb_nav(self):
        return [("Departments", self.get_view_url("tillweb-departments")),
                ("{}. {}".format(self.id, self.description),
                 self.get_absolute_url())]

    @property
    def decoded_accinfo(self):
        """Return a list of (description, data) explaining accinfo
        """
        if not self.accinfo:
            return
        s = object_session(self)
        accounts = s.info.get("accounts") if s else None
        if accounts:
            return accounts.decode_dept_accinfo(self.accinfo)

class TransCode(Base):
    __tablename__ = 'transcodes'
    code = Column('transcode', CHAR(1), nullable=False, primary_key=True)
    description = Column(String(20), nullable=False)

    def __str__(self):
        return "%s" % (self.description,)

translines_seq = Sequence('translines_seq', start=1)

class Transline(Base, Logged):
    __tablename__ = 'translines'
    id = Column('translineid', Integer, translines_seq, nullable=False,
                primary_key=True)
    transid = Column(
        Integer,
        ForeignKey('transactions.transid', ondelete='CASCADE'),
        nullable=False)
    items = Column(Integer, nullable=False)
    amount = Column(money, CheckConstraint("amount >= 0.00"),
                    nullable=False)
    dept_id = Column('dept', Integer, ForeignKey('departments.dept'),
                     nullable=False)
    user_id = Column('user', Integer, ForeignKey('users.id'), nullable=True,
                     doc="User who created this transaction line")
    voided_by_id = Column(
        'voided_by', Integer,
        ForeignKey('translines.translineid', ondelete="SET NULL"),
        nullable=True, unique=True,
        doc="Transaction line that voids this one")
    transcode = Column(CHAR(1), ForeignKey('transcodes.transcode'),
                       nullable=False)
    time = Column(DateTime, nullable=False,
                  server_default=func.current_timestamp())
    text = Column(Text, nullable=False)
    # The discount column records the discount applied to the amount
    # _per item_, i.e. you must multiply by the number of items to get
    # the total discount.
    discount = Column(money, CheckConstraint("discount >= 0.00"),
                      nullable=False, server_default=literal(zero),
                      doc="Amount of discount applied to this transaction line")
    discount_name = Column(String(), nullable=True)

    __table_args__ = (
        # If discount is zero, discount_name must be null
        # If discount is not zero, discount_name must not be null
        CheckConstraint(
            "(discount = 0.00) = (discount_name IS NULL)",
            name="discount_name_constraint"),
    )

    @property
    def original_amount(self):
        """The original amount of the transaction line before any discounts
        """
        return self.amount + (self.discount or zero)

    transaction = relationship(
        Transaction,
        backref=backref('lines', order_by=id,
                        passive_deletes=True))
    department = relationship(Department)
    user = relationship(User)
    voided_by = relationship(
        "Transline", remote_side=[id], uselist=False,
        backref=backref('voids', uselist=False, passive_deletes=True))
    def __str__(self):
        return "Transaction line {} in transaction {}".format(
            self.id, self.transaction.id)

    @hybrid_property
    def total(self):
        return self.items * self.amount

    @hybrid_property
    def total_discount(self):
        return self.items * self.discount

    tillweb_viewname = "tillweb-transline"
    tillweb_argname = "translineid"
    def tillweb_nav(self):
        return self.transaction.tillweb_nav() \
            + [("Line {}{}".format(
                self.id, " (VOIDED)" if self.voided_by else ""),
                self.get_absolute_url())]

    @property
    def description(self):
        # This property is left over from the days before 'text' was
        # guaranteed not to be null.  New code should use the 'text'
        # attribute directly.
        return self.text

    def regtotal(self, currency):
        """Formatted version of items and price

        The number of items and price formatted nicely for display in
        the register or on a receipt.
        """
        if self.amount == zero and self.discount == zero:
            return ""
        if self.items == 1:
            return "%s%s" % (currency, self.amount)
        return "%d @ %s%s = %s%s" % (
            self.items, currency, self.amount, currency,
            self.items * self.amount)

    def void(self, transaction, user):
        """Void this transaction line

        Create a new transaction line in the specified transaction
        (not necessarily the same as this line's transaction) that
        voids this line and return it.

        If this transaction line has already been voided, returns
        None.
        """
        if self.voided_by:
            return
        v = Transline(transaction=transaction, items=-self.items,
                      amount=self.amount, discount=self.discount,
                      discount_name=self.discount_name,
                      department=self.department,
                      user=user, transcode='V', text=self.text)
        self.voided_by = v
        for stockout in self.stockref:
            v.stockref.append(StockOut(
                stockitem=stockout.stockitem, qty=-stockout.qty,
                removecode=stockout.removecode))
        return v

# This trigger permits null columns (text or user) to be set to
# not-null in closed transactions but subsequently prevents
# modification
add_ddl(Transline.__table__, """
CREATE FUNCTION check_modify_closed_trans_line() RETURNS trigger AS $$
BEGIN
  IF (SELECT closed FROM transactions WHERE transid=NEW.transid)=true
    AND (OLD.translineid != NEW.translineid
      OR OLD.transid != NEW.transid
      OR OLD.items != NEW.items
      OR OLD.amount != NEW.amount
      OR OLD.dept != NEW.dept
      OR OLD.user != NEW.user
      OR OLD.transcode != NEW.transcode
      OR OLD.time != NEW.time
      OR OLD.text != NEW.text)
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
                          zero)],
           whereclause=and_(Transline.transid == Transaction.id,
                            Transaction.sessionid == Session.id)).\
        correlate(Session.__table__).\
        label('total'),
    deferred=True,
    doc="Transaction lines total")
Session.closed_total = column_property(
    select([func.coalesce(func.sum(Transline.items * Transline.amount),
                          zero)],
           whereclause=and_(Transline.transid == Transaction.id,
                            Transaction.closed,
                            Transaction.sessionid == Session.id)).\
        correlate(Session.__table__).\
        label('closed_total'),
    deferred=True,
    doc="Transaction lines total, closed transactions only")

Session.discount_total = column_property(
    select([func.coalesce(func.sum(Transline.items * Transline.discount),
                          zero)],
           whereclause=and_(Transline.transid == Transaction.id,
                            Transaction.sessionid == Session.id)).\
        correlate(Session.__table__).\
        label('discount_total'),
    deferred=True,
    doc="Discount total")

# Add Transline-related column properties to the Transaction class now
# that transactions and translines are both defined
Transaction.total = column_property(
    select([func.coalesce(func.sum(Transline.items * Transline.amount),
                          zero)],
           whereclause=and_(Transline.transid == Transaction.id)).\
        correlate(Transaction.__table__).\
        label('total'),
    deferred=True,
    doc="Transaction lines total")

Transaction.discount_total = column_property(
    select([func.coalesce(func.sum(Transline.items * Transline.discount),
                          zero)],
           whereclause=and_(Transline.transid == Transaction.id)).\
        correlate(Transaction.__table__).\
        label('discount_total'),
    deferred=True,
    doc="Transaction lines discount total")

Transaction.age = column_property(
    select([func.coalesce(
        func.current_timestamp() - func.min(Transline.time),
        func.cast("0", Interval))],
           whereclause=and_(Transline.transid == Transaction.id))\
    .correlate(Transaction.__table__)\
    .label('age'),
    deferred=True,
    doc="Transaction age")

Transaction.payments_total = column_property(
    select([func.coalesce(func.sum(Payment.amount), zero)],
           whereclause=and_(Payment.transid == Transaction.id))\
    .correlate(Transaction.__table__)\
    .label('payments_total'),
    deferred=True,
    doc="Payments total")

stocklines_seq = Sequence('stocklines_seq', start=100)
class StockLine(Base, Logged):
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
        lazy='joined',
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
        # if capacity is present it must be greater than zero
        CheckConstraint(
            "capacity IS NULL OR capacity > 0",
            name="capacity_greater_than_zero_constraint"),
        )

    @property
    def logtext(self):
        return self.name

    @property
    def typeinfo(self):
        """Useful information about the line type"""
        if self.linetype == "regular":
            if self.pullthru:
                return "Regular (pullthru {})".format(self.pullthru)
            return "Regular"
        elif self.linetype == "display":
            return "Display (capacity {})".format(self.capacity)
        elif self.linetype == "continuous":
            return "Continuous"
        else:
            return self.linetype

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

    tillweb_viewname = "tillweb-stockline"
    tillweb_argname = "stocklineid"
    def tillweb_nav(self):
        return [("Stock lines", self.get_view_url("tillweb-stocklines")),
                (self.name, self.get_absolute_url())]

    @property
    def ondisplay(self):
        """Number of units of stock on display

        For "Display" stocklines, the total number of units of stock
        on display for sale across all the stock items on sale on this
        line.  For other stocklines, returns None.
        """
        if self.linetype != "display":
            return None
        return sum(sos.ondisplay for sos in self.stockonsale) or Decimal("0.0")
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
        return sum(sos.instock for sos in self.stockonsale) or Decimal("0.0")
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

    @property
    def remaining_str(self):
        """Amount of unsold stock on the stock line, including unit"""
        unit = None
        if self.linetype == "regular":
            if self.stockonsale:
                unit = self.stockonsale[0].stocktype.unit
        else:
            unit = self.stocktype.unit
        if unit:
            return unit.format_qty(self.remaining)

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
            instock_after_move = int(i.size) - newdisplayqty
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
            .filter(StockItem.stockline == None)\
            .options(undefer('remaining'))\
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
                sellqty = min(unallocated, max(ondisplay, Decimal("0.0")))
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

    @classmethod
    def locations(cls, session):
        return [x[0] for x in session.query(distinct(cls.location))\
                .order_by(cls.location).all()]

plu_seq = Sequence('plu_seq')

class PriceLookup(Base, Logged):
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

    tillweb_viewname = "tillweb-plu"
    tillweb_argname = "pluid"
    def tillweb_nav(self):
        return [("Price lookups", self.get_view_url("tillweb-plus")),
                (self.description, self.get_absolute_url())]

suppliers_seq = Sequence('suppliers_seq')

class Supplier(Base, Logged):
    __tablename__ = 'suppliers'
    id = Column('supplierid', Integer, suppliers_seq,
                nullable=False, primary_key=True)
    name = Column(String(60), nullable=False, unique=True)
    tel = Column(String(20))
    email = Column(String(60))
    web = Column(String())
    accinfo = Column(String(), nullable=True, doc="Accounting system info")

    def __str__(self):
        return self.name

    @property
    def logtext(self):
        return self.name

    tillweb_viewname = "tillweb-supplier"
    tillweb_argname = "supplierid"
    def tillweb_nav(self):
        return [("Suppliers", self.get_view_url("tillweb-suppliers")),
                (self.name, self.get_absolute_url())]

    @property
    def accounts_url(self):
        """Accounting system URL for this supplier
        """
        if not self.accinfo:
            return
        s = object_session(self)
        accounts = s.info.get("accounts") if s else None
        if accounts:
            return accounts.url_for_contact(self.accinfo)


deliveries_seq = Sequence('deliveries_seq')

class Delivery(Base, Logged):
    __tablename__ = 'deliveries'
    id = Column('deliveryid', Integer, deliveries_seq,
                nullable=False, primary_key=True)
    supplierid = Column(Integer, ForeignKey('suppliers.supplierid'),
                        nullable=False)
    docnumber = Column(String(40))
    date = Column(Date, nullable=False, server_default=func.current_timestamp())
    checked = Column(Boolean, nullable=False, server_default=literal(False))
    supplier = relationship(Supplier, backref=backref(
        'deliveries', order_by=desc(id)),
                            lazy="joined")
    accinfo = Column(String(), nullable=True, doc="Accounting system info")

    items = relationship("StockItem", order_by="StockItem.id",
                         back_populates="delivery")

    tillweb_viewname = "tillweb-delivery"
    tillweb_argname = "deliveryid"
    def tillweb_nav(self):
        return [("Deliveries", self.get_view_url("tillweb-deliveries")),
                ("{} ({} {})".format(self.id, self.supplier.name, self.date),
                 self.get_absolute_url())]

    @property
    def accounts_url(self):
        """Accounting system URL for this delivery
        """
        if not self.accinfo:
            return
        s = object_session(self)
        accounts = s.info.get("accounts") if s else None
        if accounts:
            return accounts.url_for_bill(self.accinfo)

    def add_items(self, stocktype, stockunit, qty, cost, bestbefore=None):
        description = stockunit.name
        size = stockunit.size
        # If the stockunit allows merging, do so now
        if stockunit.merge and qty > 1:
            description = f"{qty}×{description}"
            size = size * qty
            qty = 1
        costper = (cost / qty).quantize(penny) if cost else None
        remaining_cost = cost
        items = []
        # It's necessary to disable autoflush here, otherwise some of
        # the new StockItem rows may be autoflushed with deliveryid
        # still set to None if sqlalchemy has to issue a query to load
        # stocktype
        with object_session(self).no_autoflush:
            while qty > 0:
                thiscost = remaining_cost if qty == 1 else costper
                remaining_cost = remaining_cost - thiscost if cost else None
                item = StockItem(stocktype=stocktype,
                                 description=description,
                                 size=size,
                                 costprice=thiscost,
                                 bestbefore=bestbefore)
                self.items.append(item)
                items.append(item)
                qty -= 1
        return items

units_seq = Sequence('units_seq')

class Unit(Base, Logged):
    """A unit in which stock is held, and its default quantity for pricing

    Often these will be the same, eg. beer is counted by the "pint"
    and priced per one "pint"; 1 pint is called a "pint".  For some
    types of stock they will be different, eg. wine is counted by the
    "ml" and priced per 750 "ml"; 750ml is called a "wine bottle".

    Stock can be bought in different units.  For example, soft drink
    cartons can be sold by the pint (568ml) but bought by the 1l
    carton (1000ml).  The size of a stock item is stored with the
    item, and default purchase units are described by the StockUnit class.
    """
    __tablename__ = 'unittypes'
    id = Column(Integer, units_seq, nullable=False, primary_key=True)
    # How this unit appears in menus
    description = Column(String(), nullable=False)
    # Name of the fundamental unit, eg. ml, pint
    name = Column(String(), nullable=False)
    # Name of the pricing / stock-keeping unit, singular and plural form
    item_name = Column(String(), nullable=False)
    item_name_plural = Column(String(), nullable=False)
    units_per_item = Column(quantity, nullable=False, default=Decimal("1.0"))
    # This may be a good place to put a stocktake_method column,
    # eg. "by item" or "by stocktype".

    tillweb_viewname = "tillweb-unit"
    tillweb_argname = "unit_id"
    def tillweb_nav(self):
        return [("Units", self.get_view_url("tillweb-units")),
                (self.description, self.get_absolute_url())]

    def format_qty(self, qty):
        if qty < self.units_per_item and qty != 0:
            return "{} {}".format(qty, self.name)
        n = self.item_name if qty == self.units_per_item \
            else self.item_name_plural
        return "{:0.1f} {}".format(qty / self.units_per_item, n)

    def __str__(self):
        return "%s" % (self.name,)

stockunits_seq = Sequence('stockunits_seq')

class StockUnit(Base, Logged):
    """A unit in which stock is bought

    This class describes default units in which stock is bought, for
    example a "firkin" is 72 "pints" and a "1l carton of soft drink"
    is 1000 "ml".

    Actual sizes and item descriptions are stored per StockItem.
    """
    __tablename__ = 'stockunits'
    id = Column(Integer, stockunits_seq, nullable=False, primary_key=True)
    name = Column(String(), nullable=False)
    unit_id = Column(Integer, ForeignKey('unittypes.id'), nullable=False)
    size = Column(quantity, nullable=False)
    merge = Column(Boolean, nullable=False, default=False,
                   server_default=literal(False))
    unit = relationship(Unit, backref=backref('stockunits', order_by=size))

    tillweb_viewname = "tillweb-stockunit"
    tillweb_argname = "stockunit_id"
    def tillweb_nav(self):
        return [("Item sizes", self.get_view_url("tillweb-stockunits")),
                (self.name, self.get_absolute_url())]

    def __str__(self):
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
    abv = Column(Numeric(3, 1))
    unit_id = Column(Integer, ForeignKey('unittypes.id'), nullable=False)
    saleprice = Column(money, nullable=True) # inc VAT
    pricechanged = Column(DateTime, nullable=True) # Last time price was changed
    department = relationship(Department, lazy="joined")
    unit = relationship(Unit, lazy="joined",
                        backref=backref("stocktypes", order_by=id))

    __table_args__ = (
        UniqueConstraint('dept', 'manufacturer', 'name', 'abv', 'unit_id',
                         name="stocktypes_ambiguity_key"),
    )

    @hybrid_property
    def fullname(self):
        return self.manufacturer + ' ' + self.name

    tillweb_viewname = "tillweb-stocktype"
    tillweb_argname = "stocktype_id"
    def tillweb_nav(self):
        return [("Stock types", self.get_view_url("tillweb-stocktype-search")),
                (str(self), self.get_absolute_url())]

    def __str__(self):
        return "%s %s" % (self.manufacturer, self.name)

    @property
    def abvstr(self):
        if self.abv:
            return "{}%".format(self.abv)
        return ""

    @property
    def pricestr(self):
        if self.saleprice is not None:
            return "{}/{}".format(self.saleprice, self.unit.item_name)
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
            ]
        return [self.fullname]

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

    def __str__(self):
        return "%s" % self.description

stock_seq = Sequence('stock_seq')
class StockItem(Base, Logged):
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
    <--------------------------- size --------------------------> = 10
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
    description = Column(String(), nullable=False)
    size = Column(quantity, CheckConstraint("size > 0.0"), nullable=False)
    costprice = Column(money) # ex VAT
    onsale = Column(DateTime)
    finished = Column(DateTime)
    finishcode_id = Column('finishcode', String(8),
                           ForeignKey('stockfinish.finishcode'))
    bestbefore = Column(Date)
    delivery = relationship(Delivery, back_populates="items")
    stocktype = relationship(StockType, backref=backref('items', order_by=id))
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

        If the item is finished, gives the shelf life at the time it
        was finished; otherwise gives the shelf life now.

        None if the best-before date is not known.  Negative if the
        item is/was out of date.
        """
        if self.bestbefore is None:
            return None
        return (self.bestbefore - (self.finished or datetime.date.today())).days
    @property
    def displayqty_or_zero(self):
        """displayqty is always null when a stockline has no display
        capacity.

        On lines with a display capacity, a displayqty of null should
        be read as zero.

        This is needed for compatibility with legacy till databases.
        """
        if self.displayqty is None:
            return Decimal("0.0")
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
        return self.size - self.displayqty_or_zero

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

    tillweb_viewname = "tillweb-stock"
    tillweb_argname = "stockid"
    def tillweb_nav(self):
        return self.delivery.tillweb_nav() + [
            ("Item {} ({} {})".format(
                self.id, self.stocktype.manufacturer, self.stocktype.name),
             self.get_absolute_url())]

    def __str__(self):
        return "<StockItem({})>".format(self.id)

Delivery.costprice = column_property(
    select([
        case(
            [
                (func.count(StockItem.costprice) != func.count('*'), None),
            ],
            else_=func.sum(StockItem.costprice))
    ])
    .correlate(Delivery.__table__)
    .where(StockItem.deliveryid == Delivery.id)
    .label('costprice'),
    deferred=True,
    doc="Cost ex-VAT of this delivery")

class AnnotationType(Base):
    __tablename__ = 'annotation_types'
    id = Column('atype', String(8), nullable=False, primary_key=True)
    description = Column(String(20), nullable=False)
    def __str__(self):
        return "%s" % (self.description,)

stock_annotation_seq = Sequence('stock_annotation_seq');

class StockAnnotation(Base, Logged):
    __tablename__ = 'stock_annotations'
    id = Column(Integer, stock_annotation_seq, nullable=False, primary_key=True)
    stockid = Column(Integer, ForeignKey('stock.stockid', ondelete='CASCADE'),
                     nullable=False)
    atype = Column(String(8), ForeignKey('annotation_types.atype'),
                   nullable=False)
    time = Column(DateTime, nullable=False,
                  server_default=func.current_timestamp())
    text = Column(String(), nullable=False)
    user_id = Column('user', Integer, ForeignKey('users.id'), nullable=True,
                     doc="User who created this annotation")
    stockitem = relationship(StockItem, backref=backref(
        'annotations', passive_deletes=True, order_by=time))
    type = relationship(AnnotationType)
    user = relationship(User, backref=backref("annotations", order_by=time))

class RemoveCode(Base, Logged):
    __tablename__ = 'stockremove'
    id = Column('removecode', String(8), nullable=False, primary_key=True)
    reason = Column(String(80))
    def __str__(self):
        return "%s" % (self.reason,)

stockout_seq = Sequence('stockout_seq')

class StockOut(Base, Logged):
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
    select([StockItem.size
            - func.coalesce(func.sum(StockOut.qty), text("0.0"))]).\
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
                    StockItem.size -
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
    keycap = Column(String(), nullable=False, server_default=literal(''))
    css_class = Column(String(), nullable=False, server_default=literal(''))

add_ddl(KeyCap.__table__, """
CREATE OR REPLACE FUNCTION notify_keycap_change() RETURNS trigger AS $$
DECLARE
BEGIN
  PERFORM pg_notify('keycaps', NEW.keycode);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER keycap_changed
  AFTER INSERT OR UPDATE ON keycaps
  FOR EACH ROW EXECUTE PROCEDURE notify_keycap_change();
""", """
DROP TRIGGER keycap_changed ON keycaps;
DROP FUNCTION notify_keycap_change();
""")

class StockLineTypeLog(Base):
    """Association table for stocklines to stocktypes

    This table records all the stocktypes that have been used on each
    stockline.  This information is used to sort sensible defaults to
    the top of the list when displaying lists of stock that can be put
    on sale on a stockline.
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

log_seq = Sequence('log_seq')

class LogEntry(Base):
    """A user did something, possibly involving some other tables
    """
    __tablename__ = "log"
    id = Column(Integer, log_seq, primary_key=True)
    time = Column(DateTime, nullable=False,
                  server_default=func.current_timestamp())
    sourceaddr = Column(postgresql.INET)
    source = Column(String(), nullable=False)
    user_id = Column('user', Integer, ForeignKey(
        'users.id', name="log_loguser_fkey"), nullable=False)
    loguser = relationship(User, foreign_keys=[user_id],
                           backref=backref("activity", order_by=time))
    description = Column(String(), nullable=False)

    tillweb_viewname = "tillweb-logentry"
    tillweb_argname = "logid"

    # These models subclass the Logged class; we need to generate columns
    # and foreign key constraints that link to their primary keys
    _logged_models = [x for x in globals().values()
                      if isclass(x) and x != Logged and issubclass(x, Logged)]

    # A reference looks like [description]Model(pk1,pk2,...)
    # If description is blank, the primary keys will be used instead.
    _ref_re = re.compile(fr"""
            \[(.*?)\]                                        # description
            ({'|'.join(m.__name__ for m in _logged_models)}) # model
            \((.*?)\)                                        # primary keys
        """, re.VERBOSE)

    @staticmethod
    def _str_to_date(ds):
        return datetime.date(*(int(x) for x in ds.split('-')))

    @classmethod
    def _match_to_model(cls, match, session):
        """Return model and model instance when passed a _ref_re match

        If no instance can be found, returns model, None
        """
        modelname = match.group(2)
        keys = match.group(3).split(',')
        model = globals()[modelname]
        pk_types = [x.type.python_type
                    if x.type.python_type != datetime.date
                    else cls._str_to_date
                    for x in inspect(model).primary_key]
        if len(keys) != len(pk_types):
            return model, None
        obj = None
        obj = session.query(model).get(
            c(k) for c, k in zip(pk_types, keys))
        return model, obj

    def update_refs(self, session):
        # Look for object references in the description and add links
        # to them.  We're going to use .get() a lot here, which is ok
        # because the objects referred to are guaranteed to be in the
        # session.
        for match in self._ref_re.finditer(self.description):
            model, obj = self._match_to_model(match, session)
            if obj:
                setattr(self, model._log_relationship_name(), obj)

    def as_text(self):
        """Return description with object references converted to text
        """
        return self._ref_re.sub(
            lambda x: x.group(1) if x.group(1) else x.group(3),
            self.description)

    def as_html(self):
        """Return description with object references converted to links
        """
        def make_link(match):
            model, obj = self._match_to_model(match, object_session(self))
            linktext = match.group(1) if match.group(1) else match.group(3)
            if obj:
                return f'<a href="{obj.get_absolute_url()}">{linktext}</a>'
            else:
                return linktext
        return self._ref_re.sub(make_link, self.description)

    def __str__(self):
        return self.as_text()

_constraints = []

# Add the columns, foreign key constraints and relationships to
# LogEntry for all models that subclassed Logged
for _m in LogEntry._logged_models:
    _relationship_name = _m._log_relationship_name()
    _primary_keys = list(inspect(_m).primary_key)
    _cols = []
    for _num, _key in enumerate(_primary_keys):
        _colname = f"{_key.table.name}_id{_num if len(_primary_keys) > 1 else ''}"
        _colval = Column(_colname, _key.type, nullable=True)
        setattr(LogEntry, _colname, _colval)
        _cols.append(_colval)
    _constraints.append(ForeignKeyConstraint(
        _cols, _primary_keys, ondelete="SET NULL",
        name=f"log_{_relationship_name}_fkey"))
    setattr(LogEntry, _relationship_name, relationship(
        _m, foreign_keys=_cols, backref=backref(
            "logs", order_by="LogEntry.time")))
LogEntry.__table_args__ = tuple(_constraints)

add_ddl(LogEntry.__table__, """
CREATE OR REPLACE FUNCTION notify_log_entry() RETURNS trigger AS $$
DECLARE
BEGIN
  PERFORM pg_notify('log', NEW.id::text);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER log_entry
  AFTER INSERT OR UPDATE ON log
  FOR EACH ROW EXECUTE PROCEDURE notify_log_entry();
""", """
DROP TRIGGER log_entry ON log;
DROP FUNCTION notify_log_entry();
""")

# Add indexes here
Index('translines_transid_key', Transline.transid)
Index('payments_transid_key', Payment.transid)
Index('transactions_sessionid_key', Transaction.sessionid)
Index('stock_annotations_stockid_key', StockAnnotation.stockid)
Index('stockout_stockid_key', StockOut.stockid)
Index('stockout_translineid_key', StockOut.translineid)
Index('translines_time_key', Transline.time)

# The "find free drinks on this day" function is speeded up
# considerably by an index on stockout.time::date.
Index('stockout_date_key', func.cast(StockOut.time, Date))

foodorder_seq = Sequence('foodorder_seq', metadata=metadata)

# Very simple refusals log for EMF 2018.  Log templates are in config.
refusals_log_seq = Sequence('refusals_log_seq');
class RefusalsLog(Base):
    __tablename__ = 'refusals_log'
    id = Column(Integer, refusals_log_seq, nullable=False, primary_key=True)
    user_id = Column('user', Integer, ForeignKey('users.id'), nullable=False,
                     doc="User who made this log entry")
    time = Column(DateTime, nullable=False,
                  server_default=func.current_timestamp())
    terminal = Column('terminal', String(), nullable=False)
    details = Column('details', String(), nullable=False)
    user = relationship(User, backref=backref("refusals", order_by=time))
