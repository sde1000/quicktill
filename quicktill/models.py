from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column,Integer,String,DateTime,Date,ForeignKey,Numeric,CHAR,Boolean,Text
from sqlalchemy.schema import Sequence
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
