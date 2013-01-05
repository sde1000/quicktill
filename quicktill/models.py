from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column,Integer,String,DateTime,Date,ForeignKey,Numeric,CHAR,Boolean,Text
from sqlalchemy.schema import Sequence,Index,MetaData
from sqlalchemy.sql.expression import text
from sqlalchemy.orm import relationship,backref

import datetime

Base=declarative_base()

class Business(Base):
    __tablename__='businesses'
    id=Column('business',Integer,primary_key=True)
    name=Column(String(80))
    abbrev=Column(String(20))
    address=Column(String(200))
    vatno=Column(String(30))

    def __repr__(self):
        return "<Business('%s')>"%(self.name,)

class VatBand(Base):
    __tablename__='vat'
    band=Column(CHAR(1),primary_key=True)
    rate=Column(Numeric(5,2),nullable=False)
    business=Column(Integer,ForeignKey('businesses.business'))

class VatRate(Base):
    __tablename__='vatrates'
    band=Column(CHAR(1),ForeignKey('vat.band'),primary_key=True)
    rate=Column(Numeric(5,2),nullable=False)
    business=Column(Integer,ForeignKey('businesses.business'))
    active=Column(Date,nullable=False,primary_key=True)

# Vatrate function goes here
# Business function goes here

class PayType(Base):
    __tablename__='paytypes'
    paytype=Column(String(8),nullable=False,primary_key=True)
    description=Column(String(10),nullable=False)
    def __repr__(self):
        return "<PayType('%s')>"%(self.paytype,)

sessions_seq=Sequence('sessions_seq',start=1)

class Session(Base):
    """As well as a start and end time, sessions have an accounting
   date.  This is to cope with sessions being closed late
   (eg. subsequent date) or started early.  In the accounts, the
   session takings will be recorded against the session date.

   """
    __tablename__='sessions'

    id=Column('sessionid',Integer,sessions_seq,primary_key=True)
    starttime=Column(DateTime)
    endtime=Column(DateTime)
    date=Column('sessiondate',Date)

    def __init__(self,date):
        self.date=date
        self.starttime=datetime.datetime.now()

    def __repr__(self):
        return "<Session('%s')>"%(self.date,)

class SessionTotal(Base):
    __tablename__='sessiontotals'
    sessionid=Column(Integer,ForeignKey('sessions.sessionid'),primary_key=True)
    paytype=Column(String(8),ForeignKey('paytypes.paytype'),primary_key=True)
    amount=Column(Numeric(10,2),nullable=False)
    session=relationship(Session,backref=backref('totals'))
    def __repr__(self):
        return "<SessionTotal('%s','%s')>"%(self.paytype,self.amount)

transactions_seq=Sequence('transactions_seq',start=1)
class Transaction(Base):
    __tablename__='transactions'
    id=Column('transid',Integer,transactions_seq,nullable=False,
              primary_key=True)
    session=Column('sessionid',Integer,ForeignKey('sessions.sessionid'),
                   nullable=True) # Null sessionid for deferred transactions
    notes=Column(String(60))
    closed=Column(Boolean,nullable=False,default=False)

payments_seq=Sequence('payments_seq',start=1)
class Payment(Base):
    __tablename__='payments'
    id=Column('paymentid',Integer,payments_seq,nullable=False,
              primary_key=True)
    transaction=Column('transid',Integer,ForeignKey('transactions.transid'),
                       nullable=False)
    amount=Column(Numeric(10,2),nullable=False)
    paytype=Column(String(8),ForeignKey('paytypes.paytype'),nullable=False)
    ref=Column(String(16))
    time=Column(DateTime,nullable=False) # default?

class PingapintPayment(Base):
    __tablename__='pingapint'
    id=Column('paymentid',Integer,ForeignKey('payments.paymentid'),
              nullable=False,primary_key=True)
    amount=Column(Numeric(10,2),nullable=False)
    vid=Column(Integer,nullable=False)
    json_data=Column(Text,nullable=False)
    reimbursed=Column(Date)

class Department(Base):
    __tablename__='departments'
    id=Column('dept',Integer,nullable=False,primary_key=True)
    description=Column(String(20),nullable=False)
    vatband=Column(CHAR(1),ForeignKey('vat.band'),nullable=False)

class TransCode(Base):
    __tablename__='transcodes'
    code=Column('transcode',CHAR(1),nullable=False,primary_key=True)
    description=Column(String(20))

translines_seq=Sequence('translines_seq',start=1)
class Transline(Base):
    __tablename__='translines'
    id=Column('translineid',Integer,translines_seq,nullable=False,
              primary_key=True)
    transaction=Column('transid',Integer,ForeignKey('transactions.transid'),
                       nullable=False)
    items=Column(Integer,nullable=False)
    amount=Column(Numeric(10,2),nullable=False)
    department=Column('dept',Integer,ForeignKey('departments.dept'),
                      nullable=False)
    source=Column(String(10))
    stockref=Column(Integer)
    transcode=Column(CHAR(1),ForeignKey('transcodes.transcode'),nullable=False)
    time=Column(DateTime,nullable=False,server_default=text('NOW()'))
    text=Column(Text)

# Stock control information below here

suppliers_seq=Sequence('suppliers_seq')
class Supplier(Base):
    __tablename__='suppliers'
    id=Column('supplierid',Integer,nullable=False,primary_key=True)
    name=Column(String(60),nullable=False)
    tel=Column(String(20))
    email=Column(String(60))

deliveries_seq=Sequence('deliveries_seq')
class Delivery(Base):
    __tablename__='deliveries'
    id=Column('deliveryid',Integer,nullable=False,primary_key=True)
    supplier=Column('supplierid',Integer,ForeignKey('suppliers.supplierid'),
                    nullable=False)
    docnumber=Column(String(40))
    date=Column(Date,nullable=False,server_default=text('NOW()'))
    checked=Column(Boolean,nullable=False,server_default=text('false'))

class UnitType(Base):
    __tablename__='unittypes'
    id=Column('unit',String(10),nullable=False,primary_key=True)
    name=Column(String(30),nullable=False)

class StockUnit(Base):
    __tablename__='stockunits'
    id=Column('stockunit',String(8),nullable=False,primary_key=True)
    name=Column(String(30),nullable=False)
    unit=Column(String(10),ForeignKey('unittypes.unit'),nullable=False)
    size=Column(Numeric(5,1),nullable=False)

stocktypes_seq=Sequence('stocktypes_seq')
class StockType(Base):
    __tablename__='stocktypes'
    id=Column('stocktype',Integer,stocktypes_seq,nullable=False,
              primary_key=True)
    dept=Column(Integer,ForeignKey('departments.dept'),nullable=False)
    manufacturer=Column(String(30),nullable=False)
    name=Column(String(30),nullable=False)
    shortname=Column(String(25),nullable=False)
    abv=Column(Numeric(3,1))
    unit=Column(String(10),ForeignKey('unittypes.unit'),nullable=False)

class FinishCode(Base):
    __tablename__='stockfinish'
    id=Column('finishcode',String(8),nullable=False,primary_key=True)
    description=Column(String(50),nullable=False)

stock_seq=Sequence('stock_seq')
class StockItem(Base):
    __tablename__='stock'
    id=Column('stockid',Integer,stock_seq,nullable=False,primary_key=True)
    delivery=Column('deliveryid',Integer,ForeignKey('deliveries.deliveryid'),
                    nullable=False)
    stocktype=Column('stocktype',Integer,ForeignKey('stocktypes.stocktype'),
                     nullable=False)
    stockunit=Column(String(8),ForeignKey('stockunits.stockunit'),
                     nullable=False)
    costprice=Column(Numeric(7,2)) # ex VAT
    saleprice=Column(Numeric(5,2),nullable=False) # inc VAT
    onsale=Column(DateTime)
    finished=Column(DateTime)
    finishcode=Column(String(8),ForeignKey('stockfinish.finishcode'))
    bestbefore=Column(Date)

class AnnotationType(Base):
    __tablename__='annotation_types'
    id=Column('atype',String(8),nullable=False,primary_key=True)
    description=Column(String(20),nullable=False)

# This table needs a primary key if it is to be accessed through the ORM.
#class StockAnnotation(Base):
#    __tablename__='stock_annotations'
#    stockitem=Column('stockid',Integer,ForeignKey('stock.stockid'),
#                     nullable=False)
#    atype=Column(String(8),ForeignKey('annotation_types.atype'),nullable=False)
#    time=Column(DateTime,nullable=False,server_default=text('NOW()'))
#    text=Column(String(60),nullable=False)

class RemoveCode(Base):
    __tablename__='stockremove'
    id=Column('removecode',String(8),nullable=False,primary_key=True)
    reason=Column(String(80))

stockout_seq=Sequence('stockout_seq')
class StockOut(Base):
    __tablename__='stockout'
    id=Column('stockoutid',Integer,stockout_seq,nullable=False,primary_key=True)
    stockitem=Column('stockid',Integer,ForeignKey('stock.stockid'),
                     nullable=False)
    qty=Column(Numeric(5,1),nullable=False)
    removecode=Column(String(8),ForeignKey('stockremove.removecode'),
                      nullable=False)
    transline=Column('translineid',Integer,ForeignKey('translines.translineid'))
    time=Column(DateTime,nullable=False,server_default=text('NOW()'))

stocklines_seq=Sequence('stocklines_seq',start=100)
class StockLine(Base):
    __tablename__='stocklines'
    id=Column('stocklineid',Integer,nullable=False,primary_key=True)
    name=Column(String(30),nullable=False,unique=True)
    location=Column(String(20),nullable=False)
    capacity=Column(Integer)
    department=Column('dept',Integer,ForeignKey('departments.dept'),
                      nullable=False)
    pullthru=Column(Numeric(5,2))
    # Maybe add a constraint to say capacity and pullthru can't both be
    # non-null at the same time

# This table doesn't actually have a primary key, it just has a UNIQUE
# constraint on stockid.  Perhaps rewrite so that the stock on sale is
# accessed through the stockline object.
class StockOnSale(Base):
    __tablename__='stockonsale'
    stockline=Column('stocklineid',Integer,ForeignKey('stocklines.stocklineid'),
                     nullable=False)
    stockitem=Column('stockid',Integer,ForeignKey('stock.stockid'),
                     nullable=False,primary_key=True)
    displayqty=Column(Integer)

class KeyboardBinding(Base):
    __tablename__='keyboard'
    layout=Column(Integer,nullable=False,primary_key=True)
    keycode=Column(String(20),nullable=False,primary_key=True)
    menukey=Column(String(20),nullable=False,primary_key=True)
    stockline=Column('stocklineid',Integer,ForeignKey('stocklines.stocklineid'),
                     nullable=False)
    qty=Column(Numeric(5,2),nullable=False)

class KeyCap(Base):
    __tablename__='keycaps'
    layout=Column(Integer,nullable=False,primary_key=True)
    keycode=Column(String(20),nullable=False,primary_key=True)
    keycap=Column(String(30))

class StockLineTypeLog(Base):
    __tablename__='stockline_stocktype_log'
    stockline=Column('stocklineid',Integer,
                     ForeignKey('stocklines.stocklineid',ondelete='CASCADE'),
                     nullable=False,primary_key=True)
    stocktype=Column(Integer,
                     ForeignKey('stocktypes.stocktype',ondelete='CASCADE'),
                     nullable=False,primary_key=True)
# Code for ignore_duplicate_stockline_types rule here
# Code for log_stocktype rule here

class User(Base):
    __tablename__='users'
    code=Column(CHAR(2),nullable=False,primary_key=True)
    name=Column(String(30),nullable=False)

# stockinfo view definition here?  Probably don't need to use it, but
# we might still want to emit the CREATE VIEW command sometimes.

# stockqty view definition here?

# businesstotals view definition

# Lots of rule definitions here - see createdb

# Add indexes here
Index('translines_transid_key',Transline.transaction)
Index('payments_transid_key',Payment.transaction)
Index('transactions_sessionid_key',Transaction.session)
#Index('stock_annotations_stockid_key',Annotation.stockitem)
Index('stockout_stockid_key',StockOut.stockitem)

# sqlalchemy currently doesn't support creating indexes on
# expressions.  We need to use raw DDL for the following:
# CREATE INDEX stockout_date_key ON stockout ( (time::date) );

Index('stockout_translineid_key',StockOut.transline)
Index('translines_time_key',Transline.time)

foodorder_seq=Sequence('foodorder_seq')

if __name__=='__main__':
    from sqlalchemy import create_engine
    engine=create_engine('postgresql+psycopg2:///testdb', echo=True)
    Base.metadata.bind=engine
    Base.metadata.create_all()
    Base.metadata.drop_all()
