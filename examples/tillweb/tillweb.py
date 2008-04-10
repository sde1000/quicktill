"""Resources available to view on the till web server:

/ (overall) - a summary of recent events, index page
/week/ - totals for all weeks
/session/<number> - session totals
/session/<number>/dept<number> - list of translines in a department
/transaction/<number> - details of a transaction
/deliveries/ - list of all deliveries
/deliveries/<number> - full details of a delivery
/stock/ - a list of all stock
/stock/<number> - full details of a particular stock item
/stocklines/ - a list of all stock lines with display quantities
/sheet.csv - till totals as a CSV file

General rule - if a summary is displayed on a page, you can click on
it for a breakdown.

"""

from twisted.web.resource import Resource
from twisted.web import static,server
from twisted.internet import defer,reactor
from pgasync import ConnectionPool
import page
from page import page as pagetmpl
from Cheetah import Template
import csv
import datetime
import re
import tillfilters as Filters

def formatBlock(block):
    """Format the given block of text, trimming leading/trailing empty
    lines and any leading whitespace that is common to all lines.  The
    purpose is to let us list a code block as a multiline,
    triple-quoted Python string, taking care of indentation concerns.

    """
    lines = block.split('\n')
    while lines and not lines[0]:  del lines[0]
    while lines and not lines[-1]: del lines[-1]
    ws = re.match(r'\s*',lines[0]).group(0)
    if ws:
        lines = [x.replace(ws,'',1) for x in lines]
    while lines and not lines[0]:  del lines[0]
    while lines and not lines[-1]: del lines[-1]
    return '\n'.join(lines)+'\n'


mindate=datetime.date(datetime.MINYEAR,1,1)
maxdate=datetime.date(datetime.MAXYEAR,12,31)

def mkdate(x):
    y,m,d=x.split('-')
    return datetime.date(int(y),int(m),int(d))

class Index(Resource):
    """This is the root level of the till web application.  It doesn't
    render anything itself; it is merely the holder of the database
    connection pool and the index of the various other rendering
    classes.

    """
    def __init__(self,title,dbname,user,password="",host=None):
        Resource.__init__(self)
        self.title=title
        pool=ConnectionPool("pgasync",dbname=dbname,user=user,password=password,host=host)
        self.putChild("",Summary(title,pool))
        self.putChild("style.css",static.File("style.css"))
        self.putChild("sheet.csv",SummarySheet(title,pool))
        self.putChild("doc",static.File("/usr/share/doc"))
        self.putChild("sessions",SessionIndex(title,pool))
        self.putChild("stock",StockIndex(title,pool))
        self.putChild("stock.csv",StockIndex(title,pool,'csv'))
        self.putChild("deliveries",DeliveryIndex(title,pool))
        self.putChild("translines",TransLines(title,pool))
        self.putChild("stocklines",StockLines(title,pool))
        self.putChild("stats",Statistics(title,pool))
    def getChildWithDefault(self,name,request):
        request.rememberRootURL()
        s=request.getSession()
        if 'count' not in s.sessionNamespaces:
            s.sessionNamespaces['count']=0
        s.sessionNamespaces['count']=s.sessionNamespaces['count']+1
        return Resource.getChildWithDefault(self,name,request)

class DBPage(Resource):
    def __init__(self,title,pool,format='html'):
        Resource.__init__(self)
        self.title=title
        self.pool=pool
        self.defaultFormat=format
    def template(self,searchList):
        return Template.Template(source="#extends page",searchList=searchList,filtersLib=Filters)
    def csv(self,csvw,rl):
        pass
    def queries(self,request):
        """Returns a list of database queries for the page, as
        (resultname,(runQuery args tuple)) tuples
        """
        return []
    def render_GET(self,request):
        ql=self.queries(request)
        dl=[self.pool.runQuery(*x[1]) for x in ql]
        d=defer.DeferredList(dl)
        format=request.args.get('format',self.defaultFormat)
        if isinstance(format,list): format=format[0]
        if format=='csv':
            d.addCallback(self.finish_render_csv,request,ql)
            request.setHeader('Content-type','text/comma-separated-values')
        elif format=='html':
            d.addCallback(self.finish_render_html,request,ql)
            request.setHeader('Content-type','text/html; charset=UTF8')
        else:
            return ("Unknown format '%s'"%format)
        return server.NOT_DONE_YET
    def finish_render_csv(self,dl,request,ql):
        rl=[(b[0],a[1]) for a,b in zip(dl,ql)]
        w=csv.writer(request)
        self.csv(w,dict(rl))
        request.finish()
    def postprocess_queries(self,rl):
        # This method gives a chance to postprocess the results returned
        # from the database before rendering.
        return rl
    def finish_render_html(self,dl,request,ql):
        # dl is a list of (success,result) tuples corresponding to the
        # queries in ql.  For now I'm going to be lazy and assume they
        # were all successful (because pgasync doesn't actually report
        # errors at the moment) and just include the results in a
        # dictionary.
        rl=[(b[0],a[1]) for a,b in zip(dl,ql)]
        rl=self.postprocess_queries(rl)
        searchList=[dict(rl),{
            'title':self.title,
            'root':request.getRootURL(),
            'request':request,
            'session':request.getSession().sessionNamespaces['count'],
            'resource':self}]
        t=self.template(searchList)
        try:
            request.write(t.respond())
        except:
            request.write("There was an error.")
            request.finish()
            raise
        request.finish()

class Summary(DBPage):
    def queries(self,request):
        # Using inner joins from sessions<->transactions<->translines should
        # not affect the result and makes for a cheaper query plan
        return [('currentsession',(
            "SELECT b.abbrev,s.sessionid,s.sessiondate,"
            "sum(tl.items*tl.amount) "
            "FROM sessions s "
            "INNER JOIN transactions t ON t.sessionid=s.sessionid "
            "INNER JOIN translines tl ON t.transid=tl.transid "
            "LEFT JOIN departments d ON tl.dept=d.dept "
            "LEFT JOIN vat ON vat.band=d.vatband "
            "LEFT JOIN businesses b ON b.business=vat.business "
            "WHERE s.endtime IS NULL "
            "GROUP BY b.abbrev,s.sessionid,s.sessiondate "
            "ORDER BY b.abbrev",)),
                ('businesses',(
            "SELECT abbrev FROM businesses ORDER BY abbrev",)),
                ('weeks',(
            "SELECT abbrev,min(sessiondate),max(sessiondate),"
            "sum(sum) AS weektotal FROM businesstotals "
            "WHERE sessiondate>((now()::date)-21) "
            "GROUP BY (sessiondate-'2002-08-05'::date)/7,abbrev "
            "ORDER BY abbrev,max(sessiondate) DESC",)),
                ('onthebar',(
            "SELECT sl.name,si.stockid,si.shortname,si.abv,"
            "coalesce(si.used,0.0) AS used,"
            "si.size-coalesce(si.used,0.0) AS remaining,"
            "si.unitname,si.onsale "
            "FROM stocklines sl "
            "LEFT JOIN stockonsale sos ON sos.stocklineid=sl.stocklineid "
            "INNER JOIN stockinfo si ON si.stockid=sos.stockid "
            "WHERE sl.dept IN (1,2,3) "
            "ORDER BY sl.dept,sl.name",)),
                ('stillage',(
            "SELECT sa.text,sa.stockid,sa.time,st.shortname,sl.name "
            "FROM stock_annotations sa "
            "LEFT JOIN stock s ON s.stockid=sa.stockid "
            "LEFT JOIN stocktypes st ON s.stocktype=st.stocktype "
            "LEFT JOIN stockonsale sos ON sos.stockid=sa.stockid "
            "LEFT JOIN stocklines sl ON sl.stocklineid=sos.stocklineid "
            "WHERE (text,time) IN ("
            "SELECT text,max(time) FROM stock_annotations "
            "WHERE atype='location' GROUP BY text) "
            "AND s.finished IS NULL "
            "ORDER BY text",)),
                ]
    def postprocess_queries(self,rl):
        # Look for the "businesses" result and the "weeks" result.
        # Find up to the first two entries in "weeks" for each business,
        # and build a dictionary of business:first_two_weeks.  Add this to
        # the result list.
        d=dict(rl)
        businesses=d['businesses']
        weeks=d['weeks']
        bd={}
        for (i,) in businesses:
            bwl=[]
            bd[i]=bwl
            for abbrev,mindate,maxdate,weektotal in weeks:
                if abbrev!=i: continue
                if len(bwl)>=2: continue
                bwl.append((mindate,maxdate,weektotal))
        rl.append(("bw",bd))
        return rl
    def template(self,searchList):
        return Template.Template(source=formatBlock("""
        #extends page
        #implements body
        #filter webSafeFilter
        <table class="bordered">
        <tr><th>Current session</th>
        <th>Current week</th>
        <th>Last week</th></tr>
        <tr><td>
        #if len($currentsession)!=0
        <a href="$root/sessions/$currentsession[0][1]">$currentsession[0][1] ($currentsession[0][2])<br />
        #for $business,$sessionid,$sessiondate,$amount in $currentsession
        $business: <span class="money">$amount</span><br />
        #end for
        </a>
        #else
        There is no session currently in progress.
        #end if
        </td>
        <td>
        #for $b in $businesses
        #set $businessweek=$bw[$b[0]]
        #if len($businessweek)<1
        $b[0]: No trade
        #else
        #set $week=$businessweek[0]
        <a href="$root/sessions?startdate=$week[0]&enddate=$week[1]">$week[0] &#8211; $week[1]<br />$b[0]: <span class="money">$week[2]</span></a><br />
        #end if
        #end for
        </td>
        <td>
        #for $b in $businesses
        #set $businessweek=$bw[$b[0]]
        #if len($businessweek)<2
        $b[0]: No trade
        #else
        #set $week=$businessweek[1]
        <a href="$root/sessions?startdate=$week[0]&enddate=$week[1]">$week[0] &#8211; $week[1]<br />$b[0]: <span class="money">$week[2]</span></a><br />
        #end if
        #end for
        </td>
        </tr>
        </table>
        <h1>On the bar</h1>
        <table>
        <tr><th>Line</th><th>Product</th><th>ABV</th><th>Started</td><th>Used</th><th>Remaining</th></tr>
        #for $line,$stockid,$product,$abv,$used,$remaining,$unitname,$onsale in $onthebar
        <tr $zebra><td>$line</td>
        #if $product
        <td><a href="$root/stock/$stockid">$product</a></td>
        <td#if $abv# class="abv"#end if#>$abv</td>
        <td class="date">$onsale</td>
        <td class="qty">$used $(unitname)s</td>
        <td class="qty">$remaining $(unitname)s</td>
        #else
        <td></td><td></td><td></td><td></td><td></td>
        #end if
        </tr>
        #end for
        </table>
        <h1>On the stillage</h1>
        <table>
        <tr><th>Location</th><th>Time</th><th>Cask</th><th>Line</th></tr>
        #for $loc,$stockid,$time,$cask,$line in $stillage
        <tr><td>$loc</td><td class="date">$time</td>
        <td><a href="$root/stock/$stockid">$cask</a></td><td>$line</td></tr>
        #end for
        </table>
        <h1><a href="$root/sheet.csv">Data as spreadsheet (CSV)</a></h1>
        #end filter
        """),searchList=searchList,filtersLib=Filters)

class SessionIndex(DBPage):
    def getChild(self,name,request):
        if name=='':
            return self
        try:
            return Session(self.title,self.pool,int(name))
        except:
            Resource.getChild(self,name,request)
    def queries(self,request):
        limit=100
        if request.args.has_key('limit'):
            limit=int(request.args['limit'][0])
        if request.args.has_key('startdate'):
            startdate=mkdate(request.args['startdate'][0])
        else:
            startdate=mindate
        if request.args.has_key('enddate'):
            enddate=mkdate(request.args['enddate'][0])
        else:
            enddate=maxdate
        return [('sessions',(
            "SELECT s.sessionid,s.sessiondate,to_char(s.sessiondate,'Dy'),"
            "(SELECT sum(tl.items*tl.amount) FROM transactions t "
            "LEFT JOIN translines tl ON t.transid=tl.transid "
            "WHERE t.sessionid=s.sessionid) AS tilltotal,"
            "(SELECT sum(st.amount) FROM sessiontotals st "
            "WHERE st.sessionid=s.sessionid),"
            "(SELECT sum(stock.saleprice*stockout.qty)::numeric(7,2) FROM "
            "stockout LEFT JOIN stock ON stockout.stockid=stock.stockid "
            "WHERE (stockout.time::date)=s.sessiondate "
            "AND stockout.removecode='freebie') "
            "FROM sessions s "
            "WHERE s.sessiondate>=%s AND s.sessiondate<=%s "
            "ORDER BY s.sessionid DESC LIMIT %s",(startdate,enddate,limit)))]
    def template(self,searchList):
        return Template.Template(source=formatBlock("""
        #extends page
        #implements body
        #filter webSafeFilter
        <table><tr><th>Session</th><th>Date</th><th>Day</th>
        <th>Till Total</th><th>Actual Total</th><th>Free Drinks</th></tr>
        #for $sessionid,$sessiondate,$sessionday,$tilltotal,$realtotal,$freetotal in $sessions
        <tr $zebra>
        <td class="sessionid"><a href="$root/sessions/$sessionid">$sessionid</a></td>
        <td class="date">$sessiondate</td>
        <td>$sessionday</td>
        <td class="money">$tilltotal</td>
        <td class="money">$realtotal</td>
        <td class="money">$freetotal</td>
        </tr>
        #end for
        </table>
        #end filter
        """), searchList=searchList,filtersLib=Filters)

class Session(DBPage):
    isLeaf=True
    def __init__(self,title,pool,number):
        DBPage.__init__(self,title+" - Session %d"%number,pool)
        self.number=number
    def queries(self,request):
        return [('depttotals',(
            "SELECT d.dept,d.description,sum(l.items*l.amount) AS amount "
            "FROM sessions s "
            "LEFT JOIN transactions t ON t.sessionid=s.sessionid "
            "LEFT JOIN translines l ON l.transid=t.transid "
            "LEFT JOIN departments d ON l.dept=d.dept "
            "WHERE s.sessionid=%s "
            "GROUP BY d.dept,d.description "
            "ORDER BY d.dept",self.number)),
                ('tilltotal',(
            "SELECT sum(tl.items*tl.amount) FROM transactions t "
            "LEFT JOIN translines tl ON t.transid=tl.transid "
            "WHERE t.sessionid=%s",self.number)),
                ('transactions',(
            "SELECT t.transid,sum(tl.items*tl.amount) AS amount "
            "FROM transactions t "
            "LEFT JOIN translines tl ON tl.transid=t.transid "
            "WHERE t.sessionid=%s "
            "GROUP BY t.transid "
            "ORDER BY t.transid DESC",self.number)),
                ('stocksold',(
            "SELECT s.stocktype,st.shortname,sum(so.qty) AS qty,ut.name "
            "FROM transactions t "
            "LEFT JOIN translines tl ON t.transid=tl.transid "
            "INNER JOIN stockout so ON tl.stockref=so.stockoutid "
            "LEFT JOIN stock s ON s.stockid=so.stockid "
            "LEFT JOIN stocktypes st ON st.stocktype=s.stocktype "
            "LEFT JOIN unittypes ut ON st.unit=ut.unit "
            "WHERE t.sessionid=%s "
            "GROUP BY s.stocktype,st.shortname,ut.name,tl.dept "
            "ORDER BY tl.dept,sum(so.qty) DESC",self.number)),
                ('freebies',(
            "SELECT s.stocktype,st.shortname,sum(so.qty) AS qty,ut.name "
            "FROM stockout so LEFT JOIN stock s ON s.stockid=so.stockid "
            "LEFT JOIN stocktypes st ON st.stocktype=s.stocktype "
            "LEFT JOIN unittypes ut ON st.unit=ut.unit "
            "WHERE (so.time::date)=(SELECT sessiondate FROM sessions "
            "WHERE sessionid=%s) AND so.removecode='freebie' "
            "GROUP BY s.stocktype,st.shortname,ut.name "
            "ORDER BY sum(so.qty) DESC",self.number)),]
    def template(self,searchList):
        return Template.Template(source=formatBlock("""
        #extends page
        #implements body
        #filter webSafeFilter
        #set $session=$resource.number
        <table><tr><th>Dept</th><th>Description</th><th>Total</th></tr>
        #for $dept,$desc,$amount in $depttotals
        <tr $zebra>
        <td class="dept"><a href="$root/translines?session=$session&amp;department=$dept">$dept</a></td>
        <td><a href="$root/translines?session=$session&amp;department=$dept">$desc</a></td>
        <td class="money">$amount</td></tr>
        #end for
        <tr $zebra><td></td><td>Total</td><td class="money">$tilltotal[0][0]</td></tr>
        </table>
        <h1>Stock sold in this session</h1>
        <table>
        #for $stocktype,$shortname,$qty,$unitname in $stocksold
        <tr $zebra><td><a href="$root/stock?stocktype=$stocktype">$shortname</td>
        <td class="qty">$qty $(unitname)s</td></tr>
        #end for
        </table>
        #if len($freebies)>0
        <h1>Stock given away on this session's date</h1>
        <table>
        #for $stocktype,$shortname,$qty,$unitname in $freebies
        <tr $zebra><td><a href="$root/stock?stocktype=$stocktype">$shortname</td>
        <td class="qty">$qty $(unitname)s</td></tr>
        #end for
        </table>
        #else
        <p>No stock was given away on this session's date.</p>
        #end if
        <table><tr><th>Transaction</td><th>Amount</th></tr>
        #for $transid,$amount in $transactions
        <tr $zebra><td class="transid"><a href="$root/translines?transaction=$transid">$transid</a></td>
        <td class="money">$amount</td></tr>
        #end for
        </table>
        #end filter
        """), searchList=searchList,filtersLib=Filters)

class StockIndex(DBPage):
    def getChild(self,name,request):
        if name=='':
            return self
        try:
            return Stock(self.title,self.pool,int(name))
        except:
            Resource.getChild(self,name,request)
    def queries(self,request):
        fields=("st.stockid,st.stocktype,st.manufacturer,st.name,"
                "st.abv,st.unitname,"
                "st.size,st.used,st.sold,"
                "CASE WHEN st.used IS NULL THEN st.size "
                "ELSE st.size-st.used END AS remaining,"
                "((st.used/st.size)*100)::numeric(5,1) AS usedpct,"
                "((st.sold/st.size)*100)::numeric(5,1) AS soldpct,"
                "finishdescription,finishcode")
        clauses=[]
        if request.args.has_key("department"):
            clauses.append("st.dept IN (%s)"%','.join(
                request.args['department']))
        if request.args.has_key("delivery"):
            clauses.append("st.deliveryid IN (%s)"%','.join(
                request.args['delivery']))
        if request.args.has_key("manufacturer"):
            clauses.append("st.manufacturer IN (%s)"%','.join(
                ["'%s'"%x for x in request.args['manufacturer']]))
        if request.args.has_key("stocktype"):
            clauses.append("st.stocktype IN (%s)"%','.join(
                request.args['stocktype']))
        if request.args.has_key("finished"):
            clauses.append("st.finished IS "+("NULL","NOT NULL")[
                request.args['finished'][0]=='true'])
        if len(clauses)>0:
            where='WHERE '+(' AND '.join(clauses))
        else:
            where=""
        return [('stock',(
            "SELECT %s FROM stockinfo st %s "
            "ORDER BY st.stockid DESC"%(fields,where),))]
    def template(self,searchList):
        return Template.Template(source=formatBlock("""
        #extends page
        #implements body
        #filter webSafeFilter
        <table><tr><th>Stock ID</th><th>Manufacturer</th>
        <th>Name</th><th>ABV</th><th>Used</th><th>Sold</th><th>Remaining</th><th>Finished?</th></tr>
        #for $stockid,$stocktype,$manufacturer,$name,$abv,$unitname,$size,$used,$sold,$remaining,$usedpct,$soldpct,$finishdescription,$finishcode in $stock
        #set $usedclass='qty'
        #set $soldclass='qty'
        #set $finishclass='finish'
        #if $finishcode=='empty'
        #if $usedpct is None
        #set $usedpct=0.0
        #end if
        #if $soldpct is None
        #set $soldpct=0.0
        #end if
        #if float($usedpct)<90.0
        #set $usedclass='qtywarn'
        #end if
        #if float($usedpct)<85.0
        #set $usedclass='qtyerr'
        #end if
        #if float($soldpct)<84.0
        #set $soldclass='qtywarn'
        #end if
        #if float($soldpct)<80.0
        #set $soldclass='qtyerr'
        #end if
        #else
        #set $finishclass='finishwarn'
        #end if
        <tr $zebra>
        <td class="stockid"><a href="$root/stock/$stockid">$stockid</a></td>
        <td><a href="$root/stock?manufacturer=$manufacturer">$manufacturer</a></td>
        <td><a href="$root/stock?stocktype=$stocktype">$name</a></td>
        <td#if $abv# class="abv"#end if#>$abv</td>
        <td class="$usedclass">#if $used#$used $(unitname)s ($usedpct%)#end if#</td>
        <td class="$soldclass">#if $sold#$sold $(unitname)s ($soldpct%)#end if#</td>
        <td class="qty">$remaining $(unitname)s</td>
        <td class="$finishclass">$finishdescription</td>
        </tr>
        #end for
        </table>
        #end filter
        """), searchList=searchList,filtersLib=Filters)
    def csv(self,w,r):
        w.writerow(["StockID","Manufacturer","Name","ABV","Size","Used","Sold",
                    "Remaining","Finished"])
        for (stockid,stocktype,manufacturer,name,abv,unitname,size,
             used,sold,remaining,usedpct,soldpct,
             finishdescription,finishcode) in r['stock']:
            w.writerow([stockid,manufacturer,name,abv,size,used,sold,
                        remaining,finishdescription])

class Stock(DBPage):
    def __init__(self,title,pool,number):
        DBPage.__init__(self,title,pool)
        self.number=number
    def queries(self,request):
        return [('stock',(
            "SELECT stockid,stocktype,deliveryid,dept,deptname,"
            "manufacturer,name,shortname,abv,unit,unitname,stockunit,"
            "sunitname,size,costprice,saleprice,onsale,finished,"
            "finishcode,finishdescription,bestbefore,suppliername,"
            "deliverydate,deliverynote,deliverychecked,used,"
            "CASE WHEN used IS NULL THEN size ELSE size-used END "
            "AS remaining FROM stockinfo WHERE stockid=%s",
            self.number)),
                ('summary',(
            "SELECT sr.reason,sum(so.qty) "
            "FROM stockout so "
            "LEFT JOIN stockremove sr ON sr.removecode=so.removecode "
            "WHERE so.stockid=%s GROUP BY sr.reason",self.number)),
                ('stockout',(
            "SELECT translineid,qty,removecode,time FROM stockout WHERE stockid=%s "
            "ORDER BY time DESC",self.number)),
                ('annotations',(
            "SELECT at.description,sa.time,sa.text FROM stock_annotations sa "
            "LEFT JOIN annotation_types at ON at.atype=sa.atype "
            "WHERE sa.stockid=%s ORDER BY sa.time",self.number))]
    def template(self,searchList):
        return Template.Template(source=formatBlock("""
        #extends page
        #implements body
        #filter webSafeFilter
        <table class="kvtable">
        #for $stockid,$stocktype,$deliveryid,$dept,$deptname,$manufacturer,$name,$shortname,$abv,$unit,$unitname,$stockunit,$sunitname,$size,$costprice,$saleprice,$onsale,$finished,$finishcode,$finishdescription,$bestbefore,$suppliername,$deliverydate,$deliverynote,$deliverychecked,$used,$remaining in $stock
        <tr><td>Stock id</td><td class="stockid">$stockid</td></tr>
        <tr><td>Manufacturer</td>
        <td><a href="$root/stock?manufacturer=$manufacturer">$manufacturer</a></td></tr>
        <tr><td>Name</td>
        <td><a href="$root/stock?stocktype=$stocktype">$name</a></td></tr>
        <tr><td>Short name</td><td>$shortname</td></tr>
        #if $abv
        <tr><td>ABV</td><td#if $abv# class="abv"#end if#>$abv</td></tr>
        #end if
        <tr><td>Supplier</td><td>$suppliername</td></tr>
        <tr><td>Delivery date</td><td class="date">$deliverydate</td></tr>
        <tr><td>Delivery ID</td><td class="deliveryid"><a
        href="$root/stock?delivery=$deliveryid">$deliveryid</td></tr>
        <tr><td>Department</td><td class="deptname">$deptname</td></tr>
        <tr><td>Stock unit</td><td>$sunitname ($size $(unitname)s)</td></tr>
        <tr><td>Cost price</td><td class="money">$costprice (ex-VAT)</td></tr>
        <tr><td>Sale price</td><td class="money">$saleprice/$unitname (inc-VAT)</td></tr>
        #if $onsale
        <tr><td>Put on sale</td><td class="date">$onsale</td></tr>
        #if $finished
        <tr><td>Finished</td><td class="date">$finished ($finishdescription)</td></tr>
        #end if
        #end if
        <tr><td>Best before</td><td class="date">$bestbefore</td></tr>
        <tr><td>Amount used</td><td><table>
        #for $removecode,$qty in $summary
        <tr $zebra><td>$removecode</td><td class="qty">$qty $(unitname)s</td></tr>
        #end for
        </table></td></tr>
        <tr><td>Amount remaining</td><td>$remaining $(unitname)s</td></tr>
        #end for
        <tr><td>Annotations</td><td><table>
        #for $atype,$time,$text in $annotations
        <tr $zebra><td class="date">$time</td><td>$atype</td><td>$text</td></tr>
        #end for
        </table></td></tr>
        </table>
        <table><tr><th>Code</th><th>Quantity</th><th>Time</th></tr>
        #for $translineid,$qty,$reason,$time in $stockout
        <tr $zebra><td>#if $translineid
        <a href="$root/translines?transline=$translineid">$reason</a>
        #else
        $reason
        #end if
        </td><td class="qty">$qty</td><td class="date">$time</td></tr>
        #end for
        </table>
        #end filter
        """),searchList=searchList,filtersLib=Filters)

class SummarySheet(Resource):
    def __init__(self,title,pool):
        self.title=title
        self.pool=pool
    def render_GET(self,request):
        sd=self.pool.runQuery(
            "SELECT s.sessionid,s.sessiondate FROM sessions s "
            "INNER JOIN sessiontotals st ON s.sessionid=st.sessionid "
            "GROUP BY s.sessionid,s.sessiondate ORDER BY s.sessionid")
        ptd=self.pool.runQuery(
            "SELECT paytype,description FROM paytypes ORDER BY paytype")
        std=self.pool.runQuery(
            "SELECT st.sessionid,st.paytype,st.amount "
            "FROM sessiontotals st "
            "ORDER BY st.sessionid")
        deptd=self.pool.runQuery(
            "SELECT dept,description FROM departments ORDER BY dept")
        ttd=self.pool.runQuery(
            "SELECT s.sessionid,tl.dept,sum(tl.items*tl.amount) "
            "FROM sessions s "
            "LEFT JOIN transactions t ON s.sessionid=t.sessionid "
            "LEFT JOIN translines tl ON t.transid=tl.transid "
            "GROUP BY s.sessionid,tl.dept "
            "ORDER BY s.sessionid,tl.dept")
        dl=[sd,ptd,std,deptd,ttd]
        d=defer.DeferredList(dl)
        d.addCallback(self.finish_render,request)
        request.setHeader('Content-type','text/comma-separated-values')
        return server.NOT_DONE_YET
    def finish_render(self,dl,request):
        # dl is a list of (success,result) tuples corresponding to the
        # queries.  For now I'm going to be lazy and assume they
        # were all successful (because pgasync doesn't actually report
        # errors at the moment).
        sessions=dl[0][1]
        paytypes=dl[1][1]
        sessiontotals=dl[2][1]
        departments=dl[3][1]
        tilltotals=dl[4][1]
        # We're going to build a table with one line per session, and
        # columns for actual payments and department totals.  To do this
        # we first build a dictionary of sessions and tilltotals (which may
        # include sessions for which actual totals haven't been entered)
        # and then iterate through the payment totals.
        ttd={}
        for s,d,t in tilltotals:
            ttd[(s,d)]=t
        std={}
        for sid,pt,amount in sessiontotals:
            std[(sid,pt)]=amount
        w=csv.writer(request)
        # Each row consists of:
        # sessionid,sessiondate,sessionday,[paytypes...],paytotal,
        # [departments...],depttotal
        w.writerow(["Session","Date","Day"]+
                   [y for x,y in paytypes]+
                   ["Actual"]+
                   [desc for d,desc in departments]+
                   ["Till total"])
        for sessionid,sessiondate in sessions:
            sessiontotal=0.0
            tilltotal=0.0
            for x,y in paytypes:
                sessiontotal+=float(std.get((sessionid,x),0.0))
            for d,desc in departments:
                tilltotal+=float(ttd.get((sessionid,d),0.0))
            w.writerow(
                [sessionid,sessiondate.strftime("%d/%m/%Y"),sessiondate.strftime("%A")]+
                [std.get((sessionid,x),'') for x,y in paytypes]+
                [sessiontotal]+
                [ttd.get((sessionid,d),'') for d,desc in departments]+
                [tilltotal])
        request.finish()

class DeliveryIndex(DBPage):
    def getChild(self,name,request):
        if name=='':
            return self
        try:
            return Delivery(self.title,self.pool,int(name))
        except:
            Resource.getChild(self,name,request)
    def queries(self,request):
        return [('deliveries',(
            "SELECT d.deliveryid,d.date,d.supplierid,sup.name,d.docnumber,d.checked "
            "FROM deliveries d "
            "LEFT JOIN suppliers sup ON d.supplierid=sup.supplierid "
            "ORDER BY d.date DESC,d.deliveryid DESC",))]
    def template(self,searchList):
        return Template.Template(source=formatBlock("""
        #extends page
        #implements body
        #filter webSafeFilter
        <table>
        <tr><th>Delivery ID</th><th>Date</th><th>Supplier</th><th>Document</th>
        <th>Checked?</th></tr>
        #for $deliveryid,$date,$supplierid,$suppliername,$doc,$checked in $deliveries
        #if $request.args.get('supplier') is None or int($request.args.get('supplier')[0])==$supplierid
        <tr $zebra>
        <td class="deliveryid"><a href="$root/stock?delivery=$deliveryid">$deliveryid</a></td>
        <td class="date">$date</td>
        <td><a href="$root/deliveries?supplier=$supplierid">$suppliername</a></td>
        <td>$doc</td>
        <td>#if $checked#Yes#else#No#end if#</td>
        </tr>
        #end if
        #end for
        </table>
        #end filter
        """),searchList=searchList,filtersLib=Filters)

class StockLines(DBPage):
    def queries(self,request):
        return [('stocklines',("select sl.name,coalesce(sos.displayqty,0) as displayqty,sos.stockid,st.shortname,su.size::int,(select coalesce(sum(so.qty),0)::int from stockout so where so.stockid=s.stockid) as used from stocklines sl left join stockonsale sos on sl.stocklineid=sos.stocklineid left join stock s on s.stockid=sos.stockid left join stocktypes st on s.stocktype=st.stocktype left join stockunits su on s.stockunit=su.stockunit where sl.capacity is not null order by sl.name,s.stockid",))]
    def template(self,searchList):
        return Template.Template(source=formatBlock("""
        #extends page
        #implements body
        #filter webSafeFilter
        <table>
        <tr>
        <th>Stock line</th><th>Stock ID</th><th>Name</th><th>Remaining</th>
        </tr>
        #set $lastline=""
        #for $linename,$displayqty,$stockid,$stockname,$size,$used in $stocklines
        <tr $zebra>
        #if $linename!=$lastline
        <td class="stockline">$linename</a></td>
        #set $lastline=$linename
        #else
        <td></td>
        #end if
        #if $stockid is None
        <td></td><td>(No stock)</td><td></td>
        #else
        #set $ondisplay=$displayqty-$used
        #set $incellar=$size-max($displayqty,$used)
        <td class="stockid"><a href="$root/stock/$stockid">$stockid</a></td>
        <td>$stockname</td>
        <td>$ondisplay + $incellar</td>
        #end if
        </tr>
        #end for
        </table>
        #end filter
        """),searchList=searchList,filtersLib=Filters)

class TransLines(DBPage):
    def queries(self,request):
        fields=("tl.translineid,tl.transid,tl.items,tl.amount,tl.dept,"
                "tl.source,tl.stockref,tl.transcode,tl.time,"
                "s.stockid,st.shortname,d.description")
        clauses=[]
        transjoin=""
        if request.args.has_key("department"):
            clauses.append("tl.dept IN (%s)"%','.join(
                request.args['department']))
        if request.args.has_key("session"):
            clauses.append("t.sessionid IN (%s)"%','.join(
                request.args['session']))
            transjoin="LEFT JOIN transactions t ON t.transid=tl.transid "
        if request.args.has_key("transaction"):
            clauses.append("tl.transid IN (%s)"%','.join(
                request.args['transaction']))
        if request.args.has_key("transline"):
            clauses.append("tl.transid IN (SELECT transid FROM translines WHERE translineid IN (%s))"%','.join(
                request.args['transline']))
        if request.args.has_key("stockid"):
            clauses.append("s.stockid IN (%s)"%','.join(
                request.args['stockid']))
        if len(clauses)>0:
            where='WHERE '+(' AND '.join(clauses))
        else:
            where=""
        return [('translines',(
            ("SELECT %s FROM translines tl "+
             transjoin+
             "LEFT JOIN departments d ON d.dept=tl.dept "
             "LEFT JOIN stockout so ON so.stockoutid=tl.stockref "
             "LEFT JOIN stock s ON so.stockid=s.stockid "
             "LEFT JOIN stocktypes st ON s.stocktype=st.stocktype "
             "%s ORDER BY tl.translineid LIMIT 500")%(fields,where),))]
    def template(self,searchList):
        return Template.Template(source=formatBlock("""
        #extends page
        #implements body
        #filter webSafeFilter
        <table>
        <tr><th>Transaction</th><th>ID</th><th>Department</th><th>Items</th>
        <th>Price</th><th>Stock</th><th>Code</th><th>Time</th></tr>
        #for $translineid,$transid,$items,$amount,$dept,$source,$stockref,$transcode,$time,$stockid,$shortname,$deptname in $translines
        <tr $zebra>
        <td class="transid"><a href="$root/translines?transaction=$transid">$transid</a></td>
        <td class="translineid">$translineid</td>
        <td>$deptname</td>
        <td>$items</td>
        <td class="money">$amount</td>
        <td><a href="$root/stock/$stockid">$shortname</a></td>
        <td>$transcode</td>
        <td class="date">$time</td>
        </tr>
        #end for
        </table>
        #end filter
        """),searchList=searchList,filtersLib=Filters)

class Statistics(DBPage):
    def queries(self,request):
        return [('bestsellers',(
            "SELECT s.stocktype,st.shortname,sum(so.qty) FROM stock s "
            "LEFT JOIN stocktypes st ON s.stocktype=st.stocktype "
            "LEFT JOIN stockout so ON s.stockid=so.stockid "
            "WHERE so.removecode='sold' AND st.dept=1 "
            "GROUP BY s.stocktype,st.shortname "
            "ORDER BY sum(so.qty) DESC LIMIT 20",()))]
    def template(self,searchList):
        return Template.Template(source=formatBlock("""
        #extends page
        #implements body
        #filter webSafeFilter
        <h1>Top 20 Best-Selling Real Ales</h1>
        <table>
        #for $stocktype,$name,$qty in $bestsellers
        <tr $zebra>
        <td><a href="$root/stock?stocktype=$stocktype">$name</a></td>
        <td class="qty">$qty</td>
        </tr>
        #end for
        </table>
        #end filter
        """),searchList=searchList,filtersLib=Filters)
