from sqlalchemy.ext.declarative import declarative_base,declared_attr
from sqlalchemy import Column,Integer,String,DateTime,Date,ForeignKey,Numeric,CHAR,Boolean,Text
from sqlalchemy.schema import Sequence,Index,MetaData,DDL,CheckConstraint
from sqlalchemy.sql.expression import text,alias
from sqlalchemy.orm import relationship,backref,object_session,sessionmaker
from sqlalchemy.orm import subqueryload_all,joinedload,subqueryload
from sqlalchemy.orm import column_property
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql import select,func,desc,and_
from sqlalchemy import event

import datetime
import hashlib
from decimal import Decimal

metadata=MetaData()
Base=declarative_base(metadata=metadata)

def add_ddl(target,create,drop):
    """Convenience function to add CREATE and DROP statements for postgresql
    database rules; can also be used to create nonstandard indexes.

    """
    if create:
        event.listen(target,"after_create",
                     DDL(create).execute_if(dialect='postgresql'))
    if drop:
        event.listen(target,"before_drop",
                     DDL(drop).execute_if(dialect='postgresql'))

class Business(Base):
    __tablename__='businesses'
    id=Column('business',Integer,primary_key=True)
    name=Column(String(80))
    abbrev=Column(String(20))
    address=Column(String(200))
    vatno=Column(String(30))
    def __unicode__(self):
        return u"%s"%(self.abbrev,)
    def __repr__(self):
        return "<Business('%s')>"%(self.name,)

# This is intended to be a mixin for both VatBand and VatRate.  It's
# not intended to be instantiated.
class Vat(object):
    @declared_attr
    def rate(cls):
        return Column(Numeric(5,2),nullable=False)
    @declared_attr
    def businessid(cls):
        return Column('business',Integer,ForeignKey('businesses.business'))
    @declared_attr
    def business(cls):
        return relationship(Business)
    @property
    def rate_fraction(self):
        return self.rate/Decimal(100)
    def inc_to_exc(self,n):
        return (n/(self.rate_fraction+Decimal(1))).quantize(Decimal("0.01"))
    def inc_to_vat(self,n):
        return n-self.inc_to_exc(n)
    def exc_to_vat(self,n):
        return (n*self.rate_fraction).quantize(Decimal("0.01"))
    def exc_to_inc(self,n):
        return n+self.exc_to_vat(n)
    def at(self,date):
        """Return the VatRate object that replaces this one at the
        specified date.  If there is no suitable VatRate object,
        returns self.

        """
        return object_session(self).\
            query(VatRate).\
            filter_by(band=self.band).\
            filter(VatRate.active<=date).\
            order_by(desc(VatRate.active)).\
            first() or self

class VatBand(Base,Vat):
    __tablename__='vat'
    band=Column(CHAR(1),primary_key=True)
    def __repr__(self):
        return "<VatBand('%s')>"%(self.band,)

class VatRate(Base,Vat):
    __tablename__='vatrates'
    band=Column(CHAR(1),ForeignKey('vat.band'),primary_key=True)
    active=Column(Date,nullable=False,primary_key=True)
    def __repr__(self):
        return "<VatRate('%s',%s,'%s')>"%(self.band,self.rate,self.active)

class PayType(Base):
    __tablename__='paytypes'
    paytype=Column(String(8),nullable=False,primary_key=True)
    description=Column(String(10),nullable=False)
    def __repr__(self):
        return "<PayType('%s')>"%(self.paytype,)

sessions_seq=Sequence('sessions_seq')

class Session(Base):
    """As well as a start and end time, sessions have an accounting
   date.  This is to cope with sessions being closed late
   (eg. subsequent date) or started early.  In the accounts, the
   session takings will be recorded against the session date.

   """
    __tablename__='sessions'

    id=Column('sessionid',Integer,sessions_seq,primary_key=True)
    starttime=Column(DateTime,nullable=False)
    endtime=Column(DateTime)
    date=Column('sessiondate',Date,nullable=False)

    def __init__(self,date):
        self.date=date
        self.starttime=datetime.datetime.now()

    def __repr__(self):
        return "<Session(%s,'%s')>"%(self.id,self.date,)
    def __unicode__(self):
        return u"Session %d"%self.id
    @property
    def tillweb_url(self):
        return "session/%d/"%self.id
    @property
    def dept_totals(self):
        "Transaction lines broken down by Department."
        return object_session(self).\
            query(Department,func.sum(
                Transline.items*Transline.amount)).\
            select_from(Session).\
            filter(Session.id==self.id).\
            join(Transaction,Transline,Department).\
            order_by(Department.id).\
            group_by(Department).all()
    @property
    def total(self):
        "Total of all transaction lines."
        return object_session(self).\
            query(func.sum(Transline.items*Transline.amount)).\
            select_from(Session).\
            filter(Session.id==self.id).\
            join(Transaction,Transline).scalar()
    @property
    def actual_total(self):
        "Total of all payments."
        return sum(at.amount for at in self.actual_totals)
    @property
    def error(self):
        "Difference between actual total and transaction line total."
        return self.actual_total-self.total
    @property
    def vatband_totals(self):
        """Transaction lines broken down by VatBand.

        Returns (VatRate,amount,ex-vat amount,vat)

        """
        vt=object_session(self).\
            query(VatBand,func.sum(Transline.items*Transline.amount)).\
            select_from(Session).\
            filter(Session.id==self.id).\
            join(Transaction,Transline,Department,VatBand).\
            order_by(VatBand.band).\
            group_by(VatBand).\
            all()
        vt=[(a.at(self.date),b) for a,b in vt]
        return [(a,b,a.inc_to_exc(b),a.inc_to_vat(b)) for a,b in vt]
    # It may become necessary to add a further query here that returns
    # transaction lines broken down by Business.  Must take into
    # account multiple VAT rates per business - probably best to do
    # the summing client side using the methods in the VatRate object.
    @property
    def stock_sold(self):
        "Returns a list of (StockType,quantity) tuples."
        return object_session(self).\
            query(StockType,func.sum(StockOut.qty)).\
            select_from(Transaction).\
            filter(Transaction.sessionid==self.id).\
            join(Transline).\
            join(StockOut,StockOut.id==Transline.stockref).\
            join(StockItem,StockType).\
            group_by(StockType,Transline.dept_id).\
            order_by(Transline.dept_id,desc(func.sum(StockOut.qty))).\
            all()
    @classmethod
    def current(cls,session):
        """Return the currently open session, or None if no session is
        open.  Must be passed a suitable sqlalchemy session in which
        to run the query.

        """
        return session.query(Session).filter_by(endtime=None).first()

add_ddl(Session.__table__,"""
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
""","""
DROP TRIGGER max_one_session_open ON sessions;
DROP FUNCTION check_max_one_session_open();
""")

class SessionTotal(Base):
    __tablename__='sessiontotals'
    sessionid=Column(Integer,ForeignKey('sessions.sessionid'),primary_key=True)
    paytype_id=Column('paytype',String(8),ForeignKey('paytypes.paytype'),
                      primary_key=True)
    amount=Column(Numeric(10,2),nullable=False)
    session=relationship(Session,backref=backref('actual_totals',order_by=desc('paytype')))
    paytype=relationship(PayType)
    def __repr__(self):
        return "<SessionTotal(%s,'%s','%s')>"%(
            self.sessionid,self.paytype,self.amount)

transactions_seq=Sequence('transactions_seq')
class Transaction(Base):
    __tablename__='transactions'
    id=Column('transid',Integer,transactions_seq,nullable=False,
              primary_key=True)
    sessionid=Column(Integer,ForeignKey('sessions.sessionid'),
                     nullable=True) # Null sessionid for deferred transactions
    notes=Column(String(60))
    closed=Column(Boolean,nullable=False,default=False)
    session=relationship(Session,backref=backref('transactions',order_by=id))
    @hybrid_property
    def total(self):
        return sum(tl.items*tl.amount for tl in self.lines)
    @property
    def tillweb_url(self):
        return "transaction/%d/"%self.id
    def __unicode__(self):
        return u"Transaction %d"%self.id
    def __repr__(self):
        return "<Transaction(%s,%s,%s)>"%(self.id,self.sessionid,self.closed)

# Rules that depend on the existence of more than one table must be
# added to the metadata rather than the table - they will be created
# after all tables, and dropped before any tables.
add_ddl(Transaction.__table__,"""
CREATE OR REPLACE FUNCTION check_transaction_balances() RETURNS trigger AS $$
BEGIN
  IF NEW.closed=true
    AND (SELECT sum(amount*items) FROM translines
      WHERE transid=NEW.transid)!=
      (SELECT sum(amount) FROM payments WHERE transid=NEW.transid)
  THEN RAISE EXCEPTION 'transaction %%d does not balance', NEW.transid;
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;
CREATE CONSTRAINT TRIGGER close_only_if_balanced
  AFTER INSERT OR UPDATE ON transactions
  FOR EACH ROW EXECUTE PROCEDURE check_transaction_balances();
""","""
DROP TRIGGER close_only_if_balanced ON transactions;
DROP FUNCTION check_transaction_balances();
""")

payments_seq=Sequence('payments_seq',start=1)
class Payment(Base):
    __tablename__='payments'
    id=Column('paymentid',Integer,payments_seq,nullable=False,
              primary_key=True)
    transid=Column(Integer,ForeignKey('transactions.transid'),
                   nullable=False)
    amount=Column(Numeric(10,2),nullable=False)
    paytype_id=Column('paytype',String(8),ForeignKey('paytypes.paytype'),
                      nullable=False)
    ref=Column(String(16))
    time=Column(DateTime,nullable=False) # default?
    transaction=relationship(Transaction,
                             backref=backref('payments',order_by=id))
    paytype=relationship(PayType)
    def __repr__(self):
        return "<Payment(%s,%s,%s,'%s')>"%(self.id,self.transid,self.amount,
                                           self.paytype_id)

add_ddl(Payment.__table__,"""
CREATE OR REPLACE FUNCTION check_modify_closed_trans_payment() RETURNS trigger AS $$
BEGIN
  IF (SELECT closed FROM transactions WHERE transid=NEW.transid)=true
  THEN RAISE EXCEPTION 'attempt to modify closed transaction %%d payment', NEW.transid;
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;
CREATE CONSTRAINT TRIGGER no_modify_closed
  AFTER INSERT OR UPDATE ON payments
  FOR EACH ROW EXECUTE PROCEDURE check_modify_closed_trans_payment();
""","""
DROP TRIGGER no_modify_closed ON payments;
DROP FUNCTION check_modify_closed_trans_payment();
""")

class PingapintPayment(Base):
    __tablename__='pingapint'
    id=Column('paymentid',Integer,ForeignKey('payments.paymentid'),
              nullable=False,primary_key=True)
    amount=Column(Numeric(10,2),nullable=False)
    vid=Column(Integer,nullable=False)
    json_data=Column(Text,nullable=False)
    reimbursed=Column(Date)
    def __repr__(self):
        return "<PingapintPayment(%s,%s)>"%(self.id,self.amount)

class Department(Base):
    __tablename__='departments'
    id=Column('dept',Integer,nullable=False,primary_key=True)
    description=Column(String(20),nullable=False)
    vatband=Column(CHAR(1),ForeignKey('vat.band'),nullable=False)
    def __unicode__(self):
        return u"%s"%(self.description,)
    def __repr__(self):
        return "<Department(%s,'%s')>"%(self.id,self.description)

class TransCode(Base):
    __tablename__='transcodes'
    code=Column('transcode',CHAR(1),nullable=False,primary_key=True)
    description=Column(String(20))
    def __unicode__(self):
        return u"%s"%(self.description,)
    def __repr__(self):
        return "<TransCode('%s','%s')>"%(self.code,self.description)

translines_seq=Sequence('translines_seq',start=1)
class Transline(Base):
    __tablename__='translines'
    id=Column('translineid',Integer,translines_seq,nullable=False,
              primary_key=True)
    transid=Column(Integer,ForeignKey('transactions.transid'),
                   nullable=False)
    items=Column(Integer,nullable=False)
    amount=Column(Numeric(10,2),nullable=False)
    dept_id=Column('dept',Integer,ForeignKey('departments.dept'),
                   nullable=False)
    source=Column(String(10))
    stockref=Column(Integer)
    transcode=Column(CHAR(1),ForeignKey('transcodes.transcode'),nullable=False)
    time=Column(DateTime,nullable=False,server_default=func.current_timestamp())
    text=Column(Text)
    transaction=relationship(Transaction,backref=backref('lines',order_by=id))
    department=relationship(Department)
    @hybrid_property
    def total(self): return self.items*self.amount
    def __repr__(self):
        return "<Transline(%s,%s)>"%(self.id,self.transid)

add_ddl(Transline.__table__,"""
CREATE FUNCTION check_modify_closed_trans_line() RETURNS trigger AS $$
BEGIN
  IF (SELECT closed FROM transactions WHERE transid=NEW.transid)=true
  THEN RAISE EXCEPTION 'attempt to modify closed transaction %%d line', NEW.transid;
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;
CREATE CONSTRAINT TRIGGER no_modify_closed
  AFTER INSERT OR UPDATE ON translines
  FOR EACH ROW EXECUTE PROCEDURE check_modify_closed_trans_line();
""","""
DROP TRIGGER no_modify_closed ON translines;
DROP FUNCTION check_modify_closed_trans_line();
""")

suppliers_seq=Sequence('suppliers_seq')
class Supplier(Base):
    __tablename__='suppliers'
    id=Column('supplierid',Integer,nullable=False,primary_key=True)
    name=Column(String(60),nullable=False)
    tel=Column(String(20))
    email=Column(String(60))
    def __repr__(self):
        return "<Supplier(%s,'%s')>"%(self.id,self.name)

deliveries_seq=Sequence('deliveries_seq')
class Delivery(Base):
    __tablename__='deliveries'
    id=Column('deliveryid',Integer,nullable=False,primary_key=True)
    supplierid=Column(Integer,ForeignKey('suppliers.supplierid'),
                      nullable=False)
    docnumber=Column(String(40))
    date=Column(Date,nullable=False,server_default=func.current_timestamp())
    checked=Column(Boolean,nullable=False,server_default=text('false'))
    supplier=relationship(Supplier,backref=backref('deliveries',order_by=id))
    @property
    def tillweb_url(self):
        return "delivery/%d/"%(self.id,)
    def __repr__(self):
        return "<Delivery(%s)>"%(self.id,)

class UnitType(Base):
    __tablename__='unittypes'
    id=Column('unit',String(10),nullable=False,primary_key=True)
    name=Column(String(30),nullable=False)
    def __unicode__(self):
        return u"%s"%name
    def __repr__(self):
        return "<UnitType('%s','%s')>"%(self.id,self.name)

class StockUnit(Base):
    __tablename__='stockunits'
    id=Column('stockunit',String(8),nullable=False,primary_key=True)
    name=Column(String(30),nullable=False)
    unit_id=Column('unit',String(10),ForeignKey('unittypes.unit'),
                   nullable=False)
    size=Column(Numeric(5,1),nullable=False)
    unit=relationship(UnitType)
    def __repr__(self):
        return "<StockUnit('%s',%s)>"%(self.id,self.size)

stocktypes_seq=Sequence('stocktypes_seq')
class StockType(Base):
    __tablename__='stocktypes'
    id=Column('stocktype',Integer,stocktypes_seq,nullable=False,
              primary_key=True)
    dept_id=Column('dept',Integer,ForeignKey('departments.dept'),nullable=False)
    manufacturer=Column(String(30),nullable=False)
    name=Column(String(30),nullable=False)
    shortname=Column(String(25),nullable=False)
    abv=Column(Numeric(3,1))
    unit_id=Column('unit',String(10),ForeignKey('unittypes.unit'),
                   nullable=False)
    department=relationship(Department)
    unit=relationship(UnitType)
    @hybrid_property
    def fullname(self):
        return self.manufacturer+' '+self.name
    @property
    def tillweb_url(self):
        return "stocktype/%d/"%self.id
    def __unicode__(self):
        return u"%s %s"%(self.manufacturer,self.name)
    def __repr__(self):
        return "<StockType(%s,'%s','%s')>"%(self.id,self.manufacturer,self.name)

class FinishCode(Base):
    __tablename__='stockfinish'
    id=Column('finishcode',String(8),nullable=False,primary_key=True)
    description=Column(String(50),nullable=False)
    def __unicode__(self):
        return u"%s"%self.description
    def __repr__(self):
        return "<FinishCode('%s','%s')>"%(self.id,self.description)

stock_seq=Sequence('stock_seq')
class StockItem(Base):
    __tablename__='stock'
    id=Column('stockid',Integer,stock_seq,nullable=False,primary_key=True)
    deliveryid=Column(Integer,ForeignKey('deliveries.deliveryid'),
                      nullable=False)
    stocktype_id=Column('stocktype',Integer,ForeignKey('stocktypes.stocktype'),
                        nullable=False)
    stockunit_id=Column('stockunit',String(8),
                        ForeignKey('stockunits.stockunit'),nullable=False)
    costprice=Column(Numeric(7,2)) # ex VAT
    saleprice=Column(Numeric(5,2),nullable=False) # inc VAT
    onsale=Column(DateTime)
    finished=Column(DateTime)
    finishcode_id=Column('finishcode',String(8),
                         ForeignKey('stockfinish.finishcode'))
    bestbefore=Column(Date)
    delivery=relationship(Delivery,backref=backref('items',order_by=id))
    stocktype=relationship(StockType,backref=backref('items',order_by=id))
    stockunit=relationship(StockUnit)
    finishcode=relationship(FinishCode)
    # used and remaining column properties are added after the
    # StockOut class is defined
    @property
    def checkdigits(self):
        """
        Return three digits derived from a stock ID number.  These
        digits can be printed on stock labels; knowledge of the digits
        can be used to confirm that a member of staff really does have
        a particular item of stock in front of them.
        
        """
        a=hashlib.sha1("quicktill-%d-quicktill"%self.id)
        return str(int(a.hexdigest(),16))[-3:]
    @property
    def tillweb_url(self):
        return "stock/%d/"%self.id
    def __repr__(self):
        return "<StockItem(%s)>"%(self.id,)

class AnnotationType(Base):
    __tablename__='annotation_types'
    id=Column('atype',String(8),nullable=False,primary_key=True)
    description=Column(String(20),nullable=False)
    def __unicode__(self):
        return u"%s"%(self.description,)
    def __repr__(self):
        return "<AnnotationType('%s','%s')>"%(self.id,self.description)

stock_annotation_seq=Sequence('stock_annotation_seq');
class StockAnnotation(Base):
    __tablename__='stock_annotations'
    id=Column(Integer,stock_annotation_seq,nullable=False,primary_key=True)
    stockid=Column(Integer,ForeignKey('stock.stockid'),nullable=False)
    atype=Column(String(8),ForeignKey('annotation_types.atype'),nullable=False)
    time=Column(DateTime,nullable=False,server_default=func.current_timestamp())
    stockitem=relationship(StockItem,backref=backref(
            'annotations',order_by=time))
    text=Column(String(60),nullable=False)
    type=relationship(AnnotationType)
    def __repr__(self):
        return "<StockAnnotation(%s,%s,'%s','%s')>"%(
            self.id,self.stockitem,self.atype,self.text)

class RemoveCode(Base):
    __tablename__='stockremove'
    id=Column('removecode',String(8),nullable=False,primary_key=True)
    reason=Column(String(80))
    def __unicode__(self):
        return u"%s"%(self.reason,)
    def __repr__(self):
        return "<RemoveCode('%s','%s')>"%(self.id,self.reason)

stockout_seq=Sequence('stockout_seq')
class StockOut(Base):
    __tablename__='stockout'
    id=Column('stockoutid',Integer,stockout_seq,nullable=False,primary_key=True)
    stockid=Column(Integer,ForeignKey('stock.stockid'),nullable=False)
    qty=Column(Numeric(5,1),nullable=False)
    removecode_id=Column('removecode',String(8),
                         ForeignKey('stockremove.removecode'),nullable=False)
    translineid=Column(Integer,ForeignKey('translines.translineid'))
    time=Column(DateTime,nullable=False,server_default=func.current_timestamp())
    stockitem=relationship(StockItem,backref=backref('out',order_by=id))
    removecode=relationship(RemoveCode)
    transline=relationship(Transline) # No backref - stockref is not foreign key
    def __repr__(self):
        return "<StockOut(%s,%s)>"%(self.id,self.stockid)

# These are added to the StockItem class here because they refer
# directly to the StockOut class, defined just above.
StockItem.used=column_property(
    select([func.coalesce(func.sum(StockOut.qty),text("0.0"))]).\
        correlate(StockItem.__table__).\
        where(StockOut.stockid==StockItem.id).\
        label('used'))
StockItem.remaining=column_property(
    select([select([StockUnit.size],StockUnit.id==StockItem.stockunit_id
                   ).correlate(StockItem.__table__) -
                func.coalesce(func.sum(StockOut.qty),text("0.0"))]).\
        where(StockOut.stockid==StockItem.id).\
        label('remaining'))

stocklines_seq=Sequence('stocklines_seq',start=100)
class StockLine(Base):
    __tablename__='stocklines'
    id=Column('stocklineid',Integer,nullable=False,primary_key=True)
    name=Column(String(30),nullable=False,unique=True)
    location=Column(String(20),nullable=False)
    capacity=Column(Integer)
    dept_id=Column('dept',Integer,ForeignKey('departments.dept'),
                   nullable=False)
    pullthru=Column(Numeric(5,2))
    department=relationship(Department)
    # capacity and pullthru can't both be non-null at the same time
    __table_args__=(
        CheckConstraint(
            "capacity IS NULL OR pullthru IS NULL",
            name="line_type_constraint"),)
    @property
    def tillweb_url(self):
        return "stockline/%d/"%self.id
    def __repr__(self):
        return "<StockLine(%s,'%s')>"%(self.id,self.name)

def location_summary(session,location):
    """Return a list of (StockLine,StockItem) tuples corresponding to
    the requested location.  (Note that, since there may be multiple
    stock items on a line, some StockLine objects may be returned more
    than once.)  Does not return StockLines that have no stock on
    sale.

    """
    return session.query(StockLine,StockItem).\
        join(StockOnSale).\
        join(StockItem).\
        filter(StockLine.location==location).\
        order_by(StockLine.dept_id,StockLine.name).\
        options(joinedload('stockonsale')).\
        options(joinedload('stockonsale.stockitem')).\
        options(joinedload('stockonsale.stockitem.stocktype')).\
        all()

# In the original createdb script, this table doesn't actually have a
# primary key: it just has a UNIQUE constraint on stockid.  For our
# purposes, that's just the same as stockid being the primary key and
# it shouldn't matter that we'll be working with legacy databases that
# are different.
class StockOnSale(Base):
    __tablename__='stockonsale'
    stocklineid=Column(Integer,ForeignKey('stocklines.stocklineid'),
                       nullable=False)
    stockid=Column(Integer,ForeignKey('stock.stockid'),
                   nullable=False,primary_key=True)
    displayqty=Column(Integer)
    stockline=relationship(StockLine,backref='stockonsale')
    stockitem=relationship(
        StockItem,backref=backref('stockonsale',uselist=False))
    def __repr__(self):
        return "<StockOnSale(%s,%s)>"%(self.stocklineid,self.stockid)

class KeyboardBinding(Base):
    __tablename__='keyboard'
    layout=Column(Integer,nullable=False,primary_key=True)
    keycode=Column(String(20),nullable=False,primary_key=True)
    menukey=Column(String(20),nullable=False,primary_key=True)
    stocklineid=Column(Integer,ForeignKey('stocklines.stocklineid'),
                       nullable=False)
    qty=Column(Numeric(5,2),nullable=False)
    stockline=relationship(StockLine,backref='keyboard_bindings')
    def __repr__(self):
        return "<KeyboardBinding(%s,'%s','%s',%s)>"%(
            self.layout,self.keycode,self.menukey,self.stocklineid)

class KeyCap(Base):
    __tablename__='keycaps'
    layout=Column(Integer,nullable=False,primary_key=True)
    keycode=Column(String(20),nullable=False,primary_key=True)
    keycap=Column(String(30))
    def __repr__(self):
        return "<KeyCap(%s,'%s','%s')>"%(self.layout,self.keycode,self.keycap)

# This is the association table for stocklines to stocktypes.
class StockLineTypeLog(Base):
    __tablename__='stockline_stocktype_log'
    stocklineid=Column(Integer,
                       ForeignKey('stocklines.stocklineid',ondelete='CASCADE'),
                       nullable=False,primary_key=True)
    stocktype_id=Column('stocktype',Integer,
                        ForeignKey('stocktypes.stocktype',ondelete='CASCADE'),
                        nullable=False,primary_key=True)
    stockline=relationship(StockLine,backref='stocktype_log')
    stocktype=relationship(StockType,backref='stockline_log')
    def __repr__(self):
        return "<StockLineTypeLog(%s,%s)>"%(self.stocklineid,self.stocktype_id)

add_ddl(StockLineTypeLog.__table__,"""
CREATE OR REPLACE RULE ignore_duplicate_stockline_types AS
       ON INSERT TO stockline_stocktype_log
       WHERE (NEW.stocklineid,NEW.stocktype)
       IN (SELECT stocklineid,stocktype FROM stockline_stocktype_log)
       DO INSTEAD NOTHING
""","""
DROP RULE ignore_duplicate_stockline_types ON stockline_stocktype_log
""")

add_ddl(metadata,"""
CREATE OR REPLACE RULE log_stocktype AS ON INSERT TO stockonsale
       DO ALSO
       INSERT INTO stockline_stocktype_log VALUES
       (NEW.stocklineid,(SELECT stocktype FROM stock
       	WHERE stock.stockid=NEW.stockid))
""","""
DROP RULE log_stocktype ON stockonsale
""")

class User(Base):
    __tablename__='users'
    code=Column(CHAR(2),nullable=False,primary_key=True)
    name=Column(String(30),nullable=False)
    def __repr__(self):
        return "<User('%s','%s')>"%(self.code,self.name)

# stockinfo view definition here?  Probably don't need to use it, but
# we might still want to emit the CREATE VIEW command sometimes.

# stockqty view definition here?

# businesstotals view definition

# Lots of rule definitions here - see createdb

# Add indexes here
Index('translines_transid_key',Transline.transid)
Index('payments_transid_key',Payment.transid)
Index('transactions_sessionid_key',Transaction.sessionid)
Index('stock_annotations_stockid_key',StockAnnotation.stockid)
Index('stockout_stockid_key',StockOut.stockid)

# The "find free drinks on this day" function is speeded up
# considerably by an index on stockout.time::date
# sqlalchemy currently doesn't support creating indexes on
# expressions.  We need to use raw DDL for this:
add_ddl(StockOut.__table__,
        "CREATE INDEX stockout_date_key ON stockout ( (time::date) )",
        None)

Index('stockout_translineid_key',StockOut.translineid)
Index('translines_time_key',Transline.time)

foodorder_seq=Sequence('foodorder_seq')

if __name__=='__main__':
    from sqlalchemy import create_engine
    engine=create_engine('postgresql+psycopg2:///testdb',echo=True)
    SM=sessionmaker(bind=engine)
    metadata.bind=engine
    metadata.create_all()
    session=SM()
    s=Session('2013-01-10')
    session.add(s)
    print s
    session.commit()
    metadata.drop_all()
