# Till database handling routines

# Various parts of the UI call on these routines to work out what the
# hell is going on.  We try to ensure the database constraints are
# never broken here, but that's not really a substitute for
# implementing them in the database itself.

import pgdb,time,stock

con=None
def cursor():
    con.commit()
    return con.cursor()
def commit():
    con.commit()

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
    cur=cursor()
    t=ticket(cur,"transactions_seq")
    cur.execute("INSERT INTO transactions (transid,sessionid,notes) "
                "VALUES (%d,%d,%s)",(t,s[0],note))
    commit()
    return t

def trans_closed(trans):
    cur=cursor()
    return execone(
        cur,"SELECT closed FROM transactions WHERE transid=%d",(trans,))

# See also stock_sell()

def trans_addline(trans,dept,items,amountper,source,transcode):
    "Insert a line into a transaction that has no associated stock record"
    cur=cursor()
    lid=ticket(cur,"translines_seq")
    cur.execute("INSERT INTO translines (translineid,transid,items,amount,"
                "dept,source,transcode) VALUES (%d,%d,%d,%f,%d,%s,%s)",
                (lid,trans,items,amountper,dept,source,transcode))
    commit()
    return lid

def trans_additems(lid,items):
    "Update an existing line with additional items"
    cur=cursor()
    # XXX check the transaction is not closed
    cur.execute("UPDATE translines SET items=items+%d "
                "WHERE translines.translineid=%d",(items,lid))
    commit()

def trans_getline(lid):
    "Retrieve information about a transaction line"
    cur=cursor()
    cur.execute("SELECT translines.transid,translines.items,"
                "translines.amount,translines.dept,departments.description,"
                "translines.stockref,translines.transcode FROM translines "
                "INNER JOIN departments ON translines.dept=departments.dept "
                "WHERE translines.translineid=%d",(lid,))
    return cur.fetchone()

def trans_getlines(trans):
    "Retrieve lines and payments for a transaction"
    cur=cursor()
    cur.execute("SELECT translineid FROM translines WHERE transid=%d "
                "ORDER BY translineid",(trans,))
    lines=[x[0] for x in cur.fetchall()]
    cur.execute("SELECT p.amount,p.paytype,pt.description,p.ref "
                "FROM payments p "
                "LEFT JOIN paytypes pt ON p.paytype=pt.paytype "
                "WHERE transid=%d ORDER BY time ",(trans,))
    payments=cur.fetchall()
    return (lines,payments)

def trans_balance(trans):
    "Return (linestotal,paymentstotal) on a transaction"
    cur=cursor()
    cur.execute("SELECT (SELECT sum(amount*items) FROM translines "
                "WHERE translines.transid=%d),(SELECT sum(amount) "
                "FROM payments WHERE payments.transid=%d)",(trans,trans));
    r=cur.fetchone()
    if not r[0]: r[0]=0.0
    if not r[1]: r[1]=0.0
    return (r[0],r[1])

def trans_date(trans):
    "Return the accounting date of the transaction"
    cur=cursor()
    d=execone(cur,"SELECT s.sessiondate FROM transactions t "
              "LEFT JOIN sessions s ON t.sessionid=s.sessionid "
              "WHERE t.transid=%d",(trans,))
    return mkstructtime(d)

def trans_addpayment(trans,type,amount,ref):
    """Add a payment to a transaction, and return the remaining balance.
    If the remaining balance is zero, mark the transaction closed."""
    cur=cursor()
    cur.execute("INSERT INTO payments (transid,amount,paytype,ref) VALUES "
                "(%d,%f,%s,%s)",(trans,amount,type,ref))
    (lines,payments)=trans_balance(trans)
    remain=lines-payments
    if remain==0.0:
        cur.execute("UPDATE transactions SET closed=true WHERE transid=%d",
                    (trans,))
    commit()
    return remain

def trans_cancel(trans):
    """Delete a transaction and everything that depends on it."""
    cur=cursor()
    closed=execone(cur,"SELECT closed FROM transactions WHERE transid=%d",
                   (trans,))
    if closed: return "Transaction closed"
    cur.execute("DELETE FROM stockout WHERE stockout.translineid IN "
                "(SELECT translineid FROM translines WHERE transid=%d)",(trans,))
    cur.execute("DELETE FROM payments WHERE transid=%d",(trans,))
    cur.execute("DELETE FROM translines WHERE transid=%d",(trans,))
    cur.execute("DELETE FROM transactions WHERE transid=%d",(trans,))
    commit()

def trans_deleteline(transline):
    cur=cursor()
    cur.execute("DELETE FROM stockout WHERE translineid=%d",(transline,))
    cur.execute("DELETE FROM translines WHERE translineid=%d",(transline,))
    commit()

def trans_defer(trans):
    """Defers a transaction to a later session, by setting its sessionid to
    null.

    """
    cur=cursor()
    cur.execute("UPDATE transactions SET sessionid=null WHERE transid=%d",
                (trans,))
    commit()

def trans_merge(t1,t2):
    """Merge t1 into t2, and delete t1.

    """
    cur=cursor()
    cur.execute("UPDATE translines SET transid=%d WHERE transid=%d",
                (t2,t1))
    cur.execute("DELETE FROM transactions WHERE transid=%d",(t1,))
    commit()

def trans_restore():
    """Restores all deferred transactions.

    """
    s=session_current()
    if s is None: return 0
    sessionid=s[0]
    cur=cursor()
    cur.execute("UPDATE transactions SET sessionid=%d WHERE sessionid IS NULL",
                (sessionid,))
    commit()

def trans_makefree(transid,removecode):
    """Converts all stock sold in this transaction to 'removecode', and
    deletes the transaction.  Usually used when converting an open transaction
    to 'free drinks'.

    """
    cur=cursor()
    cur.execute("UPDATE stockout SET removecode=%s,translineid=NULL "
                "WHERE translineid IN (SELECT translineid FROM translines "
                "WHERE transid=%d)",(removecode,transid))
    cur.execute("DELETE FROM translines WHERE transid=%d",(transid,))
    cur.execute("DELETE FROM transactions WHERE transid=%d",(transid,))
    commit()

def trans_incompletes():
    "Returns the list of incomplete transactions"
    cur=cursor()
    cur.execute("SELECT transid FROM transactions WHERE closed=false "
                "AND sessionid IS NOT NULL")
    return [x[0] for x in cur.fetchall()]

### Suppliers of stock

def supplier_list():
    "Return the list of suppliers"
    cur=cursor()
    cur.execute("SELECT supplierid,name,tel,email FROM suppliers ORDER BY supplierid")
    return cur.fetchall()

def supplier_new(name,tel,email):
    "Create a new supplier and return the id"
    cur=cursor()
    sid=ticket(cur,"suppliers_seq")
    cur.execute("INSERT INTO suppliers (supplierid,name,tel,email) "
                "VALUES (%d,%s,%s,%s)",(sid,name,tel,email))
    commit()
    return sid

def supplier_fetch(sid):
    "Return supplier details"
    cur=cursor()
    cur.execute("SELECT name,tel,email FROM suppliers WHERE supplierid=%d",(sid,))
    return cur.fetchone()

def supplier_update(sid,name,tel,email):
    "Update supplier details"
    cur=cursor()
    cur.execute("UPDATE suppliers SET name=%s,tel=%s,email=%s WHERE supplierid=%d",
                (name,tel,email,sid))
    commit()

### Delivery-related functions

def delivery_get(unchecked_only=False,checked_only=False,number=None):
    cur=cursor()
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
    cur=cursor()
    dn=ticket(cur,"deliveries_seq")
    cur.execute("INSERT INTO deliveries (deliveryid,supplierid) VALUES "
                "(%d,%d)",(dn,supplier))
    commit()
    return dn

def delivery_items(delivery):
    cur=cursor()
    cur.execute("SELECT stockid FROM stock WHERE deliveryid=%d ORDER BY stockid",
                (delivery,))
    return [x[0] for x in cur.fetchall()]

def delivery_update(delivery,supplier,date,docnumber):
    cur=cursor()
    cur.execute("UPDATE deliveries SET supplierid=%d,date=%s,docnumber=%s "
                "WHERE deliveryid=%d",
                (supplier,mkdate(date),docnumber,delivery))
    commit()

def delivery_check(delivery):
    cur=cursor()
    cur.execute("UPDATE deliveries SET checked=true WHERE deliveryid=%d",
                (delivery,))
    commit()

def delivery_delete(delivery):
    cur=cursor()
    cur.execute("DELETE FROM stock WHERE deliveryid=%d",(delivery,))
    cur.execute("DELETE FROM deliveries WHERE deliveryid=%d",(delivery,))
    commit()

### Functions related to the stocktypes table

def stocktype_info(stn):
    cur=cursor()
    cur.execute("SELECT dept,manufacturer,name,shortname,abv,unit FROM stocktypes "
                "WHERE stocktype=%d",(stn,))
    return cur.fetchone()

def stocktype_completemanufacturer(m):
    cur=cursor()
    m=m+'%'
    cur.execute("SELECT DISTINCT manufacturer FROM stocktypes WHERE "
                "manufacturer ILIKE %s",(m,))
    return [x[0] for x in cur.fetchall()]

def stocktype_completename(m,n):
    cur=cursor()
    n=n+"%"
    cur.execute("SELECT DISTINCT name FROM stocktypes WHERE "
                "manufacturer=%s AND name ILIKE %s",(m,n))
    return [x[0] for x in cur.fetchall()]

def stocktype_fromnames(m,n):
    cur=cursor()
    cur.execute("SELECT stocktype FROM stocktypes WHERE "
                "manufacturer=%s AND name=%s",(m,n))
    return [x[0] for x in cur.fetchall()]

def stocktype_fromall(dept,manufacturer,name,shortname,abv,unit):
    cur=cursor()
    if abv is None:
        abvs=" is null"
    else:
        abvs="=%f"%abv
    return execone(cur,"SELECT stocktype FROM stocktypes WHERE "
                   "dept=%%d AND manufacturer=%%s AND name=%%s AND "
                   "shortname=%%s AND unit=%%s AND abv%s"%abvs,
                   (dept,manufacturer,name,shortname,unit))

def stocktype_new(dept,manufacturer,name,shortname,abv,unit):
    cur=cursor()
    if abv is None:
        abvs="null"
    else:
        abvs="%f"%abv
    sn=ticket(cur,"stocktypes_seq")
    cur.execute("INSERT INTO stocktypes (stocktype,dept,manufacturer,"
                "name,shortname,abv,unit) VALUES "
                "(%%d,%%d,%%s,%%s,%%s,%s,%%s)"%abvs,
                (sn,dept,manufacturer,name,shortname,unit))
    commit()
    return sn

def stocktype_update(sn,dept,manufacturer,name,shortname,abv,unit):
    cur=cursor()
    if abv is None:
        abvs="null"
    else:
        abvs="%f"%abv
    cur.execute("UPDATE stocktypes SET dept=%%d,manufacturer=%%s,name=%%s,"
                "shortname=%%s,abv=%s,unit=%%s WHERE stocktype=%%d"%abvs,
                (dept,manufacturer,name,shortname,unit,sn))
    commit()

### Functions related to the department table

def department_list():
    cur=cursor()
    cur.execute("SELECT dept,description FROM departments ORDER BY dept")
    return cur.fetchall()

### Functions related to the unittypes table

def unittype_list():
    cur=cursor()
    cur.execute("SELECT unit,name FROM unittypes")
    return cur.fetchall()

### Functions related to the stockunits table

def stockunits_list(unit):
    cur=cursor()
    cur.execute("SELECT stockunit,name,size FROM stockunits WHERE "
                "unit=%s",(unit,))
    return cur.fetchall()

def stockunits_info(su):
    cur=cursor()
    cur.execute("SELECT name,size FROM stockunits WHERE stockunit=%s",(su,))
    return cur.fetchone()

### Functions related to finishing stock

def stockfinish_list():
    cur=cursor()
    cur.execute("SELECT finishcode,description FROM stockfinish")
    return cur.fetchall()

### Functions related to the stock,stockout,stockonsale tables

def stock_info(stockid_list):
    """Return lots of information on stock items in the list."""
    if len(stockid_list)==0: return []
    cur=cursor()
    cur.execute("SELECT * FROM stockinfo WHERE stockid IN (%s)"%(
        ','.join(["%d"%x for x in stockid_list])))
    r=cur.fetchall()
    # Q: This is a real candidate for returning a dict! Does pgdb support it?
    # A: not explicitly, but we can do something like:
    cn=[x[0] for x in cur.description]
    def mkdict(r):
        d={}
        for i in cn:
            d[i]=r[0]
            r=r[1:]
        d['abvstr']=stock.abvstr(d['abv'])
        d['bestbefore']=mkstructtime(d['bestbefore'])
        d['deliverydate']=mkstructtime(d['deliverydate'])
        d['onsale']=mkstructtime(d['onsale'])
        d['finished']=mkstructtime(d['finished'])
        if d['used'] is None: d['used']=0.0
        d['remaining']=d['size']-d['used']
        return d
    # At this point we have a list of results, but that list is not
    # necessarily in the order of the input list.  We must sort it into
    # the appropriate order.
    sid={}
    for i in r:
        sid[i[0]]=mkdict(i)
    return [sid[x] for x in stockid_list]

def stock_extrainfo(stockid):
    "Return even more information on a particular stock item."
    cur=cursor()
    cur.execute(
        "SELECT min(so.time) as firstsale, "
        "       max(so.time) as lastsale "
        "FROM stock s LEFT JOIN stockout so ON so.stockid=s.stockid "
        "WHERE s.stockid=%d AND so.removecode='sold' ",(stockid,))
    r=cur.fetchone()
    if r is None: r=[None,None]
    d={}
    d['firstsale']=mkstructtime(r[0])
    d['lastsale']=mkstructtime(r[1])
    cur.execute(
        "SELECT so.removecode,sr.reason,sum(qty) "
        "FROM stockout so INNER JOIN stockremove sr "
        "ON so.removecode=sr.removecode WHERE so.stockid=%d "
        "GROUP BY so.removecode,sr.reason",(stockid,))
    d['stockout']=[]
    for i in cur.fetchall():
        d['stockout'].append(i)
    return d

def stock_checkpullthru(stockid,maxtime):
    """Did this stock item require pulling through?"""
    cur=cursor()
    r=execone(cur,"SELECT now()-max(stockout.time)>%s FROM stockout "
              "WHERE stockid=%d AND removecode IN ('sold','pullthru')",
              (maxtime,stockid))
    if r is None: r=False
    return r

def stock_receive(delivery,stocktype,stockunit,costprice,saleprice,
                  bestbefore=None):
    "Receive stock, allocate a stock number and return it."
    cur=cursor()
    i=ticket(cur,"stock_seq")
    cur.execute("INSERT INTO stock (stockid,deliveryid,stocktype,stockunit,costprice,"
                "saleprice,bestbefore) VALUES "
                "(%d,%d,%d,%s,%f,%f,%s)",
                (i,delivery,stocktype,stockunit,costprice,saleprice,
                 mkdate(bestbefore)))
    commit()
    return i

def stock_duplicate(sn):
    """Duplicate an existing stock item, returning the new stock number.
    NB we deliberately do not duplicate the best before date, so the user
    must check each item.
    """
    cur=cursor()
    i=ticket(cur,"stock_seq")
    cur.execute("INSERT INTO stock (stockid,deliveryid,stocktype,stockunit,"
                "costprice,saleprice) "
                "SELECT %d AS stockid,deliveryid,stocktype,stockunit,"
                "costprice,saleprice FROM stock WHERE stockid=%d",
                (i,sn))
    commit()
    return i

def stock_update(sn,stocktype,stockunit,costprice,saleprice,bestbefore=None):
    cur=cursor()
    # XXX check that delivery is not marked "checked"
    cur.execute("UPDATE stock SET stocktype=%s,stockunit=%s,"
                "costprice=%f,saleprice=%f,bestbefore=%s WHERE "
                "stockid=%d",(stocktype,stockunit,costprice,saleprice,
                              mkdate(bestbefore),sn))
    commit()

def stock_delete(sn):
    cur=cursor()
    cur.execute("DELETE FROM stock WHERE stockid=%d",(sn,))
    commit()

def stock_sell(trans,dept,stockitem,items,qty,price,source,transcode):
    """Sell some stock.  Inserts a line into a transaction, and creates
    an associated stock record.

    'dept' is the department the sale will be recorded in.

    'qty' is the amount being sold as a unit, eg. 0.5 for a half pint,
    2.0 for a double, 4.0 for a 4-pint jug.

    'items' is the number of things of size 'qty' that are being sold.
    It will be negative for void transactions.

    'price' is the price of 'qty' of the stock, with discounts, etc. taken
    into account.

    'source' is a string identifying where the transaction is taking place.

    'transcode' is a letter identifying the type of transaction;
    currently 'S' for a sale, or 'V' for a void.

    """
    cur=cursor()
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
                (lid,trans,items,price,dept,source,son,transcode))
    commit()
    return lid

def stock_sellmore(lid,items):
    "Update a transaction line and stock record with extra items"
    cur=cursor()
    # Fetch old number of items
    oi=execone(cur,"SELECT items FROM translines WHERE translineid=%d",(lid,))
    ni=oi+items
    # Update stockout line
    cur.execute("UPDATE stockout SET qty=(qty/%d)*%d WHERE translineid=%d",
                (oi,ni,lid))
    # Update transaction line
    cur.execute("UPDATE translines SET items=%d WHERE translineid=%d",(ni,lid))
    commit()
    return ni

def stock_fetchline(stocklineref):
    "Fetch stockout details given a line reference"
    cur=cursor()
    cur.execute("SELECT so.qty,so.removecode,"
                "so.stockid,st.manufacturer,st.name,st.shortname,"
                "st.abv,ut.name FROM stockout so "
                "INNER JOIN stock ON so.stockid=stock.stockid "
                "INNER JOIN stocktypes st ON st.stocktype=stock.stocktype "
                "INNER JOIN unittypes ut ON ut.unit=st.unit "
                "WHERE so.stockoutid=%d",(stocklineref,))
    return cur.fetchone()

def stock_search(dept=None,exclude_stock_on_sale=True,
                 finished_stock_only=False):
    """Return a list of stock numbers that fit the criteria."""
    cur=cursor()
    if dept is None:
        deptq=""
    else:
        deptq="AND st.dept=%d"%dept
    if exclude_stock_on_sale:
        sosq="AND s.stockid NOT IN (SELECT stockid FROM stockonsale)"
    else:
        sosq=""
    if finished_stock_only:
        finq="not null"
    else:
        finq="null"
    cur.execute("SELECT s.stockid FROM stock s INNER JOIN deliveries d ON "
                "s.deliveryid=d.deliveryid INNER JOIN stocktypes st ON "
                "st.stocktype=s.stocktype WHERE finishcode is %s AND "
                "d.checked=true %s %s ORDER BY s.stockid"%(finq,sosq,deptq))
    return [x[0] for x in cur.fetchall()]

def stock_putonsale(stockid,stocklineid):
    "Connect a stock item to a particular line"
    cur=cursor()
    cur.execute("UPDATE stock SET onsale=now() WHERE stockid=%d",(stockid,))
    cur.execute("INSERT INTO stockonsale (stocklineid,stockid) VALUES "
                "(%d,%d)",(stocklineid,stockid))
    commit()
    return True

def stock_autoallocate():
    cur=cursor()
    cur.execute(
        "INSERT INTO stockonsale (stocklineid,stockid,displayqty) "
        "SELECT sl.stocklineid,si.stockid,si.used AS displayqty "
	"FROM stocklines sl "
	"CROSS JOIN stockinfo si "
	"WHERE sl.capacity IS NOT NULL "
	"AND si.deliverychecked "
	"AND si.stocktype IN "
	"(SELECT isi.stocktype FROM stockonsale sos "
	"LEFT JOIN stockinfo isi ON isi.stockid=sos.stockid "
	"WHERE sos.stocklineid=sl.stocklineid) "
	"AND si.stockid NOT IN "
	"(SELECT sos.stockid FROM stockonsale sos)")
    commit()

def stock_recordwaste(stock,reason,amount,update_displayqty):
    """Record wastage of a stock item.  If update_displayqty is set then
    the displayqty field in the stockonsale table will be increased by the
    same amount, so that the quantity on display remains unchanged.  (If
    there is no entry for the stockid in stockonsale then nothing happens.)

    """
    cur=cursor()
    t=ticket(cur,'stockout_seq')
    cur.execute("INSERT INTO stockout (stockoutid,stockid,qty,removecode) "
                "VALUES (%d,%d,%f,%s)",(t,stock,amount,reason))
    if update_displayqty:
        cur.execute("UPDATE stockonsale SET displayqty=displayqty+%d "
                    "WHERE stockid=%d",(int(amount),stock))
    commit()
    return t

def stock_finish(stock,reason):
    "Finish with a stock item; anything left is unaccounted waste"
    cur=cursor()
    # Disconnect it from its line, if it has one
    cur.execute("DELETE FROM stockonsale WHERE stockid=%d",(stock,))
    # Record the finish time and reason
    cur.execute("UPDATE stock SET finished=now(),finishcode=%s "
                "WHERE stockid=%d",(reason,stock))
    commit()

def stock_disconnect(stock):
    "Temporarily disconnect a stock item."
    cur=cursor()
    cur.execute("DELETE FROM stockonsale WHERE stockid=%d",(stock,))
    commit()

def stock_onsale(line):
    """Find out what's on sale on a particular [beer] line.  This function
    returns a list of all the stock items allocated to the line, in order
    of best before date and then stock number, earliest dates/lowest numbers
    first.

    """
    cur=cursor()
    cur.execute(
        "SELECT sos.stockid,sos.displayqty "
        "FROM stockonsale sos "
        "LEFT JOIN stock s ON s.stockid=sos.stockid "
        "WHERE sos.stocklineid=%d ORDER BY s.bestbefore,sos.stockid",(line,))
    return cur.fetchall()

### Functions related to stock lines

def stockline_create(name,location,dept,capacity,pullthru):
    cur=cursor()
    id=ticket(cur,"stocklines_seq")
    try:
        cur.execute("INSERT INTO stocklines (stocklineid,name,location,"
                    "dept) VALUES (%d,%s,%s,%d)",
                    (id,name,location,dept))
    except:
        return False
    if capacity is not None:
        cur.execute("UPDATE stocklines SET capacity=%d WHERE stocklineid=%d",
                    (capacity,id))
    if pullthru is not None:
        cur.execute("UPDATE stocklines SET pullthru=%f WHERE stocklineid=%d",
                    (pullthru,id))
    commit()
    return True

def stockline_update(stocklineid,name,location,capacity,pullthru):
    cur=cursor()
    if capacity is None: capstr="NULL"
    else: capstr="%d"%capacity
    if pullthru is None: pullstr="NULL"
    else: pullstr="%f"%pullthru
    cur.execute("UPDATE stocklines SET name=%%s,location=%%s,capacity=%s,"
                "pullthru=%s WHERE stocklineid=%%d"%(capstr,pullstr),
                (name,location,stocklineid))
    commit()
    return True

def stockline_info(stocklineid):
    cur=cursor()
    cur.execute("SELECT name,location,capacity,dept,pullthru "
                "FROM stocklines WHERE stocklineid=%d",(stocklineid,))
    return cur.fetchone()

def stockline_restock(stocklineid,changes):
    cur=cursor()
    for sd,move,newdisplayqty,stockqty_after_move in changes:
        cur.execute("UPDATE stockonsale SET displayqty=%d WHERE "
                    "stocklineid=%d AND stockid=%d",(
            newdisplayqty,stocklineid,sd['stockid']))
    commit()

def stockline_list(caponly=False):
    cur=cursor()
    if caponly:
        wc=" WHERE capacity IS NOT NULL"
    else:
        wc=""
    cur.execute("SELECT stocklineid,name,location,capacity,dept,pullthru "
                "FROM stocklines%s ORDER BY location,name"%wc)
    return cur.fetchall()

### Functions relating to till keyboards

def keyboard_checklines(layout,keycode):
    """keycode is a string.  Returns a list of (menukey,stocklineid,qty,
    linename,lineloc,capacity,dept,pullthru) tuples (possibly empty).  The
    list may be in any order; it's up to the caller to sort it (eg. by
    menukey numeric keycode)."""
    cur=cursor()
    cur.execute("SELECT sl.name,k.qty,sl.dept,sl.pullthru,"
                "k.menukey,k.stocklineid,sl.location,sl.capacity "
                "FROM keyboard k "
                "LEFT JOIN stocklines sl ON sl.stocklineid=k.stocklineid "
                "WHERE k.layout=%d AND k.keycode=%s",(layout,keycode))
    return cur.fetchall()

### Functions relating to the sessions,sessiontotals tables

def session_current():
    "Return the current session number and the time it started."
    cur=cursor()
    cur.execute("SELECT sessionid,starttime,sessiondate FROM sessions WHERE "
                "endtime IS NULL");
    r=cur.fetchall()
    if len(r)==1:
        return (r[0][0],mkstructtime(r[0][1]),mkstructtime(r[0][2]))
    return None

def session_start(date):
    "Start a new session, if there is no session currently active."
    # Check that there's no session currently active
    if session_current(): return None
    # Create a new session
    cur=cursor()
    cur.execute("INSERT INTO sessions (sessiondate) VALUES ('%s')"%
                mkdate(date))
    commit()
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
    cur=cursor()
    cur.execute("UPDATE sessions SET endtime=now() WHERE sessionid=%d",(cs[0],))
    commit()
    return None

def session_recordtotals(number,amounts):
    """Record actual takings for a session; amounts is a list of
    (paytype,amount) tuples."""
    # Check that the session has ended, but is otherwise incomplete
    cur=cursor()
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
    commit()
    return

def session_actualtotals(number):
    "Return a list of actual payments received for the session"
    cur=cursor()
    cur.execute("SELECT st.paytype,pt.description,st.amount "
                "FROM sessiontotals st "
                "INNER JOIN paytypes pt ON pt.paytype=st.paytype "
                "WHERE st.sessionid=%d",
                (number,))
    f=cur.fetchall()
    d={}
    for i in f:
        d[i[0]]=(i[1],i[2])
    return d

def session_paytotals(number):
    """Return the total of all payments in this session, as a dict of
    amounts with the payment type (CASH, CARD, etc.) as the key.
    
    """
    cur=cursor()
    cur.execute("SELECT p.paytype,pt.description,sum(p.amount) "
                "FROM payments p LEFT JOIN paytypes pt ON "
                "p.paytype=pt.paytype WHERE transid in "
                "(SELECT transid FROM transactions WHERE sessionid=%d) "
                "GROUP BY p.paytype,pt.description",(number,))
    f=cur.fetchall()
    d={}
    for i in f:
        d[i[0]]=(i[1],i[2])
    return d

def session_depttotals(number):
    "Return a list of departments and the amounts taken in each department"
    cur=cursor()
    cur.execute("SELECT d.dept,d.description,sum(l.items*l.amount) FROM "
                "sessions s INNER JOIN transactions t ON "
                "t.sessionid=s.sessionid INNER JOIN translines l ON "
                "l.transid=t.transid INNER JOIN departments d ON "
                "l.dept=d.dept WHERE s.sessionid=%d GROUP BY "
                "d.dept,d.description ORDER BY d.dept",(number,))
    return cur.fetchall()

def session_dates(number):
    "Return the start and end times of the session"
    cur=cursor()
    cur.execute("SELECT starttime,endtime,sessiondate FROM sessions WHERE "
                "sessionid=%d",(number,))
    (start,end,date)=cur.fetchone()
    return (mkstructtime(start),mkstructtime(end),mkstructtime(date))

def session_list():
    """Return a list of sessions with summary details in descending order
    of session number."""
    cur=cursor()
    cur.execute("SELECT s.sessionid,s.starttime,s.endtime,s.sessiondate,"
                "sum(st.amount) "
                "FROM sessions s LEFT OUTER JOIN sessiontotals st ON "
                "s.sessionid=st.sessionid GROUP BY s.sessionid,"
                "s.starttime,s.endtime,s.sessiondate "
                "ORDER BY s.sessionid DESC")
    return [(x[0],mkstructtime(x[1]),mkstructtime(x[2]),mkstructtime(x[3]),
             x[4])
            for x in cur.fetchall()]

def session_translist(session,onlyopen=False):
    """Returns the list of transactions in a session; transaction number,
    closed status, total charge.

    """
    cur=cursor()
    oos=""
    if onlyopen:
        oos="AND t.closed=FALSE "
    cur.execute("SELECT t.transid,t.closed,sum(tl.items*tl.amount) "
                "FROM transactions t LEFT JOIN translines tl "
                "ON t.transid=tl.transid "
                "WHERE t.sessionid=%d %s"
                "GROUP BY t.transid,t.closed "
                "ORDER BY t.closed,t.transid DESC"%(session,oos))
    return cur.fetchall()

### List of payment types

def paytypes_list():
    """Return a dictionary of payment types and their descriptions."""
    cur=cursor()
    cur.execute("SELECT paytype,description FROM paytypes")
    f=cur.fetchall()
    d={}
    for i in f:
        d[i[0]]=i[1]
    return d

def db_version():
    cur=cursor()
    return execone(cur,"SELECT version()")

def init(database):
    global con
    con=pgdb.connect(database)
