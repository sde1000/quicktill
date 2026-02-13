from sqlalchemy.orm import declarative_base, declared_attr
from sqlalchemy import Column, Integer, String, DateTime, Date
from sqlalchemy import LargeBinary
from sqlalchemy.dialects import postgresql
from sqlalchemy import ForeignKey, Numeric, CHAR, Boolean, Text, Interval
from sqlalchemy.schema import Sequence, Index, MetaData, DDL
from sqlalchemy.schema import CheckConstraint, Table
from sqlalchemy.schema import UniqueConstraint
from sqlalchemy.schema import ForeignKeyConstraint
from sqlalchemy.sql.expression import text, case, literal
from sqlalchemy.orm import relationship, backref, object_session
from sqlalchemy.orm import joinedload, lazyload
from sqlalchemy.orm import contains_eager, column_property
from sqlalchemy.orm import undefer_group
from sqlalchemy.orm import aliased
from sqlalchemy.orm import deferred
from sqlalchemy.orm.collections import attribute_mapped_collection
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql import select, func, desc
from sqlalchemy import event
from sqlalchemy import distinct
from sqlalchemy import inspect

import datetime
import hashlib
from decimal import Decimal
from inspect import isclass
import re
import warnings

# Configuration of money
money_max_digits = 10
money_decimal_places = 2

# Configuration of quantities
qty_max_digits = 8
qty_decimal_places = 1

# Alcohol By Volume
abv_max_digits = 3
abv_decimal_places = 1

# Used for quantization of money
zero = Decimal(f"0.{'0' * money_decimal_places}")
penny = Decimal(f"0.{'0' * (money_decimal_places - 1)}1")

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

abv = Numeric(abv_max_digits, abv_decimal_places)
min_abv_value = Decimal("0." + "0" * abv_decimal_places)
max_abv_value = Decimal("9" * (abv_max_digits - abv_decimal_places)
                        + "." + "9" * abv_decimal_places)

metadata = MetaData()


# Methods common to all models
class Base:
    def get_view_url(self, viewname, *args, **kwargs):
        s = object_session(self)
        reverse = s.info["reverse"]
        return reverse(viewname, args=args, kwargs=kwargs)

    def get_absolute_url(self):
        return self.get_view_url(self.tillweb_viewname,
                                 **{self.tillweb_argname: self.id})

    # repr() of an instance is used in log entries.
    def __repr__(self):
        insp = inspect(self)
        if insp.identity:
            return f"{self.__class__.__name__}"\
                f"({','.join(str(x) for x in insp.identity)})"
        else:
            return f"{self.__class__.__name__}(no-identity)"

    # The __str__ method should be used to return a description of the
    # instance suitable for use in sentences like "session {s}" or
    # "the {d} department".  If it's sensible to refer to an instance
    # by name or description instead of primary key, override this
    # method.
    def __str__(self):
        insp = inspect(self)
        if insp.identity:
            return ','.join(str(x) for x in insp.identity)
        return "<unknown>"


Base = declarative_base(metadata=metadata, cls=Base)


# Use this class as a mixin to request a foreign key relationship from
# the 'log' table.  Log entries are accessible using the 'logs'
# relationship.
class Logged:
    # What to use as the 'text' part of a log reference?  When empty,
    # the primary keys are used by default.  Override in models as
    # required.
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
    show_vat_breakdown = Column(Boolean(), nullable=False, default=False)

    def __str__(self):
        return self.abbrev

    @property
    def logtext(self):
        return self.abbrev


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
    description = Column(String(), nullable=False, server_default="None")


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
    """A payment method
    """
    __tablename__ = 'paytypes'
    paytype = Column(String(8), nullable=False, primary_key=True)
    description = Column(String(10), nullable=False)
    order = Column(Integer, doc="Hint for sorting")
    driver_name = Column(
        String(), nullable=False, server_default='',
        doc="Name of driver code for this payment type")
    mode = Column(
        String(), nullable=False, server_default='disabled',
        doc="How the payment method is currently used")
    config = Column(
        Text(), doc="Payment method configuration; format depends "
        "on chosen driver")
    state = Column(
        Text(), doc="Payment method state; format depends on chosen driver, "
        "not expected to be edited by users, only user option should be "
        "reset to blank")
    payments_account = Column(
        String(), nullable=False, server_default='',
        doc="Name of account in accounting system to receive payments")
    fees_account = Column(
        String(), nullable=False, server_default='',
        doc="Name of account in accounting system for fees deducted from "
        "payments")
    payment_date_policy = Column(
        String(), nullable=False, server_default='same-day',
        doc="How to calculate the date the payment will arrive "
        "in the payments account")

    __table_args__ = (
        CheckConstraint(
            "mode='disabled' OR mode='active' OR mode='total_only'",
            name="paytype_mode_constraint"),
        # A paytype with no driver can only be disabled
        CheckConstraint(
            "NOT(driver_name='') OR (mode='disabled')",
            name="paytype_absent_driver_constraint"),
    )

    def __str__(self):
        return self.description

    modes = {
        'disabled': "Disabled",
        'total_only': "Total entry only",
        'active': "Active",
    }

    @property
    def mode_display(self):
        return self.modes[self.mode]

    # This should be set to the appropriate payment driver factory
    # before the `driver` property is accessed
    driver_factory = None

    @property
    def driver(self):
        if not hasattr(self, '_driver'):
            self._driver = self.driver_factory()
        return self._driver

    @property
    def active(self):
        """Can the payment type be used to create new payments?
        """
        return self.mode == "active" and self.driver.config_valid

    @property
    def id(self):
        # Needed for get_absolute_url
        return self.paytype

    tillweb_viewname = "tillweb-paytype"
    tillweb_argname = "paytype"

    def tillweb_nav(self):
        return [("Payment methods", self.get_view_url("tillweb-paytypes")),
                (self.description, self.get_absolute_url())]


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
    # XXX starttime and endtime are currently stored in
    # localtime. They should be stored with timezone info.
    starttime = Column(DateTime, nullable=False)
    endtime = Column(DateTime)
    date = Column('sessiondate', Date, nullable=False)
    accinfo = Column(String(), nullable=True, doc="Accounting system info")

    def __init__(self, date):
        self.date = date
        self.starttime = datetime.datetime.now()

    tillweb_viewname = "tillweb-session"
    tillweb_argname = "sessionid"

    def tillweb_nav(self):
        return [("Sessions", self.get_view_url("tillweb-sessions")),
                (f"{self.id} ({self.date})",
                 self.get_absolute_url())]

    incomplete_transactions = relationship(
        "Transaction",
        viewonly=True,
        primaryjoin="and_(Transaction.sessionid==Session.id,"
        "Transaction.closed==False)")

    meta = relationship("SessionMeta",
                        collection_class=attribute_mapped_collection('key'),
                        back_populates="session",
                        passive_deletes=True,
                        cascade="all,delete-orphan")

    def set_meta(self, key, val):
        val = str(val)
        if key in self.meta:
            o = self.meta[key]
            o.value = val
        else:
            self.meta[key] = SessionMeta(
                key=key,
                value=val)

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
        return object_session(self)\
            .query(Department, func.sum(
                Transline.items * Transline.amount).label("total"))\
            .select_from(Session)\
            .filter(Session.id == self.id)\
            .join(Transaction)\
            .join(Transline)\
            .join(Department)\
            .order_by(Department.id)\
            .group_by(Department)\
            .all()

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
        return object_session(self)\
            .query(User, func.sum(Transline.items), func.sum(
                Transline.items * Transline.amount))\
            .filter(Transaction.sessionid == self.id)\
            .join(Transline)\
            .join(Transaction)\
            .order_by(desc(func.sum(
                Transline.items * Transline.amount)))\
            .group_by(User).all()

    @property
    def payment_totals(self):
        "Transactions broken down by payment type."
        return object_session(self)\
            .query(PayType, func.sum(Payment.amount))\
            .select_from(Session)\
            .filter(Session.id == self.id)\
            .join(Transaction)\
            .join(Payment)\
            .join(PayType)\
            .group_by(PayType)\
            .all()

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
        vt = object_session(self)\
            .query(VatBand, func.sum(Transline.items * Transline.amount))\
            .select_from(Session)\
            .filter(Session.id == self.id)\
            .join(Transaction)\
            .join(Transline)\
            .join(Department)\
            .join(VatBand)\
            .order_by(VatBand.band)\
            .group_by(VatBand)\
            .all()
        vt = [(a.at(self.date), b) for a, b in vt]
        return [(a, b, a.inc_to_exc(b), a.inc_to_vat(b)) for a, b in vt]

    # It may become necessary to add a further query here that returns
    # transaction lines broken down by Business.  Must take into
    # account multiple VAT rates per business - probably best to do
    # the summing client side using the methods in the VatRate object.

    @property
    def stock_sold(self):
        "Returns a list of (StockType, quantity) tuples."
        return object_session(self)\
            .query(StockType, func.sum(StockOut.qty))\
            .join(Unit)\
            .join(StockItem)\
            .join(StockOut)\
            .join(Transline)\
            .join(Transaction)\
            .filter(Transaction.sessionid == self.id)\
            .options(lazyload(StockType.department))\
            .options(contains_eager(StockType.unit))\
            .group_by(StockType, Unit)\
            .order_by(StockType.dept_id, desc(func.sum(StockOut.qty)))\
            .all()

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
    RAISE EXCEPTION 'there is already an open session'
          USING ERRCODE = 'integrity_constraint_violation';
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


class SessionMeta(Base):
    """Metadata on a session

    Acts as a key/value store per session.  Only one instance of a
    key can exist per session: the primary key for this table is
    (session_id,key).

    If the session is deleted, all its metadata is deleted too.

    Session metadata is expected to be used by register plugins.
    """
    __tablename__ = 'session_meta'
    session_id = Column('sessionid', Integer,
                        ForeignKey('sessions.sessionid',
                                   ondelete='CASCADE'),
                        primary_key=True, nullable=False)
    key = Column(String(), nullable=False, primary_key=True)
    value = Column(String(), nullable=False)

    session = relationship(Session, back_populates='meta')


class SessionTotal(Base):
    """Actual total recorded for a payment type in a Session

    The actual amount taken through this payment type is recorded as
    'amount'. If the payment will be received net of fees, the amount
    of fees to be deducted is recorded as 'fees'. The amount expected
    to arrive in the bank account is 'amount - fees'.

    Negative amounts are possible, for example when a payment type has
    issued more refunds than it has taken payments. It is also
    possible for the overall total for a session to be negative.

    Negative fees may apply, for example where card payments have been
    refunded and their fees have been refunded as well.
    """
    __tablename__ = 'sessiontotals'
    sessionid = Column(Integer, ForeignKey('sessions.sessionid'),
                       primary_key=True)
    paytype_id = Column('paytype', String(8), ForeignKey('paytypes.paytype'),
                        primary_key=True)
    amount = Column(money, nullable=False)
    fees = Column(money, nullable=False, server_default=literal(zero))
    session = relationship(Session, backref=backref(
        'actual_totals', order_by=desc(paytype_id)))
    paytype = relationship(PayType)

    @hybrid_property
    def payment_amount(self):
        return self.amount - self.fees


Session.actual_total = column_property(
    select(func.sum(SessionTotal.amount))
    .where(SessionTotal.sessionid == Session.id)
    .correlate(Session.__table__)
    .label('actual_total'),
    deferred=True,
    doc="Actual recorded total")


transactions_seq = Sequence('transactions_seq')


class Transaction(Base, Logged):
    __tablename__ = 'transactions'
    id = Column('transid', Integer, transactions_seq, nullable=False,
                primary_key=True)

    # Deferred transactions have a null sessionid
    sessionid = Column(Integer, ForeignKey('sessions.sessionid'),
                       nullable=True)
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

    session = relationship(
        Session, backref=backref('transactions', order_by=id))

    meta = relationship("TransactionMeta",
                        collection_class=attribute_mapped_collection('key'),
                        back_populates="transaction",
                        passive_deletes=True,
                        cascade="all,delete-orphan")

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

    def related_transaction_ids(self):
        """A set of transaction IDs related to this transaction

        Currently derived by following chains of void transaction
        lines, but may be extended in the future (for example if we
        implement a "related transactions" table).

        Transaction IDs are not guaranteed to exist, for example if a
        related transaction has been merged.

        The returned set of transaction IDs will always include the ID
        of this transaction.
        """
        s = object_session(self)

        # We are trying to build something like the following CTE:

        # WITH RECURSIVE related(transid) AS (
        #   SELECT self.id
        #   UNION
        #   SELECT voided.transid FROM related
        #   INNER JOIN translines AS tl ON tl.transid=related.transid
        #   INNER JOIN translines AS voided ON voided.voided_by=tl.translineid
        # ) SELECT transid FROM related;

        trans_line = aliased(Transline, name="tl")
        voided_line = aliased(Transline, name="voided")
        rel = s.query(literal(self.id).label("transid"))\
               .cte("related", recursive=True)
        rec = s.query(voided_line.transid)\
               .select_from(rel)\
               .join(trans_line, trans_line.transid == rel.c.transid)\
               .join(voided_line, voided_line.voided_by_id == trans_line.id)
        return set(t.transid for t in s.query(rel.union(rec)).all())

    @property
    def balance(self):
        """Transaction balance
        """
        return self.total - self.payments_total

    @property
    def state(self):
        return "closed" if self.closed else "open"

    tillweb_viewname = "tillweb-transaction"
    tillweb_argname = "transid"

    def tillweb_nav(self):
        if self.session:
            return self.session.tillweb_nav() \
                + [(f"Transaction {self.id}", self.get_absolute_url())]
        return [("Transactions",
                 self.get_view_url("tillweb-transactions")),
                (str(self), self.get_absolute_url())]

    # age is now a column property, defined below

    def set_meta(self, key, val):
        val = str(val)
        if key in self.meta:
            o = self.meta[key]
            o.value = val
        else:
            self.meta[key] = TransactionMeta(
                key=key,
                value=val)


class TransactionMeta(Base):
    """Metadata on a transaction

    Acts as a key/value store per transaction.  Only one instance of a
    key can exist per transaction: the primary key for this table is
    (trans_id,key).

    If the transaction is deleted, all its metadata is deleted too.

    Transaction metadata is expected to be used by register plugins.
    """
    __tablename__ = 'transaction_meta'
    trans_id = Column('transid', Integer,
                      ForeignKey('transactions.transid',
                                 ondelete='CASCADE'),
                      primary_key=True, nullable=False)
    key = Column(String(), nullable=False, primary_key=True)
    value = Column(String(), nullable=False)

    transaction = relationship(Transaction, back_populates='meta')


add_ddl(Transaction.__table__, """
CREATE OR REPLACE FUNCTION check_transaction_balances() RETURNS trigger AS $$
BEGIN
  IF NEW.closed=true
    AND (SELECT COALESCE(sum(amount*items), 0.00) FROM translines
      WHERE transid=NEW.transid)!=
      (SELECT COALESCE(sum(amount), 0.00) FROM payments WHERE transid=NEW.transid)
  THEN RAISE EXCEPTION 'transaction %% does not balance', NEW.transid
       USING ERRCODE = 'integrity_constraint_violation';
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
""")  # noqa: E501

add_ddl(Transaction.__table__, """
CREATE OR REPLACE FUNCTION check_no_pending_payments() RETURNS trigger AS $$
BEGIN
  IF NEW.closed=true
    AND EXISTS (SELECT * FROM payments WHERE pending AND transid=NEW.transid)
  THEN RAISE EXCEPTION 'transaction %% has pending payments', NEW.transid
       USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;
CREATE CONSTRAINT TRIGGER close_only_if_no_pending_payments
  AFTER INSERT OR UPDATE ON transactions
  FOR EACH ROW EXECUTE PROCEDURE check_no_pending_payments();
""", """
DROP TRIGGER close_only_if_no_pending_payments ON transactions;
DROP FUNCTION check_no_pending_payments();
""")


register_seq = Sequence('register_seq')


class Register(Base):
    """A register instance

    An entry is made in this table each time the register starts
    up. References to this table are then used to ensure a user is
    only active on at most one register at a time.
    """
    __tablename__ = 'registers'
    id = Column(Integer, register_seq, nullable=False, primary_key=True)
    version = Column(
        String(), nullable=False, doc="Software version of the register")
    startup_time = Column(DateTime(), nullable=False,
                          server_default=func.current_timestamp())
    config_name = Column(String(), nullable=False)
    terminal_name = Column(String(), nullable=False)

    users = relationship('User', back_populates='register')


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
    register_id = Column(Integer, ForeignKey('registers.id'), nullable=True)
    message = Column(String(), nullable=True,
                     doc="Message to present to user on their next keypress")
    last_seen = Column(DateTime)
    password = Column(String(), nullable=True)
    groups = relationship("Group", secondary="group_grants", backref="users")
    permissions = relationship(
        "Permission",
        secondary="join(group_membership, group_grants, "
        "group_membership.c.group == group_grants.c.group)"
        ".join(Permission, group_membership.c.permission == Permission.id)",
        viewonly=True)
    transaction = relationship(Transaction, backref=backref(
        'user', uselist=False))
    register = relationship(Register)

    tillweb_viewname = "tillweb-till-user"
    tillweb_argname = "userid"

    def tillweb_nav(self):
        return [("Users", self.get_view_url("tillweb-till-users")),
                (self.fullname, self.get_absolute_url())]

    def __str__(self):
        return self.fullname

    def log_out(self):
        for token in self.tokens:
            token.last_successful_login = None

    @property
    def logtext(self):
        return self.fullname


# When the 'transid' or 'register' column of a user is changed, send
# notification 'user_register' with the user ID as payload. This
# enables registers to detect the user arriving at a different
# register, or the user's transaction being taken over by another
# user.
add_ddl(User.__table__, """
CREATE OR REPLACE FUNCTION notify_user_change() RETURNS trigger AS $$
DECLARE
BEGIN
  IF NEW.transid IS DISTINCT FROM OLD.transid
    OR NEW.register_id IS DISTINCT FROM OLD.register_id THEN
    PERFORM pg_notify('user_register', CAST(NEW.id AS text));
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER user_changed
  AFTER UPDATE ON users
  FOR EACH ROW EXECUTE PROCEDURE notify_user_change();
""", """
DROP TRIGGER user_changed ON users;
DROP FUNCTION notify_user_change();
""")


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
    last_successful_login = Column(DateTime, nullable=True)
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
""")  # noqa: E501

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
""")  # noqa: E501


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
    text = Column(Text, nullable=False)
    time = Column(DateTime, nullable=False,
                  server_default=func.current_timestamp())
    user_id = Column('user', Integer, ForeignKey('users.id'), nullable=True,
                     doc="User who created this payment")
    source = Column(String(), nullable=False, server_default="default",
                    doc="On which terminal was this payment created?")
    pending = Column(Boolean, nullable=False, server_default=literal(False))
    transaction = relationship(
        Transaction,
        backref=backref('payments', order_by=id, cascade="all, delete-orphan",
                        passive_deletes=True))
    paytype = relationship(PayType)
    user = relationship(User)

    meta = relationship("PaymentMeta",
                        collection_class=attribute_mapped_collection('key'),
                        back_populates="payment",
                        passive_deletes=True,
                        cascade="all,delete-orphan")

    __table_args__ = (
        # If payment is pending, amount must be zero
        CheckConstraint(
            "(NOT pending) OR (amount = 0.00)",
            name="pending_payment_constraint"),
    )

    def set_meta(self, key, val):
        val = str(val)
        if key in self.meta:
            o = self.meta[key]
            o.value = val
        else:
            self.meta[key] = PaymentMeta(
                key=key,
                value=val)

    tillweb_viewname = "tillweb-payment"
    tillweb_argname = "paymentid"

    def tillweb_nav(self):
        return self.transaction.tillweb_nav() \
            + [(f"Payment {self.id}", self.get_absolute_url())]


class PaymentMeta(Base):
    """Metadata on a payment

    Acts as a key/value store per payment.  Only one instance of a
    key can exist per payment: the primary key for this table is
    (paymentid,key).

    If the payment is deleted, all its metadata is deleted too.

    Payment metadata is expected to be used by payment methods.
    """
    __tablename__ = 'payment_meta'
    payment_id = Column('paymentid', Integer,
                        ForeignKey('payments.paymentid',
                                   ondelete='CASCADE'),
                        primary_key=True, nullable=False)
    key = Column(String(), nullable=False, primary_key=True)
    value = Column(String(), nullable=False)

    payment = relationship(Payment, back_populates='meta')


add_ddl(Payment.__table__, """
CREATE OR REPLACE FUNCTION check_modify_closed_trans_payment() RETURNS trigger AS $$
BEGIN
  IF (SELECT closed FROM transactions WHERE transid=NEW.transid)=true
  THEN RAISE EXCEPTION 'attempt to modify closed transaction %% payment', NEW.transid
             USING ERRCODE = 'integrity_constraint_violation';
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
""")  # noqa: E501


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
    minabv = Column(abv, CheckConstraint("minabv >= 0.0"),
                    nullable=True, doc="Minimum ABV of "
                    "stock types in this department")
    maxabv = Column(abv, CheckConstraint("maxabv >= 0.0"),
                    nullable=True, doc="Maximum ABV of "
                    "stock types in this department")
    sales_account = Column(
        String(), nullable=False, server_default='',
        doc="Name of account in accounting system for sales")
    purchases_account = Column(
        String(), nullable=False, server_default='',
        doc="Name of account in accounting system for purchases")

    vat = relationship(VatBand)

    def __str__(self):
        return self.description

    @property
    def logtext(self):
        return f"{self.id} ('{self.description}')"

    tillweb_viewname = "tillweb-department"
    tillweb_argname = "departmentid"

    def tillweb_nav(self):
        return [("Departments", self.get_view_url("tillweb-departments")),
                (f"{self.id}. {self.description}",
                 self.get_absolute_url())]


class TransCode(Base):
    __tablename__ = 'transcodes'
    code = Column('transcode', CHAR(1), nullable=False, primary_key=True)
    description = Column(String(20), nullable=False)

    def __str__(self):
        return self.description


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
    discount = Column(
        money, CheckConstraint("discount >= 0.00"),
        nullable=False, server_default=literal(zero),
        doc="Amount of discount applied to this transaction line")
    discount_name = Column(String(), nullable=True)
    source = Column(String(), nullable=False, server_default="default",
                    doc="On which terminal was this transaction line created?")
    protected = Column(Boolean, nullable=False, server_default=literal(False),
                       doc="Is this transaction line protected from deletion?")

    __table_args__ = (
        # If discount is zero, discount_name must be null
        # If discount is not zero, discount_name must not be null
        CheckConstraint(
            "(discount = 0.00) = (discount_name IS NULL)",
            name="discount_name_constraint"),
    )

    # The original_amount instance attribute may be accessed before
    # the instance is committed to the database, and at this point
    # self.discount may be None; treat this as zero
    @hybrid_property
    def original_amount(self):
        """The original amount of the transaction line before any discounts
        """
        return self.amount + (self.discount or zero)

    # The original_amount class attribute relies on amount and
    # discount having nullable=False
    @original_amount.expression
    def original_amount(cls):
        return cls.amount + cls.discount

    transaction = relationship(
        Transaction,
        backref=backref('lines', order_by=id, cascade="all, delete-orphan",
                        passive_deletes=True))
    department = relationship(Department)
    user = relationship(User)
    voided_by = relationship(
        "Transline", remote_side=[id], uselist=False,
        backref=backref('voids', uselist=False, passive_deletes=True))

    meta = relationship("TranslineMeta",
                        collection_class=attribute_mapped_collection('key'),
                        back_populates="transline",
                        passive_deletes=True,
                        cascade="all,delete-orphan")

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
            + [(f"Line {self.id}{' (VOIDED)' if self.voided_by else ''}",
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

    def void(self, transaction, user, source):
        """Void this transaction line

        Create a new transaction line in the specified transaction
        (not necessarily the same as this line's transaction) that
        voids this line and return it.

        The new transaction line is not automatically placed in the
        ORM session; the caller must do this if desired.

        If this transaction line has already been voided, returns
        None.
        """
        if self.voided_by:
            return
        v = Transline(transaction=transaction, items=-self.items,
                      amount=self.amount, discount=self.discount,
                      discount_name=self.discount_name,
                      department=self.department,
                      user=user, transcode='V', text=self.text,
                      source=source)
        self.voided_by = v
        for stockout in self.stockref:
            v.stockref.append(StockOut(
                stockitem=stockout.stockitem, qty=-stockout.qty,
                removecode=stockout.removecode))
        return v

    def set_meta(self, key, val):
        val = str(val)
        if key in self.meta:
            o = self.meta[key]
            o.value = val
        else:
            self.meta[key] = TranslineMeta(
                key=key,
                value=val)


class TranslineMeta(Base):
    """Metadata on a transaction line

    Acts as a key/value store per transaction line.  Only one instance
    of a key can exist per transaction line: the primary key for this
    table is (transline_id,key).

    If the transaction line is deleted, all its metadata is deleted
    too.

    Transaction line metadata is expected to be used by register plugins.
    """
    __tablename__ = 'transline_meta'
    transline_id = Column('translineid', Integer,
                          ForeignKey('translines.translineid',
                                     ondelete='CASCADE'),
                          primary_key=True, nullable=False)
    key = Column(String(), nullable=False, primary_key=True)
    value = Column(String(), nullable=False)

    transline = relationship(Transline, back_populates='meta')


# This trigger permits null columns (user or voided_by) to be set to
# not-null in closed transactions but subsequently prevents
# modification. Note: any attempt to change discount_name between null
# and not-null will be caught by the discount_name_constraint because
# it would need to involve a change of discount between zero and
# non-zero.
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
      OR OLD.discount != NEW.discount
      OR OLD.discount_name != NEW.discount_name
      OR OLD.source != NEW.source
      OR OLD.text != NEW.text)
    THEN RAISE EXCEPTION 'attempt to modify closed transaction %% line', NEW.transid
               USING ERRCODE = 'integrity_constraint_violation';
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
""")  # noqa: E501


# Add "total" column property to the Session class now that
# transactions and translines are defined
Session.total = column_property(
    select(func.coalesce(func.sum(Transline.items * Transline.amount), zero))
    .where(Transline.transid == Transaction.id,
           Transaction.sessionid == Session.id)
    .correlate(Session.__table__)
    .label('total'),
    deferred=True,
    doc="Transaction lines total")

Session.closed_total = column_property(
    select(func.coalesce(func.sum(Transline.items * Transline.amount), zero))
    .where(Transline.transid == Transaction.id,
           Transaction.closed,
           Transaction.sessionid == Session.id)
    .correlate(Session.__table__)
    .label('closed_total'),
    deferred=True,
    doc="Transaction lines total, closed transactions only")

Session.discount_total = column_property(
    select(func.coalesce(func.sum(Transline.items * Transline.discount), zero))
    .where(Transline.transid == Transaction.id,
           Transaction.sessionid == Session.id)
    .correlate(Session.__table__)
    .label('discount_total'),
    deferred=True,
    doc="Discount total")


# Add Transline-related column properties to the Transaction class now
# that transactions and translines are both defined
Transaction.total = column_property(
    select(func.coalesce(func.sum(Transline.items * Transline.amount), zero))
    .where(Transline.transid == Transaction.id)
    .correlate(Transaction.__table__)
    .label('total'),
    deferred=True,
    doc="Transaction lines total")

Transaction.discount_total = column_property(
    select(func.coalesce(func.sum(Transline.items * Transline.discount), zero))
    .where(Transline.transid == Transaction.id)
    .correlate(Transaction.__table__)
    .label('discount_total'),
    deferred=True,
    doc="Transaction lines discount total")

Transaction.age = column_property(
    select(func.coalesce(
        func.current_timestamp() - func.min(Transline.time),
        func.cast("0", Interval)))
    .where(Transline.transid == Transaction.id)
    .correlate(Transaction.__table__)
    .label('age'),
    deferred=True,
    doc="Transaction age")

Transaction.payments_total = column_property(
    select(func.coalesce(func.sum(Payment.amount), zero))
    .where(Payment.transid == Transaction.id)
    .correlate(Transaction.__table__)
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
    note = Column(String(), nullable=False, server_default='',
                  doc='Note about the status of this stock line. If stock '
                  'is present, the note should be treated for display '
                  'purposes as an abnormal condition.')
    stocktype_id = Column(
        'stocktype', Integer, ForeignKey('stocktypes.stocktype'),
        nullable=True)
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
            "linetype='regular' OR linetype='display' "
            "OR linetype='continuous'",
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

    def __str__(self):
        return self.name

    @property
    def logtext(self):
        return self.name

    @property
    def typeinfo(self):
        """Useful information about the line type"""
        if self.linetype == "regular":
            if self.pullthru:
                return f"Regular (pullthru {self.pullthru})"
            return "Regular"
        elif self.linetype == "display":
            return f"Display (capacity {self.capacity})"
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
            return unit.format_stock_qty(self.remaining)

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
        sos = list(self.stockonsale)  # copy because we may reverse it later
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
            return self.stocktype.calculate_sale(qty)

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
        return [x[0] for x in session.query(distinct(cls.location))
                .order_by(cls.location).all()]


add_ddl(StockLine.__table__, """
CREATE OR REPLACE FUNCTION notify_stockline_change() RETURNS trigger AS $$
DECLARE
BEGIN
  IF (TG_OP = 'DELETE') THEN
    PERFORM pg_notify('stockline_change', CAST(OLD.stocklineid AS text));
  ELSE
    PERFORM pg_notify('stockline_change', CAST(NEW.stocklineid AS text));
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER stockline_changed
  AFTER INSERT OR UPDATE OR DELETE ON stocklines
  FOR EACH ROW EXECUTE PROCEDURE notify_stockline_change();
""", """
DROP TRIGGER stockline_changed ON stocklines;
DROP FUNCTION notify_stockline_change();
""")


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

    def __str__(self):
        return self.description

    @property
    def logtext(self):
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
    date = Column(Date, nullable=False,
                  server_default=func.current_timestamp())
    checked = Column(Boolean, nullable=False, server_default=literal(False))
    supplier = relationship(
        Supplier, backref=backref('deliveries', order_by=desc(id)),
        lazy="joined")
    accinfo = Column(String(), nullable=True, doc="Accounting system info")

    items = relationship("StockItem", order_by="StockItem.id",
                         back_populates="delivery")

    tillweb_viewname = "tillweb-delivery"
    tillweb_argname = "deliveryid"

    def tillweb_nav(self):
        return [("Deliveries", self.get_view_url("tillweb-deliveries")),
                (f"{self.id} ({self.supplier.name} {self.date})",
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
        while qty > 0:
            thiscost = remaining_cost if qty == 1 else costper
            remaining_cost = remaining_cost - thiscost if cost else None
            item = StockItem(stocktype=stocktype,
                             description=description,
                             size=size,
                             costprice=thiscost,
                             bestbefore=bestbefore,
                             delivery=self)
            object_session(self).add(item)
            items.append(item)
            qty -= 1
        return items


stocktake_seq = Sequence('stocktake_seq')


class StockTake(Base, Logged):
    __tablename__ = 'stocktakes'
    id = Column('id', Integer, stocktake_seq,
                nullable=False, primary_key=True)
    description = Column(String(), nullable=False)

    create_time = Column(DateTime, nullable=False,
                         server_default=func.current_timestamp())
    create_user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Start time of the stock take: when stock quantities were sampled
    start_time = Column(DateTime, nullable=True)
    commit_time = Column(DateTime, nullable=True)
    commit_user_id = Column(Integer, ForeignKey('users.id'), nullable=True)

    create_user = relationship(
        User, foreign_keys=[create_user_id],
        backref=backref("stocktakes_created", order_by=desc(create_time)))

    commit_user = relationship(
        User, foreign_keys=[commit_user_id],
        backref=backref("stocktakes_committed", order_by=desc(commit_time)))

    scope = relationship("StockType", back_populates="stocktake",
                         order_by="""[
                         StockType.dept_id,
                         StockType.manufacturer,
                         StockType.name,
                         StockType.abv]""",
                         passive_deletes=True)

    # NB these are stock items created by this stock take, not stock
    # items in scope for it.
    items = relationship("StockItem", back_populates="stocktake",
                         order_by="StockItem.id")

    snapshots = relationship("StockTakeSnapshot",
                             order_by="StockTakeSnapshot.stock_id",
                             passive_deletes=True)
    __table_args__ = (
        CheckConstraint(
            "not(start_time is null) or commit_time is null",
            name="commit_time_null_if_no_start_time"),
        CheckConstraint(
            "not(start_time is null) or commit_user_id is null",
            name="commit_user_null_if_no_start_time"),
        CheckConstraint(
            "(commit_time is null)=(commit_user_id is null)",
            name="commit_time_and_user_null_together"),
        CheckConstraint(
            "commit_time > start_time",
            name="commit_time_after_start_time"),
    )

    @property
    def state(self):
        if not self.start_time:
            return "pending"
        if not self.commit_time:
            return "in progress"
        return "complete"

    def __str__(self):
        if self.state != "complete":
            return f"{self.id} ({self.description}) — {self.state}"
        return f"{self.id} ({self.description})"

    @property
    def contact(self):
        """Contact details for stock take in progress

        Describes the stock take, who started it, and when.
        """
        return f"{self.id} ({self.description}, {self.state}) started at " \
            f"{self.create_time:%Y-%m-%d %H:%M:%S} by {self.create_user}"

    tillweb_viewname = "tillweb-stocktake"
    tillweb_argname = "stocktake_id"

    def tillweb_nav(self):
        return [("Stock takes", self.get_view_url("tillweb-stocktakes")),
                (str(self), self.get_absolute_url())]

    @property
    def logtext(self):
        return f"{self.id} ('{self.description}')"

    def take_snapshot(self):
        if self.start_time:
            return
        self.start_time = func.current_timestamp()
        # XXX displayqty and newdisplayqty should be snapshotted as well,
        # once support is added for them in the stocktake web interface
        exc = (StockTakeSnapshot.__table__.insert()
               .from_select(
                   ['stocktake_id', 'stock_id', 'qty',
                    'bestbefore', 'newbestbefore'],
                   select(StockType.stocktake_id,
                          StockItem.id,
                          StockItem.remaining,
                          StockItem.bestbefore,
                          StockItem.bestbefore)
                   .select_from(StockItem.__table__.join(StockType.__table__))
                   .where(StockItem.checked == True)
                   .where(StockType.stocktake_id == self.id)
                   .where(StockItem.finished == None)))
        object_session(self).execute(exc)

    def commit_snapshot(self, user):
        if not self.start_time:
            return
        if self.commit_time:
            return
        s = object_session(self)
        self.commit_time = func.current_timestamp()
        self.commit_user = user
        for ss in self.snapshots:
            if ss.finishcode:
                ss.stockitem.finishcode = ss.finishcode
                ss.stockitem.stockline = None
                ss.stockitem.displayqty = None
                if not ss.stockitem.finished:
                    ss.stockitem.finished = func.current_timestamp()
            if not ss.finishcode:
                ss.stockitem.finishcode = None
                ss.stockitem.finished = None
            ss.stockitem.bestbefore = ss.newbestbefore
            # XXX commit newdisplayqty once implemented, too
            for a in ss.adjustments:
                s.add(StockOut(
                    stockitem=ss.stockitem,
                    time=func.current_timestamp(),
                    removecode=a.removecode,
                    stocktake=self,
                    qty=a.qty))
        s.query(StockType).filter(StockType.stocktake == self).update({
            StockType.stocktake_id: None})

# XXX add rules to ensure that stocktakes cannot be deleted once committed


units_seq = Sequence('units_seq')


class Unit(Base, Logged):
    """A unit in which stock is held, and its default quantity for pricing

    Often these will be the same, eg. beer is counted by the "pint"
    and priced per one "pint"; 1 pint is called a "pint".  For some
    types of stock they will be different, eg. wine is counted by the
    "ml" and priced per 750 "ml"; 750ml is called a "wine bottle".

    We call the fundamental unit the "base" unit.

    When we count stock we may need to use a different unit again.
    For example, soft drinks from cartons are sold by the pint (568ml)
    but bought and counted in units of 1l carton (1000ml).

    The size of a stock item in base units is stored with the
    item. Sizes of units in which items are purchased are described by
    the StockUnit class.

    """
    __tablename__ = 'unittypes'
    id = Column(Integer, units_seq, nullable=False, primary_key=True)
    # How this unit appears in menus
    description = Column(String(), nullable=False)

    # Name of the fundamental ("base") unit, eg. ml, pint
    name = Column(String(), nullable=False)

    # Name of the pricing/sale unit, singular and plural form
    sale_unit_name = Column(String(), nullable=False)
    sale_unit_name_plural = Column(String(), nullable=False)
    base_units_per_sale_unit = Column(quantity, nullable=False,
                                      default=Decimal("1.0"))

    # Name of the stock-keeping unit, singular and plural form
    stock_unit_name = Column(String(), nullable=False)
    stock_unit_name_plural = Column(String(), nullable=False)
    base_units_per_stock_unit = Column(quantity, nullable=False,
                                       default=Decimal("1.0"))

    # This column has moved from StockType
    stocktake_by_items = Column(
        Boolean, nullable=False, server_default=literal(True))

    tillweb_viewname = "tillweb-unit"
    tillweb_argname = "unit_id"

    def tillweb_nav(self):
        return [("Units", self.get_view_url("tillweb-units")),
                (self.description, self.get_absolute_url())]

    @staticmethod
    def _fq(q):
        return f"{q:.1f}".rstrip('0').rstrip('.')

    def format_sale_qty(self, qty):
        if abs(qty) < self.base_units_per_sale_unit and qty != 0:
            return f"{self._fq(qty)} {self.name}"
        single = abs(qty) - self.base_units_per_sale_unit < 0.05
        n = self.sale_unit_name if single else self.sale_unit_name_plural
        return f"{self._fq(qty / self.base_units_per_sale_unit)} {n}"

    def format_stock_qty(self, qty):
        if abs(qty) < self.base_units_per_stock_unit and qty != 0:
            return self.format_sale_qty(qty)
        single = abs(qty) - self.base_units_per_stock_unit < 0.05
        if qty == 0.0:
            single = False
        n = self.stock_unit_name if single else self.stock_unit_name_plural
        return f"{self._fq(qty / self.base_units_per_stock_unit)} {n}"

    def format_adjustment_qty(self, qty):
        # Format the quantity as an adjustment, eg. "-10 pints" or "+10 pints"
        q = self.format_stock_qty(-qty)
        if q[0] != "-":
            q = f"+{q}"
        return q

    # sale_unit_name etc. were renamed from item_name etc.; add properties
    # to ease the migration XXX with deprecation warnings

    @property
    def item_name(self):
        warnings.warn(
            "Unit.item_name has been renamed to Unit.sale_unit_name",
            DeprecationWarning, stacklevel=2)
        return self.sale_unit_name

    @property
    def item_name_plural(self):
        warnings.warn(
            "Unit.item_name_plural has been renamed to "
            "Unit.sale_unit_name_plural", DeprecationWarning, stacklevel=2)
        return self.sale_unit_name_plural

    @property
    def units_per_item(self):
        warnings.warn(
            "Unit.units_per_item has been renamed to "
            "Unit.base_units_per_sale_unit", DeprecationWarning, stacklevel=2)
        return self.base_units_per_sale_unit

    @property
    def stocktake_method(self):
        return "separate items" if self.stocktake_by_items \
            else "total quantity"

    def __str__(self):
        return self.name

    @property
    def logtext(self):
        return self.description


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

    @property
    def logtext(self):
        return self.name


stocktypes_seq = Sequence('stocktypes_seq')


class StockType(Base, Logged):
    __tablename__ = 'stocktypes'
    id = Column('stocktype', Integer, stocktypes_seq, nullable=False,
                primary_key=True)
    dept_id = Column('dept', Integer, ForeignKey('departments.dept'),
                     nullable=False)
    manufacturer = Column(String(30), nullable=False)
    name = Column(String(30), nullable=False)
    abv = Column(abv, CheckConstraint("abv >= 0.0"),
                 nullable=True)
    unit_id = Column(Integer, ForeignKey('unittypes.id'), nullable=False)
    saleprice = Column(money, nullable=True)  # inc VAT
    stocktake_id = Column(
        Integer, ForeignKey('stocktakes.id', ondelete='SET NULL'),
        nullable=True)
    archived = Column(
        Boolean, server_default=literal(False), nullable=False,
        doc='When a stock type is archived, it no longer shows up in '
        'searches and autocompletion, and new stock of this type cannot '
        'be created.')
    note = Column(
        String(), nullable=False, server_default='',
        doc='Note about the status of this stock type.')
    department = relationship(Department, lazy="joined")
    unit = relationship(Unit, lazy="joined",
                        backref=backref("stocktypes", order_by=id))

    # Currently in scope for this stock take
    stocktake = relationship(StockTake, back_populates="scope")

    meta = relationship("StockTypeMeta",
                        collection_class=attribute_mapped_collection('key'),
                        back_populates="stocktype",
                        passive_deletes=True,
                        cascade="all,delete-orphan")

    __table_args__ = (
        UniqueConstraint('dept', 'manufacturer', 'name', 'abv', 'unit_id',
                         name="stocktypes_ambiguity_key"),
    )

    def set_meta(self, key, val=None, document=None, mimetype=None):
        val = str(val)
        if key in self.meta:
            o = self.meta[key]
            o.value = val
            o.document = document
            o.document_mimetype = mimetype
        else:
            self.meta[key] = StockTypeMeta(
                key=key,
                value=val,
                document=document,
                document_mimetype=mimetype)

    @hybrid_property
    def fullname(self):
        return self.manufacturer + ' ' + self.name

    tillweb_viewname = "tillweb-stocktype"
    tillweb_argname = "stocktype_id"

    def tillweb_nav(self):
        return [("Stock types", self.get_view_url("tillweb-stocktype-search")),
                (str(self), self.get_absolute_url())]

    def __str__(self):
        return f"{self.manufacturer} {self.name}"

    @property
    def logtext(self):
        return f"{self.manufacturer} {self.name}"

    @property
    def abvstr(self):
        if self.abv is not None:
            return f"{self.abv}%"
        return ""

    @property
    def pricestr(self):
        if self.saleprice is not None:
            return f"{self.saleprice}/{self.unit.sale_unit_name}"
        return ""

    @property
    def remaining_str(self):
        """Amount of unsold stock, including unit"""
        return self.unit.format_stock_qty(self.remaining)

    @property
    def descriptions(self):
        """List of possible descriptions

        Various possible descriptions of this stocktype, returned in
        descending order of string length.
        """
        if self.abv:
            return [
                f'{self.fullname} ({self.abv}% ABV)',
                self.fullname,
            ]
        return [self.fullname]

    def format(self, maxw=None):
        """Format this stocktype with optional maximum width
        """
        for x in self.descriptions:
            if maxw is None or len(x) <= maxw:
                return x
        return self.descriptions[-1][:maxw]

    _specre = re.compile(r"^(?:(?P<fill>.?)(?P<align>[<>^]))?#?0?(?P<minwidth>\d+)?(?:\.(?P<maxwidth>\d+))?(?P<type>s)?$")  # noqa: E501

    def __format__(self, spec):
        """Format the stock type according to the supplied specification
        """
        m = self._specre.match(spec)
        if m is None:
            raise ValueError("Invalid format specifier")
        fill = m['fill'] or ' '
        align = m['align'] or '<'
        minwidth = int(m['minwidth']) if m['minwidth'] else 0
        maxwidth = int(m['maxwidth']) if m['maxwidth'] else None
        s = self.format(maxw=maxwidth)
        if align == '<':
            s = s.ljust(minwidth, fill)
        elif align == '^':
            s = s.center(minwidth, fill)
        else:
            s = s.rjust(minwidth, fill)
        return s

    # Similar to StockLine.stockonsale, except for continuous stock
    # lines or direct sale through StockType
    def stockonsale(self):
        return object_session(self)\
            .query(StockItem)\
            .filter(StockItem.checked == True)\
            .filter(StockItem.stocktype == self)\
            .filter(StockItem.finished == None)\
            .filter(StockItem.stockline == None)\
            .options(undefer_group('qtys'),
                     joinedload(StockItem.delivery),
                     joinedload(StockItem.finishcode))\
            .order_by(StockItem.id)\
            .all()

    def calculate_sale(self, qty):
        """Work out a plan to remove a quantity of stock from the stock type.

        They may be sold, wasted, etc. - this is not just for
        calculating a sale!

        Returns (list of (stockitem, qty) pairs, the number of items
        that could not be allocated, remaining stock).

        Stock that is connected to a stock line (excluding
        "continuous" stock lines) isn't available for sale through
        this method.
        """
        # Reject negative quantities
        if qty < Decimal("0.0"):
            return ([], qty, None)
        stock = self.stockonsale()
        if len(stock) == 0:
            # There's no unfinished stock of this type at all that
            # isn't connected to a stock line - we can't do anything.
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


add_ddl(StockType.__table__, """
CREATE OR REPLACE FUNCTION notify_stocktype_change() RETURNS trigger AS $$
DECLARE
BEGIN
  IF (TG_OP = 'DELETE') THEN
    PERFORM pg_notify('stocktype_change', CAST(OLD.stocktype AS text));
  ELSE
    PERFORM pg_notify('stocktype_change', CAST(NEW.stocktype AS text));
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER stocktype_changed
  AFTER INSERT OR UPDATE OR DELETE ON stocktypes
  FOR EACH ROW EXECUTE PROCEDURE notify_stocktype_change();
""", """
DROP TRIGGER stocktype_changed ON stocktypes;
DROP FUNCTION notify_stocktype_change();
""")


class FinishCode(Base):
    __tablename__ = 'stockfinish'
    id = Column('finishcode', String(8), nullable=False, primary_key=True)
    description = Column(String(50), nullable=False)

    def __str__(self):
        return self.description


class StockTypeMeta(Base):
    """Metadata on a stock type

    Acts as a key/value store per stocktype.  Only one instance of a
    key can exist per stock type: the primary key for this table is
    (id,key).

    If the stock type is deleted, all its metadata is deleted too.

    Stock type metadata is expected to be used by the web interface.

    At least one of "value" or "document" must be supplied, and if
    "document" is supplied then "document_mimetype" must be supplied
    as well.

    document_hash will be calculated. (Implementation note: for now it
    is calculated client-side because we are targeting Postgresql
    10. In the future (from Postgresql 12 onwards) this can be
    calculated automatically using a database trigger.
    """
    __tablename__ = 'stocktype_meta'
    stocktype_id = Column('stocktype', Integer,
                          ForeignKey('stocktypes.stocktype',
                                     ondelete='CASCADE'),
                          primary_key=True, nullable=False)
    key = Column(String(), nullable=False, primary_key=True)
    value = Column(String(), nullable=True)
    _document = deferred(Column('document', LargeBinary(), nullable=True))
    document_hash = Column(LargeBinary(), nullable=True)
    document_mimetype = Column(String(), nullable=True)

    stocktype = relationship(StockType, back_populates='meta')

    @hybrid_property
    def document(self):
        return self._document

    @document.setter
    def document(self, contents):
        self._document = contents
        self.document_hash = None if contents is None else \
            hashlib.sha256(contents).digest()

    __table_args__ = (
        CheckConstraint(
            "value IS NOT NULL OR document IS NOT NULL",
            name="be_useful_constraint"),
        CheckConstraint(
            "(document is null)=(document_hash is null)",
            name="document_and_hash_null_together"),
        CheckConstraint(
            "(document is null)=(document_mimetype is null)",
            name="document_and_mimetype_null_together"),
    )


add_ddl(StockTypeMeta.__table__, """
CREATE OR REPLACE FUNCTION notify_stocktype_meta_change() RETURNS trigger AS $$
DECLARE
BEGIN
  IF (TG_OP = 'DELETE') THEN
    PERFORM pg_notify('stocktype_change', CAST(OLD.stocktype AS text));
  ELSE
    PERFORM pg_notify('stocktype_change', CAST(NEW.stocktype AS text));
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER stocktype_meta_changed
  AFTER INSERT OR UPDATE OR DELETE ON stocktype_meta
  FOR EACH ROW EXECUTE PROCEDURE notify_stocktype_meta_change();
""", """
DROP TRIGGER stocktype_meta_changed ON stocktype_meta;
DROP FUNCTION notify_stocktype_meta_change();
""")


stock_seq = Sequence('stock_seq')


class StockItem(Base, Logged):
    """An item of stock - a cask, keg, case of bottles, card of snacks,
    and so on.

    Stock items are introduced to the database via either a delivery
    or a stocktake; always one, never both.  A stock item is available
    for use when delivery.checked is true, or stocktake.commit_time is
    not null.  A column property, StockItem.checked, is available to
    test this.

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
    id = Column('stockid', Integer, stock_seq, nullable=False,
                primary_key=True)
    deliveryid = Column(Integer, ForeignKey('deliveries.deliveryid'),
                        nullable=True)
    stocktake_id = Column(Integer, ForeignKey('stocktakes.id'), nullable=True)
    stocktype_id = Column('stocktype', Integer,
                          ForeignKey('stocktypes.stocktype'), nullable=False)
    description = Column(String(), nullable=False)
    size = Column(quantity, CheckConstraint("size > 0.0"), nullable=False)
    costprice = Column(money)  # ex VAT
    onsale = Column(DateTime)
    finished = Column(DateTime)
    finishcode_id = Column('finishcode', String(8),
                           ForeignKey('stockfinish.finishcode'))
    bestbefore = Column(Date)
    delivery = relationship(Delivery, back_populates="items")
    stocktake = relationship(StockTake, back_populates="items")
    stocktype = relationship(StockType, backref=backref('items', order_by=id))
    finishcode = relationship(FinishCode, lazy="joined")
    stocklineid = Column(Integer, ForeignKey('stocklines.stocklineid',
                                             ondelete='SET NULL'),
                         nullable=True)
    displayqty = Column(quantity, nullable=True)

    snapshots = relationship("StockTakeSnapshot", back_populates="stockitem")

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
        CheckConstraint(
            "(deliveryid is null)!=(stocktake_id is null)",
            name="only_one_of_delivery_or_stocktake"),
    )

    stockline = relationship(StockLine, backref=backref(
        'stockonsale',
        order_by=lambda: (
            desc(func.coalesce(StockItem.displayqty, 0)),
            StockItem.id)))

    @property
    def logtext(self):
        return f"{self.id} ({self.stocktype})"

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
        return (
            self.bestbefore - (self.finished or datetime.date.today())).days

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
        a = hashlib.sha1((f"quicktill-{self.id}-quicktill").encode('utf-8'))
        return str(int(a.hexdigest(), 16))[-3:]

    @property
    def removed(self):
        """Amount of stock removed from this item under all the
        various RemoveCodes.

        Returns a list of (RemoveCode, qty) tuples.
        """
        return object_session(self)\
            .query(RemoveCode, func.sum(StockOut.qty))\
            .select_from(StockOut.__table__)\
            .join(RemoveCode)\
            .filter(StockOut.stockid == self.id)\
            .group_by(RemoveCode)\
            .order_by(desc(func.sum(StockOut.qty)))\
            .all()

    @property
    def used_units(self):
        """Quantity used as a string with the unit name

        eg. 2 pints, 1 pint, 3 bottles
        """
        return self.stocktype.unit.format_stock_qty(self.used)

    @property
    def sold_units(self):
        """Quantity sold as a string with the unit name

        eg. 2 pints, 1 pint, 3 bottles
        """
        return self.stocktype.unit.format_stock_qty(self.sold)

    @property
    def remaining_units(self):
        """Quantity remaining as a string with the unit name

        eg. 2 pints, 1 pint, 3 bottles
        """
        return self.stocktype.unit.format_stock_qty(self.remaining)

    tillweb_viewname = "tillweb-stock"
    tillweb_argname = "stockid"

    def tillweb_nav(self):
        return self.delivery.tillweb_nav() + [
            (f"Item {self.id} ({self.stocktype.manufacturer} "
             f"{self.stocktype.name})", self.get_absolute_url())]


# This trigger notifies changes in a stock item, and also notifies a
# change to a stockline when the item is added to or removed from it.
add_ddl(StockItem.__table__, """
CREATE OR REPLACE FUNCTION notify_stockitem_change() RETURNS trigger AS $$
DECLARE
BEGIN
  IF (TG_OP = 'DELETE') THEN
    PERFORM pg_notify('stockitem_change', CAST(OLD.stockid AS text));
    IF (OLD.stocklineid IS NOT NULL) THEN
      PERFORM pg_notify('stockline_change', CAST(OLD.stocklineid AS text));
    END IF;
  ELSIF (TG_OP = 'INSERT') THEN
    PERFORM pg_notify('stockitem_change', CAST(NEW.stockid AS text));
  ELSE
    PERFORM pg_notify('stockitem_change', CAST(NEW.stockid AS text));
    IF (OLD.stocklineid IS DISTINCT FROM NEW.stocklineid) THEN
      IF (OLD.stocklineid IS NOT NULL) THEN
        PERFORM pg_notify('stockline_change', CAST(OLD.stocklineid AS text));
      END IF;
      IF (NEW.stocklineid IS NOT NULL) THEN
        PERFORM pg_notify('stockline_change', CAST(NEW.stocklineid AS text));
      END IF;
    END IF;
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER stockitem_changed
  AFTER INSERT OR UPDATE OR DELETE ON stock
  FOR EACH ROW EXECUTE PROCEDURE notify_stockitem_change();
""", """
DROP TRIGGER stockitem_changed ON stock;
DROP FUNCTION notify_stockitem_change();
""")


StockItem.checked = column_property(
    select(
        func.coalesce(
            select(Delivery.checked)
            .correlate(StockItem.__table__)
            .where(Delivery.id == StockItem.deliveryid)
            .label("delivered"),
            select(StockTake.commit_time != None)
            .correlate(StockItem.__table__)
            .where(StockTake.id == StockItem.stocktake_id)
            .label("found_in_stocktake")))
    .label("checked"),
    deferred=True,
    doc="Is this item available for use?")

Delivery.costprice = column_property(
    select(
        case((func.count(StockItem.costprice) != func.count('*'), None),
             else_=func.sum(StockItem.costprice))
    )
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
        return self.description


stock_annotation_seq = Sequence('stock_annotation_seq')


class StockAnnotation(Base, Logged):
    __tablename__ = 'stock_annotations'
    id = Column(Integer, stock_annotation_seq, nullable=False,
                primary_key=True)
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
        return self.reason


stockout_seq = Sequence('stockout_seq')


class StockOut(Base, Logged):
    __tablename__ = 'stockout'
    id = Column('stockoutid', Integer, stockout_seq,
                nullable=False, primary_key=True)
    stockid = Column(Integer, ForeignKey('stock.stockid'), nullable=False)
    qty = Column(quantity, nullable=False)
    removecode_id = Column(
        'removecode', String(8),
        ForeignKey('stockremove.removecode'), nullable=False)
    translineid = Column(
        Integer, ForeignKey('translines.translineid', ondelete='CASCADE'),
        nullable=True)
    stocktake_id = Column(
        Integer, ForeignKey('stocktakes.id', ondelete='CASCADE'),
        nullable=True)
    time = Column(DateTime, nullable=False,
                  server_default=func.current_timestamp())
    stockitem = relationship(StockItem, backref=backref('out', order_by=id))
    removecode = relationship(RemoveCode, lazy="joined")
    transline = relationship(Transline,
                             backref=backref('stockref', cascade="all,delete"))
    stocktake = relationship(StockTake)

    # At most one of translineid and stocktake_id can be non-NULL
    __table_args__ = (
        CheckConstraint(
            "translineid IS NULL OR stocktake_id IS NULL",
            name="be_unambiguous_constraint"),
    )


add_ddl(StockOut.__table__, """
CREATE OR REPLACE FUNCTION notify_stockout_change() RETURNS trigger AS $$
DECLARE
BEGIN
  IF (TG_OP = 'DELETE') THEN
    PERFORM pg_notify('stockitem_change', CAST(OLD.stockid AS text));
  ELSE
    PERFORM pg_notify('stockitem_change', CAST(NEW.stockid AS text));
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER stockout_changed
  AFTER INSERT OR UPDATE OR DELETE ON stockout
  FOR EACH ROW EXECUTE PROCEDURE notify_stockout_change();
""", """
DROP TRIGGER stockout_changed ON stockout;
DROP FUNCTION notify_stockout_change();
""")


# These are added to the StockItem class here because they refer
# directly to the StockOut class, defined just above.
StockItem.used = column_property(
    select(func.coalesce(func.sum(StockOut.qty), text("0.0")))
    .correlate(StockItem.__table__)
    .where(StockOut.stockid == StockItem.id)
    .label('used'),
    deferred=True,
    group="qtys",
    doc="Amount of this item that has been used for any reason")

StockItem.sold = column_property(
    select(func.coalesce(func.sum(StockOut.qty), text("0.0")))
    .correlate(StockItem.__table__)
    .where(StockOut.stockid == StockItem.id)
    .where(StockOut.removecode_id == "sold")
    .label('sold'),
    deferred=True,
    group="qtys",
    doc="Amount of this item that has been used by being sold")

StockItem.remaining = column_property(
    select(StockItem.size - func.coalesce(func.sum(StockOut.qty), text("0.0")))
    .where(StockOut.stockid == StockItem.id)
    .label('remaining'),
    deferred=True,
    group="qtys",
    doc="Amount of this item remaining")

StockItem.firstsale = column_property(
    select(func.min(StockOut.time))
    .correlate(StockItem.__table__)
    .where(StockOut.stockid == StockItem.id)
    .where(StockOut.removecode_id == 'sold')
    .label('firstsale'),
    deferred=True,
    doc="Time of first sale of this item")

StockItem.lastsale = column_property(
    select(func.max(StockOut.time))
    .correlate(StockItem.__table__)
    .where(StockOut.stockid == StockItem.id)
    .where(StockOut.removecode_id == 'sold')
    .label('lastsale'),
    deferred=True,
    doc="Time of last sale of this item")

# Similarly, this is added to the StockType class here because it
# refers to Stock

# This is used as "remaining" for continuous stock lines and stock
# types. It excludes stock items attached to regular or display stock
# lines, because that stock isn't directly sellable through the
# continuous stock line or the stock type.
StockType.instock = column_property(
    select(
        func.coalesce(
            func.sum(
                StockItem.size - select(
                    func.coalesce(func.sum(StockOut.qty), text("0.0")))
                .where(StockOut.stockid == StockItem.id)
                .scalar_subquery()),
            text("0.0")))
    .where(StockItem.stocktype_id == StockType.id,
           StockItem.finished == None,
           StockItem.stocklineid == None,
           StockItem.checked == True)
    .correlate(StockType.__table__)
    .label('instock'),
    deferred=True,
    doc="Amount remaining in stock, not already on sale")

StockType.remaining = StockType.instock

# This is used for the buying list: it includes stock items attached
# to stock lines because it only cares about the total amount of stock
# on the premises.
StockType.all_instock = column_property(
    select(
        func.coalesce(
            func.sum(
                StockItem.size - select(
                    func.coalesce(func.sum(StockOut.qty), text("0.0")))
                .where(StockOut.stockid == StockItem.id)
                .scalar_subquery()),
            text("0.0")))
    .where(StockItem.stocktype_id == StockType.id,
           StockItem.finished == None,
           StockItem.checked == True)
    .correlate(StockType.__table__)
    .label('all_instock'),
    deferred=True,
    doc="Total amount remaining in stock")

StockType.lastsale = column_property(
    select(func.max(StockOut.time))
    .where(StockItem.stocktype_id == StockType.id,
           StockOut.stockid == StockItem.id,
           StockItem.checked == True)
    .correlate(StockType.__table__)
    .label('lastsale'),
    deferred=True,
    doc="Date of last sale")


class StockTakeSnapshot(Base):
    """Snapshot of stock levels at the start of a stock take

    Primary key is (stocktake,stockitem)

    If the item is discovered to be completely finished, missing, or
    out of date, set 'finishcode' as appropriate.

    If a finished item is manually added to the stock take (i.e. it's
    been discovered in stock), initialise finishcode to the finishcode
    of the item.

    qty is the number of items in stock as at the start of the
    stocktake.  newqty (added to the class later) is qty minus the sum
    of all adjustments.  displayqty is the amount of qty considered to
    be on display, and newdisplayqty is the amount of newqty
    considered to be on display, i.e. it should be changed as
    adjustments are added and if not null should be in the range 0 <=
    newdisplayqty <= newqty, although it is not possible to add a check
    constraint for this.
    """
    __tablename__ = 'stocktake_snapshots'
    stocktake_id = Column(
        Integer, ForeignKey('stocktakes.id', ondelete='CASCADE'),
        primary_key=True)
    stock_id = Column(Integer, ForeignKey('stock.stockid'), primary_key=True)
    # Quantity recorded at start of stock take
    qty = Column(quantity, nullable=False)
    displayqty = Column(quantity, nullable=True)
    newdisplayqty = Column(quantity, nullable=True)
    checked = Column(Boolean, server_default=literal(False), nullable=False)
    finishcode_id = Column('finishcode', String(8),
                           ForeignKey('stockfinish.finishcode'))
    bestbefore = Column(Date, doc="Best-before date for this stock item as "
                        "at the start of the stock take")
    newbestbefore = Column(Date, doc="Best-before date to apply when "
                           "committing the stock take")
    note = Column(String(), nullable=False, server_default='',
                  doc='Note about this stock item during the stock take.')

    stocktake = relationship(StockTake, back_populates='snapshots')
    stockitem = relationship(StockItem, back_populates='snapshots')
    finishcode = relationship(FinishCode)
    adjustments = relationship("StockTakeAdjustment",
                               back_populates='snapshot',
                               passive_deletes=True)

    tillweb_viewname = "tillweb-stocktake-stockitem"

    @property
    def qty_in_stock_units(self):
        u = self.stockitem.stocktype.unit
        if self.displayqty is not None:
            return f'{u.format_stock_qty(self.displayqty)} + ' \
                f'{u.format_stock_qty(self.qty - self.displayqty)}'
        return u.format_stock_qty(self.qty)

    @property
    def newqty_in_stock_units(self):
        u = self.stockitem.stocktype.unit
        if self.displayqty is not None:
            return f'{u.format_stock_qty(self.newdisplayqty)} + ' \
                f'{u.format_stock_qty(self.newqty - self.newdisplayqty)}'
        return u.format_stock_qty(self.newqty)

    def __str__(self):
        return f"Adjustment for {self.stock_id}"

    def tillweb_nav(self):
        return self.stocktake.tillweb_nav() + [
            (str(self), self.get_absolute_url())]

    def get_absolute_url(self):
        return self.get_view_url(self.tillweb_viewname,
                                 stocktake_id=self.stocktake_id,
                                 stock_id=self.stock_id)


# Add the StockTake.snapshot_count column property
StockTake.snapshot_count = column_property(
    select(func.count('*'))
    .select_from(StockTakeSnapshot)
    .correlate(StockTake.__table__)
    .where(StockTakeSnapshot.stocktake_id == StockTake.id)
    .label('snapshot_count'),
    deferred=True,
    doc="Number of snapshots in this stock take")


class StockTakeAdjustment(Base):
    """Adjustment to stock level during a stock take

    Primary key is (stocktake,stockitem,removecode)

    NB the foreign key constraint for stocktake,stockitem is a
    compound constraint referencing the snapshots table, so
    adjustments cannot be present when a snapshot has not been taken.
    """
    __tablename__ = 'stocktake_adjustments'
    stocktake_id = Column(Integer, primary_key=True)
    stock_id = Column(Integer, primary_key=True)
    removecode_id = Column(
        String(8), ForeignKey('stockremove.removecode'), primary_key=True)
    qty = Column(quantity, CheckConstraint("qty != 0.0"), nullable=False)

    snapshot = relationship(StockTakeSnapshot, back_populates='adjustments')
    removecode = relationship(RemoveCode)

    __table_args__ = (
        ForeignKeyConstraint([stocktake_id, stock_id],
                             [StockTakeSnapshot.stocktake_id,
                              StockTakeSnapshot.stock_id],
                             ondelete='CASCADE'),
    )

    @property
    def stock_qty(self):
        return self.snapshot.stockitem.stocktype.unit.format_stock_qty(
            self.qty)

    @property
    def adjustment_qty(self):
        return self.snapshot.stockitem.stocktype.unit.format_adjustment_qty(
            self.qty)


StockTakeSnapshot.newqty = column_property(
    select(StockTakeSnapshot.qty - func.coalesce(
        func.sum(StockTakeAdjustment.qty), text("0.0")))
    .where(StockTakeAdjustment.stocktake_id == StockTakeSnapshot.stocktake_id,
           StockTakeAdjustment.stock_id == StockTakeSnapshot.stock_id)
    .correlate(StockTakeSnapshot.__table__)
    .label('newqty'),
    deferred=True,
    doc="Amount remaining after adjustments")


class KeyboardBinding(Base):
    __tablename__ = 'keyboard'
    keycode = Column(String(20), nullable=False, primary_key=True)
    menukey = Column(String(20), nullable=False, primary_key=True)
    stocklineid = Column(Integer, ForeignKey(
        'stocklines.stocklineid', ondelete='CASCADE'))
    pluid = Column(Integer, ForeignKey(
        'pricelookups.id', ondelete='CASCADE'))
    modifier = Column(String(), nullable=True)
    stockline = relationship(
        StockLine, backref=backref('keyboard_bindings', cascade='all'))
    plu = relationship(
        PriceLookup, backref=backref('keyboard_bindings', cascade='all'))

    @property
    def stocktype(self):
        # KeyboardBinding may support binding to stocktype in the
        # future; for now, ensure the attribute exists for
        # compatibility with barcode bindings
        return None

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
        stockline name, PLU name, or modifier name as appropriate.
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
        return object_session(self).get(KeyCap, self.keycode)


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


class Barcode(Base):
    """Barcodes

    A scanned barcode can refer to a stock line, price lookup or stock
    type (where it behaves as if that stock type is connected to a
    continuous stock line), with optional modifier.  It can also refer
    to a modifier.  It is similar in principle to a keyboard binding,
    but for a keyboard with a very large number of keys.
    """
    __tablename__ = 'barcodes'
    id = Column('barcode', String(), primary_key=True)
    stocklineid = Column(Integer, ForeignKey(
        'stocklines.stocklineid', ondelete='CASCADE'))
    pluid = Column(Integer, ForeignKey(
        'pricelookups.id', ondelete='CASCADE'))
    stocktype_id = Column(
        'stocktype', Integer, ForeignKey(
            'stocktypes.stocktype', ondelete='CASCADE'))
    modifier = Column(String())
    stockline = relationship(
        StockLine, backref=backref('barcodes', cascade='all',
                                   passive_deletes=True))
    plu = relationship(
        PriceLookup, backref=backref('barcodes', cascade='all',
                                     passive_deletes=True))
    stocktype = relationship(
        StockType, backref=backref('barcodes', cascade='all',
                                   passive_deletes=True))
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(stocklineid, pluid, stocktype, modifier) != 0",
            name="be_useful_constraint"),
        CheckConstraint(
            "num_nonnulls(stocklineid, pluid, stocktype) <= 1",
            name="be_unambiguous_constraint"),
    )

    tillweb_viewname = "tillweb-barcode"
    tillweb_argname = "barcode"

    def tillweb_nav(self):
        return [("Barcodes", self.get_view_url("tillweb-barcodes")),
                (f"{self.id}", self.get_absolute_url())]

    # XXX these properties could be in a mixin class shared with
    # KeyboardBinding?  Arguably the stockline, plu and modifier
    # columns could be too
    @property
    def name(self):
        """Look up the name of this barcode binding
        """
        if self.stockline:
            return self.stockline.name
        if self.plu:
            return self.plu.description
        if self.stocktype:
            return format(self.stocktype)
        return self.modifier

    @property
    def binding_type(self):
        if self.stockline:
            return "Stock line"
        elif self.plu:
            return "Price lookup"
        elif self.stocktype:
            return "Stock type"
        else:
            return "Modifier"

    @property
    def target(self):
        return self.stockline or self.plu or self.stocktype


class Config(Base, Logged):
    """Till configuration
    """
    __tablename__ = "config"
    key = Column(String(), primary_key=True)
    value = Column(Text, nullable=False)
    type = Column(String(), nullable=False)
    display_name = Column(Text, nullable=False)
    description = Column(Text, nullable=False)

    tillweb_viewname = "tillweb-config-item"
    tillweb_argname = "key"

    @property
    def id(self):
        # Needed for get_absolute_url
        return self.key

    def tillweb_nav(self):
        return [("Config", self.get_view_url("tillweb-config-index")),
                (self.display_name, self.get_absolute_url())]

    def value_summary(self, max_lines=6):
        lines = self.value.splitlines()
        if len(lines) > max_lines:
            lines = lines[:max_lines] \
                + [f"(plus {len(lines) - max_lines} more lines)"]
        return '\n'.join(lines)

    @property
    def logtext(self):
        return self.display_name


add_ddl(Config.__table__, """
CREATE OR REPLACE FUNCTION notify_config_change() RETURNS trigger AS $$
DECLARE
BEGIN
  PERFORM pg_notify('config', NEW.key::text);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER config_change
  AFTER UPDATE ON config
  FOR EACH ROW EXECUTE PROCEDURE notify_config_change();
""", """
DROP TRIGGER config_change ON config;
DROP FUNCTION notify_config_change();
""")


class Secret(Base):
    """A cryptographic secret or a password

    Secrets are stored encrypted using Fernet (https://github.com/fernet/spec/)

    The Fernet key is not stored in the database.  It will generally
    be stored in the till configuration file, although the site may
    make other arrangements.  This is not intended to be a security
    feature; the intent is to prevent accidental use of live keys from
    a database that has been copied elsewhere, for example for backup
    or development.
    """
    __tablename__ = "secrets"
    key_name = Column(String(), primary_key=True)
    secret_name = Column(String(), primary_key=True)
    token = Column(LargeBinary(), nullable=False)


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

    def tillweb_nav(self):
        return [("Logs", self.get_view_url("tillweb-logs")),
                (str(self.id), self.get_absolute_url())]

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
        obj = session.get(model, tuple(c(k) for c, k in zip(pk_types, keys)))
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
        _colname = f"{_key.table.name}_id{_num if len(_primary_keys) > 1 else ''}"  # noqa: E501
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
Index('stock_stocktype_key', StockItem.stocktype_id)

# The "find free drinks on this day" function is speeded up
# considerably by an index on stockout.time::date.
Index('stockout_date_key', func.cast(StockOut.time, Date))


foodorder_seq = Sequence('foodorder_seq', metadata=metadata)


# Very simple refusals log for EMF 2018.  Log templates are in config.
refusals_log_seq = Sequence('refusals_log_seq')


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
