# Till database handling routines

# Various parts of the UI call on these routines to work out what the
# hell is going on.  We try to ensure the database constraints are
# never broken here, but that's not really a substitute for
# implementing them in the database itself.

import pgdb,time

con=pgdb.connect("localhost:till")

### Convenience functions

def mkstructtime(d):
    "Take a date returned from the database and convert to a time.struct_time"
    if d is not None:
        if len(d)==10:
            return time.strptime(d,"%Y-%m-%d")
        return time.strptime(d[0:19],"%Y-%m-%d %H:%M:%S")
    return None

def mkdate(st):
    "Take a time.struct_time and return a date"
    if st is not None:
        return time.strftime("%Y-%m-%d",st)
    return None

def execone(cur,c,*args):
    "Execute c and return the single result. Does not commit."
    cur.execute(c,*args)
    r=cur.fetchone()
    if not r: return None
    return r[0]

def ticket(cur,seq):
    "Fetch a new serial number from the named sequence"
    return execone(cur,"SELECT nextval(%s)",(seq,))

### Functions relating to the transactions,lines,payments tables

def trans_new(note=None):
    "Create a new transaction and return its number"
    # Check that there's a current session
    s=session_current()
    if not s: return None
    cur=con.cursor()
    t=ticket(cur,"transactions_seq")
    cur.execute("INSERT INTO transactions (transid,sessionid,notes) "
                "VALUES (%d,%d,%s)",(t,s[0],note))
    con.commit()
    return t

def trans_closed(trans):
    cur=con.cursor()
    return execone(cur,"SELECT closed FROM transactions WHERE transid=%d",(trans,))

# See also stock_sell()

def trans_addline(trans,dept,items,amountper,source,transcode):
    "Insert a line into a transaction that has no associated stock record"
    cur=con.cursor()
    lid=ticket(cur,"translines_seq")
    cur.execute("INSERT INTO translines (translineid,transid,items,amount,"
                "dept,source,transcode) VALUES (%d,%d,%d,%f,%d,%s,%s)",
                (lid,trans,items,amountper,dept,source,transcode))
    con.commit()
    return lid

def trans_additems(lid,items):
    "Update an existing line with additional items"
    cur=con.cursor()
    # XXX check the transaction is not closed
    cur.execute("UPDATE translines SET items=items+%d "
                "WHERE translines.translineid=%d",(items,lid))
    con.commit()

def trans_getline(lid):
    "Retrieve information about a transaction line"
    cur=con.cursor()
    cur.execute("SELECT translines.transid,translines.items,"
                "translines.amount,translines.dept,departments.description,"
                "translines.stockref,translines.transcode FROM translines "
                "INNER JOIN departments ON translines.dept=departments.dept "
                "WHERE translines.translineid=%d",(lid,))
    return cur.fetchone()

def trans_getlines(trans):
    "Retrieve lines and payments for a transaction"
    cur=con.cursor()
    cur.execute("SELECT translineid FROM translines WHERE transid=%d "
                "ORDER BY translineid",(trans,))
    lines=[x[0] for x in cur.fetchall()]
    cur.execute("SELECT amount,paytype FROM payments WHERE transid=%d "
                "ORDER BY time ",(trans,))
    payments=cur.fetchall()
    return (lines,payments)

def trans_balance(trans):
    "Return (linestotal,paymentstotal) on a transaction"
    cur=con.cursor()
    cur.execute("SELECT (SELECT sum(amount*items) FROM translines "
                "WHERE translines.transid=%d),(SELECT sum(amount) "
                "FROM payments WHERE payments.transid=%d)",(trans,trans));
    r=cur.fetchone()
    if not r[0]: r[0]=0.0
    if not r[1]: r[1]=0.0
    return (r[0],r[1])

def trans_date(trans):
    "Return the date of the last line of the transaction"
    cur=con.cursor()
    d=execone(cur,"SELECT max(time) FROM translines WHERE transid=%d",(trans,))
    return mkstructtime(d)

def trans_addpayment(trans,type,amount):
    """Add a payment to a transaction, and return the remaining balance.
    If the remaining balance is zero, mark the transaction closed."""
    cur=con.cursor()
    cur.execute("INSERT INTO payments (transid,amount,paytype) VALUES "
                "(%d,%f,%s)",(trans,amount,type))
    (lines,payments)=trans_balance(trans)
    remain=lines-payments
    if remain==0.0:
        cur.execute("UPDATE transactions SET closed=true WHERE transid=%d",
                    (trans,))
    con.commit()
    return remain

def trans_cancel(trans):
    """Delete a transaction and everything that depends on it."""
    cur=con.cursor()
    closed=execone(cur,"SELECT closed FROM transactions WHERE transid=%d",
                   (trans,))
    if closed: return "Transaction closed"
    cur.execute("DELETE FROM stockout WHERE stockout.translineid IN "
                "(SELECT translineid FROM translines WHERE transid=%d)",(trans,))
    cur.execute("DELETE FROM payments WHERE transid=%d",(trans,))
    cur.execute("DELETE FROM translines WHERE transid=%d",(trans,))
    cur.execute("DELETE FROM transactions WHERE transid=%d",(trans,))
    con.commit()

def trans_deleteline(transline):
    cur=con.cursor()
    cur.execute("DELETE FROM stockout WHERE translineid=%d",(transline,))
    cur.execute("DELETE FROM translines WHERE translineid=%d",(transline,))
    con.commit()

def trans_incompletes():
    "Returns the list of incomplete transactions"
    cur=con.cursor()
    cur.execute("SELECT transid FROM transactions WHERE closed=false")
    return [x[0] for x in cur.fetchall()]

def trans_sessionlist(session):
    "Returns the list of transactions in a session"
    cur=con.cursor()
    cur.execute("SELECT transid FROM transactions WHERE sessionid=%d "
                "ORDER BY closed,transid DESC",(session,))
    return [x[0] for x in cur.fetchall()]

### Functions related to the stocktypes table

def stocktype_add(manufacturer,name,shortname,dept,unit,defsize,abv=None):
    cur=con.cursor()
    t=ticket(cur,'stocktypes_seq')
    cur.execute("INSERT INTO stocktypes (stocktype,dept,manufacturer,name,"
                "shortname,abv,unit,defsize) VALUES "
                "(%d,%d,%s,%s,%s,%f,%s,%s)",
                (t,dept,manufacturer,name,shortname,
                 abv,unit,defsize))
    con.commit()
    return t

### Suppliers of stock

def supplier_list():
    "Return the list of suppliers"
    cur=con.cursor()
    cur.execute("SELECT supplierid,name,tel,email FROM suppliers ORDER BY supplierid")
    return cur.fetchall()

def supplier_new(name,tel,email):
    "Create a new supplier and return the id"
    cur=con.cursor()
    sid=ticket(cur,"suppliers_seq")
    cur.execute("INSERT INTO suppliers (supplierid,name,tel,email) "
                "VALUES (%d,%s,%s,%s)",(sid,name,tel,email))
    con.commit()
    return sid

def supplier_fetch(sid):
    "Return supplier details"
    cur=con.cursor()
    cur.execute("SELECT name,tel,email FROM suppliers WHERE supplierid=%d",(sid,))
    return cur.fetchone()

def supplier_update(sid,name,tel,email):
    "Update supplier details"
    cur=con.cursor()
    cur.execute("UPDATE suppliers SET name=%s,tel=%s,email=%s WHERE supplierid=%d",
                (name,tel,email,sid))
    con.commit()

### Delivery-related functions

def delivery_get(unchecked_only=False,checked_only=False,number=None):
    cur=con.cursor()
    if number is not None:
        w="d.deliveryid=%d"%number
    elif unchecked_only and checked_only: return None
    elif unchecked_only:
        w="d.checked=false"
    elif checked_only:
        w="d.checked=true"
    else:
        w="true"
    cur.execute("SELECT d.deliveryid,d.supplierid,d.docnumber,d.date,d.checked,"
                "s.name FROM deliveries d INNER JOIN suppliers s ON "
                "d.supplierid=s.supplierid WHERE %s ORDER BY d.date DESC"%w)
    return [(r[0],r[1],r[2],mkstructtime(r[3]),r[4],r[5]) for r in cur.fetchall()]

def delivery_new(supplier):
    cur=con.cursor()
    dn=ticket(cur,"deliveries_seq")
    cur.execute("INSERT INTO deliveries (deliveryid,supplierid) VALUES "
                "(%d,%d)",(dn,supplier))
    con.commit()
    return dn

def delivery_items(delivery):
    cur=con.cursor()
    cur.execute("SELECT stockid FROM stock WHERE deliveryid=%d ORDER BY stockid",
                (delivery,))
    return [x[0] for x in cur.fetchall()]

def delivery_update(delivery,supplier,date,docnumber):
    cur=con.cursor()
    cur.execute("UPDATE deliveries SET supplierid=%d,date=%s,docnumber=%s "
                "WHERE deliveryid=%d",
                (supplier,mkdate(date),docnumber,delivery))
    con.commit()

def delivery_check(delivery):
    cur=con.cursor()
    cur.execute("UPDATE deliveries SET checked=true WHERE deliveryid=%d",
                (delivery,))
    con.commit()

def delivery_delete(delivery):
    cur=con.cursor()
    cur.execute("DELETE FROM stock WHERE deliveryid=%d",(delivery,))
    cur.execute("DELETE FROM deliveries WHERE deliveryid=%d",(delivery,))
    con.commit()

### Functions related to the stocktypes table

def stocktype_info(stn):
    cur=con.cursor()
    cur.execute("SELECT dept,manufacturer,name,shortname,abv,unit FROM stocktypes "
                "WHERE stocktype=%d",(stn,))
    return cur.fetchone()

def stocktype_completemanufacturer(m):
    cur=con.cursor()
    m=m+'%'
    cur.execute("SELECT DISTINCT manufacturer FROM stocktypes WHERE "
                "manufacturer ILIKE %s",(m,))
    return [x[0] for x in cur.fetchall()]

def stocktype_completename(m,n):
    cur=con.cursor()
    n=n+"%"
    cur.execute("SELECT DISTINCT name FROM stocktypes WHERE "
                "manufacturer=%s AND name ILIKE %s",(m,n))
    return [x[0] for x in cur.fetchall()]

def stocktype_fromnames(m,n):
    cur=con.cursor()
    cur.execute("SELECT stocktype FROM stocktypes WHERE "
                "manufacturer=%s AND name=%s",(m,n))
    return [x[0] for x in cur.fetchall()]

def stocktype_fromall(dept,manufacturer,name,shortname,abv,unit):
    cur=con.cursor()
    if abv is None:
        abvs=" is null"
    else:
        abvs="=%f"%abv
    return execone(cur,"SELECT stocktype FROM stocktypes WHERE "
                   "dept=%%d AND manufacturer=%%s AND name=%%s AND "
                   "shortname=%%s AND unit=%%s AND abv%s"%abvs,
                   (dept,manufacturer,name,shortname,unit))

def stocktype_new(dept,manufacturer,name,shortname,abv,unit):
    cur=con.cursor()
    if abv is None:
        abvs="null"
    else:
        abvs="%f"%abv
    sn=ticket(cur,"stocktypes_seq")
    cur.execute("INSERT INTO stocktypes (stocktype,dept,manufacturer,"
                "name,shortname,abv,unit) VALUES "
                "(%%d,%%d,%%s,%%s,%%s,%s,%%s)"%abvs,
                (sn,dept,manufacturer,name,shortname,unit))
    con.commit()
    return sn

def stocktype_update(sn,dept,manufacturer,name,shortname,abv,unit):
    cur=con.cursor()
    if abv is None:
        abvs="null"
    else:
        abvs="%f"%abv
    cur.execute("UPDATE stocktypes SET dept=%%d,manufacturer=%%s,name=%%s,"
                "shortname=%%s,abv=%s,unit=%%s WHERE stocktype=%%d"%abvs,
                (dept,manufacturer,name,shortname,unit,sn))
    con.commit()

### Functions related to the department table

def department_list():
    cur=con.cursor()
    cur.execute("SELECT dept,description FROM departments ORDER BY dept")
    return cur.fetchall()

### Functions related to the unittypes table

def unittype_list():
    cur=con.cursor()
    cur.execute("SELECT unit,name FROM unittypes")
    return cur.fetchall()

### Functions related to the stockunits table

def stockunits_list(unit):
    cur=con.cursor()
    cur.execute("SELECT stockunit,name,size FROM stockunits WHERE "
                "unit=%s",(unit,))
    return cur.fetchall()

def stockunits_info(su):
    cur=con.cursor()
    cur.execute("SELECT name,size FROM stockunits WHERE stockunit=%s",(su,))
    return cur.fetchone()

### Functions related to finishing stock

def stockfinish_list():
    cur=con.cursor()
    cur.execute("SELECT finishcode,description FROM stockfinish")
    return cur.fetchall()

### Functions related to the stock,stockout,stockonsale tables

def stock_info(stockid):
    "Return lots of information on a particular stock item."
    cur=con.cursor()
    cur.execute("SELECT st.stocktype,st.dept,st.manufacturer,"
                "st.name,st.shortname,st.abv,"
                "st.unit,ut.name AS unitname,su.stockunit,"
                "su.name AS sunitname,su.size,s.costprice,"
                "s.saleprice,s.onsale,s.finished,"
                "s.finishcode,s.bestbefore FROM stock s INNER JOIN "
                "stocktypes st ON s.stocktype=st.stocktype INNER "
                "JOIN stockunits su ON s.stockunit=su.stockunit "
                "INNER JOIN unittypes ut ON su.unit=ut.unit "
                "WHERE s.stockid=%d",(stockid,))
    r=cur.fetchone()
    if r is None: return None
    # Q: This is a real candidate for returning a dict! Does pgdb support it?
    # A: not explicitly, but we can do something like:
    cn=[x[0] for x in cur.description]
    d={}
    for i in cn:
        d[i]=r[0]
        r=r[1:]
    d['bestbefore']=mkstructtime(d['bestbefore'])
    d['used']=execone(cur,"SELECT sum(qty) FROM stockout WHERE stockid=%d",
                      (stockid,))
    if d['used'] is None: d['used']=0.0
    d['remaining']=d['size']-d['used']
    return d

def stock_extrainfo(stockid):
    "Return even more information on a particular stock item."
    cur=con.cursor()
    cur.execute(
        "SELECT sup.name AS suppliername,"
        "       d.date AS deliverydate,"
        "       d.docnumber AS deliverynote,"
        "       min(so.time) as firstsale, "
        "       max(so.time) as lastsale "
        "FROM stock s INNER JOIN deliveries d ON s.deliveryid=d.deliveryid "
        "INNER JOIN suppliers sup ON d.supplierid=sup.supplierid "
        "INNER JOIN stockout so ON so.stockid=s.stockid "
        "WHERE s.stockid=%d GROUP BY sup.name,d.date,d.docnumber",(stockid,))
    r=cur.fetchone()
    if r is None: return None
    cn=[x[0] for x in cur.description]
    d={}
    for i in cn:
        d[i]=r[0]
        r=r[1:]
    d['deliverydate']=mkstructtime(d['deliverydate'])
    d['firstsale']=mkstructtime(d['firstsale'])
    d['lastsale']=mkstructtime(d['lastsale'])
    cur.execute(
        "SELECT so.removecode,sr.reason,sum(qty) "
        "FROM stockout so INNER JOIN stockremove sr "
        "ON so.removecode=sr.removecode WHERE so.stockid=%d "
        "GROUP BY so.removecode,sr.reason",(stockid,))
    d['stockout']=[]
    for i in cur.fetchall():
        d['stockout'].append(i)
    return d

def stock_receive(delivery,stocktype,stockunit,costprice,saleprice,
                  bestbefore=None):
    "Receive stock, allocate a stock number and return it."
    cur=con.cursor()
    i=ticket(cur,"stock_seq")
    cur.execute("INSERT INTO stock (stockid,deliveryid,stocktype,stockunit,costprice,"
                "saleprice,bestbefore) VALUES "
                "(%d,%d,%d,%s,%f,%f,%s)",
                (i,delivery,stocktype,stockunit,costprice,saleprice,
                 mkdate(bestbefore)))
    con.commit()
    return i

def stock_update(sn,stocktype,stockunit,costprice,saleprice,bestbefore=None):
    cur=con.cursor()
    # XXX check that delivery is not marked "checked"
    cur.execute("UPDATE stock SET stocktype=%s,stockunit=%s,"
                "costprice=%f,saleprice=%f,bestbefore=%s WHERE "
                "stockid=%d",(stocktype,stockunit,costprice,saleprice,
                              mkdate(bestbefore),sn))
    con.commit()

def stock_delete(sn):
    cur=con.cursor()
    cur.execute("DELETE FROM stock WHERE stockid=%d",(sn,))
    con.commit()

def stock_sell(trans,stockitem,items,qty,source,transcode):
    "Insert a line into a transaction and create an associated stock record"
    cur=con.cursor()
    # Look up the price of the item and its department
    cur.execute("SELECT stock.saleprice,stocktypes.dept FROM stock,stocktypes "
                "WHERE stock.stocktype=stocktypes.stocktype AND "
                "stock.stockid=%d",(stockitem,))
    item=cur.fetchone()
    # Work out the item price; items is negative for voids
    p=item[0]*qty
    # Write out a stockout line
    son=ticket(cur,"stockout_seq")
    lid=ticket(cur,"translines_seq")
    cur.execute("INSERT INTO stockout (stockoutid,stockid,qty,removecode,"
                "translineid) VALUES (%d,%d,%f,'sold',%d)",
                (son,stockitem,qty*items,lid))
    # Write out a transaction line
    cur.execute("INSERT INTO translines (translineid,transid,items,amount,"
                "dept,source,stockref,transcode) VALUES "
                "(%d,%d,%d,%f,%d,%s,%d,%s)",
                (lid,trans,items,p,item[1],source,son,transcode))
    con.commit()
    return lid

def stock_sellmore(lid,items):
    "Update a transaction line and stock record with extra items"
    cur=con.cursor()
    # Fetch old number of items
    oi=execone(cur,"SELECT items FROM translines WHERE translineid=%d",(lid,))
    ni=oi+items
    # Update stockout line
    cur.execute("UPDATE stockout SET qty=(qty/%d)*%d WHERE translineid=%d",
                (oi,ni,lid))
    # Update transaction line
    cur.execute("UPDATE translines SET items=%d WHERE translineid=%d",(ni,lid))
    con.commit()
    return ni

def stock_fetchline(stocklineref):
    "Fetch stockout details given a line reference"
    cur=con.cursor()
    cur.execute("SELECT so.qty,so.removecode,"
                "so.stockid,st.manufacturer,st.name,st.shortname,"
                "st.abv,ut.name FROM stockout so "
                "INNER JOIN stock ON so.stockid=stock.stockid "
                "INNER JOIN stocktypes st ON st.stocktype=stock.stocktype "
                "INNER JOIN unittypes ut ON ut.unit=st.unit "
                "WHERE so.stockoutid=%d",(stocklineref,))
    return cur.fetchone()

def stock_availableforsale(dept):
    """Return a list of stock numbers available to be put on sale."""
    cur=con.cursor()
    cur.execute("SELECT s.stockid FROM stock s INNER JOIN deliveries d ON "
                "s.deliveryid=d.deliveryid INNER JOIN stocktypes st ON "
                "st.stocktype=s.stocktype WHERE finishcode is null AND "
                "d.checked=true AND s.stockid NOT IN (SELECT stockid "
                "FROM stockonsale) AND st.dept=%d ORDER BY s.stockid",
                (dept,))
    return [x[0] for x in cur.fetchall()]

def stock_putonsale(stock,line):
    "Connect a stock item to a particular line"
    cur=con.cursor()
    if stock_onsale(line): return False
    cur.execute("UPDATE stock SET onsale=now() WHERE stockid=%d",(stock,))
    cur.execute("INSERT INTO stockonsale (line,stockid) VALUES "
                "(%s,%d)",(line,stock))
    con.commit()
    return True

def stock_recordwaste(stock,reason,amount):
    "Record wastage of a stock item"
    cur=con.cursor()
    t=ticket(cur,'stockout_seq')
    cur.execute("INSERT INTO stockout (stockoutid,stockid,qty,removecode) "
                "VALUES (%d,%d,%f,%s)",(t,stock,amount,reason))
    con.commit()
    return t

def stock_finish(stock,reason):
    "Finish with a stock item; anything left is unaccounted waste"
    cur=con.cursor()
    # Disconnect it from its line, if it has one
    cur.execute("DELETE FROM stockonsale WHERE stockid=%d",(stock,))
    # Record the finish time and reason
    cur.execute("UPDATE stock SET finished=now(),finishcode=%s "
                "WHERE stockid=%d",(reason,stock))
    con.commit()

def stock_disconnect(stock):
    "Temporarily disconnect a stock item."
    cur=con.cursor()
    cur.execute("DELETE FROM stockonsale WHERE stockid=%d",(stock,))
    con.commit()

def stock_onsale(line):
    "Find out what's on sale on a particular [beer] line"
    cur=con.cursor()
    return execone(cur,"SELECT stockid FROM stockonsale WHERE line=%s",(line,))

### Functions relating to the sessions,sessiontotals tables

def session_current():
    "Return the current session number and the time it started."
    cur=con.cursor()
    cur.execute("SELECT sessionid,starttime FROM sessions WHERE "
                "endtime IS NULL");
    r=cur.fetchall()
    if len(r)==1:
        return (r[0][0],mkstructtime(r[0][1]))
    return None

def session_start():
    "Start a new session, if there is no session currently active."
    # Check that there's no session currently active
    if session_current(): return None
    # Create a new session
    cur=con.cursor()
    cur.execute("INSERT INTO sessions DEFAULT VALUES")
    con.commit()
    return session_current()

def session_end():
    """End the current session; only succeeds if there are no incomplete
    transactions.  On failure returns the list of incomplete transactions."""
    # Check that the session is active
    cs=session_current()
    if cs is None: return None
    # Check that there are no incomplete transactions
    i=trans_incompletes()
    if len(i)>0: return i
    # Mark the sesion ended
    cur=con.cursor()
    cur.execute("UPDATE sessions SET endtime=now() WHERE sessionid=%d",(cs[0],))
    con.commit()
    return None

def session_recordtotals(number,amounts):
    """Record actual takings for a session; amounts is a list of
    (paytype,amount) tuples."""
    # Check that the session has ended, but is otherwise incomplete
    cur=con.cursor()
    cur.execute("SELECT endtime FROM sessions WHERE sessionid=%d",(number,))
    s=cur.fetchall()
    if len(s)!=1: raise "Session does not exist"
    cur.execute("SELECT sum(amount) FROM sessiontotals WHERE sessionid=%d",
                (number,))
    s=cur.fetchall()
    if s[0][0]!=None:
        raise "Session has already had payments entered"
    # Record the amounts
    for i in amounts:
        cur.execute("INSERT INTO sessiontotals VALUES (%d,%s,%f)",
                    (number,i[0],i[1]))
    con.commit()
    return

def session_actualtotals(number):
    "Return a list of actual payments received for the session"
    cur=con.cursor()
    cur.execute("SELECT pt.description,st.amount FROM sessiontotals st "
                "INNER JOIN paytypes pt ON pt.paytype=st.paytype "
                "WHERE st.sessionid=%d",
                (number,))
    return cur.fetchall()

def session_depttotals(number):
    "Return a list of departments and the amounts taken in each department"
    cur=con.cursor()
    cur.execute("SELECT d.dept,d.description,sum(l.items*l.amount) FROM "
                "sessions s INNER JOIN transactions t ON "
                "t.sessionid=s.sessionid INNER JOIN translines l ON "
                "l.transid=t.transid INNER JOIN departments d ON "
                "l.dept=d.dept WHERE s.sessionid=%d GROUP BY "
                "d.dept,d.description ORDER BY d.dept",(number,))
    return cur.fetchall()

def session_transtotal(number):
    "Return the total of all payments in this session"
    cur=con.cursor()
    return execone(cur,"SELECT sum(amount) FROM payments WHERE transid in "
                   "(SELECT transid FROM transactions WHERE sessionid=%d)",
                   (number,))

def session_startend(number):
    "Return the start and end times of the session"
    cur=con.cursor()
    cur.execute("SELECT starttime,endtime FROM sessions WHERE "
                "sessionid=%d",(number,))
    (start,end)=cur.fetchone()
    return (mkstructtime(start),mkstructtime(end))

def session_list():
    """Return a list of sessions with summary details in descending order
    of session number."""
    cur=con.cursor()
    cur.execute("SELECT s.sessionid,s.starttime,s.endtime,sum(st.amount) "
                "FROM sessions s LEFT OUTER JOIN sessiontotals st ON "
                "s.sessionid=st.sessionid GROUP BY s.sessionid,"
                "s.starttime,s.endtime "
                "ORDER BY s.sessionid DESC")
    return [(x[0],mkstructtime(x[1]),mkstructtime(x[2]),x[3])
             for x in cur.fetchall()]

def db_version():
    cur=con.cursor()
    return execone(cur,"SELECT version()")
