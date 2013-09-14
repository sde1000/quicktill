import string,time
from . import td,ui,tillconfig
from decimal import Decimal
from .models import Delivery,VatBand,Business,Transline,Transaction

driver=None
labeldriver=None

# All of these functions assume there's a database session in td.s
# This should be the case if called during a keypress!  If being used
# in any other context, create one using td.start_session() and then
# remove it afterwards with td.end_session()

def print_receipt(transid):
    from . import stock
    trans=td.s.query(Transaction).get(transid)
    transopen=False
    if len(trans.lines)==0: return
    linestotal=trans.total
    paymentstotal=trans.payments_total
    if linestotal!=paymentstotal: transopen=True
    driver.start()
    driver.printline("\t%s"%tillconfig.pubname,emph=1)
    for i in tillconfig.pubaddr:
        driver.printline("\t%s"%i,colour=1)
    driver.printline("\tTel. %s"%tillconfig.pubnumber)
    driver.printline()
    multiband=td.trans_multiband(transid)
    date=trans.session.date
    bandtotals={}
    for tl in trans.lines:
        bandtotals[tl.department.vatband]=bandtotals.get(
            tl.department.vatband,Decimal("0.00"))+(tl.items*tl.amount)
        left=tl.description
        right=tl.regtotal(tillconfig.currency)
        if multiband and not transopen:
            driver.printline("%s\t\t%s %s"%(left,right,tl.department.vatband),font=1)
        else:
            driver.printline("%s\t\t%s"%(left,right),font=1)
    totalpad="  " if multiband else ""
    driver.printline("\t\tSubtotal %s%s"%(tillconfig.fc(linestotal),totalpad),
                     colour=1,emph=1)
    for p in trans.payments:
        if p.paytype_id=='CASH':
            driver.printline("\t\t%s %s%s"%(p.ref,
                                            tillconfig.fc(p.amount),totalpad))
        else:
            if ref is None:
                driver.printline("\t\t%s %s%s"%(p.paytype.description,
                                                tillconfig.fc(p.amount),
                                                totalpad))
            else:
                driver.printline("\t\t%s %s %s%s"%(
                    p.paytype.description,p.ref,tillconfig.fc(p.amount),totalpad))
    driver.printline("")
    if transopen:
        driver.printline("\tThis is not a VAT receipt",colour=1,emph=1)
        driver.printline("\tTransaction number %d"%trans.id)
    else:
        # We have a list of VAT bands; we need to look up rate and
        # business information for each of them.  Once we have the
        # list of businesses, we can print out a section per business.
        # In each section, show the business name and address, VAT
        # number, and then for each VAT band the net amount, VAT and
        # total.
        businesses={} # Keys are business IDs, values are (band,rate) tuples
        for i in list(bandtotals.keys()):
            vr=td.s.query(VatBand).get(i).at(date)
            businesses.setdefault(vr.business.id,[]).append((i,vr.rate))
        for i in list(businesses.keys()):
            business=td.s.query(Business).get(i)
            bands=businesses[i]
            # Print the business info
            driver.printline("\t%s"%business.name)
            for l in business.address.split('\\n'):
                driver.printline("\t%s"%l)
            driver.printline()
            driver.printline("VAT reg no. %s"%business.vatno)
            for band,rate in bands:
                # Print the band, amount ex VAT, amount inc VAT, gross
                gross=bandtotals[band]
                net=gross/((rate/Decimal("100.0"))+Decimal("1.0"))
                vat=gross-net
                driver.printline("%s: %s net, %s VAT @ %0.1f%%\t\tTotal %s"%(
                        band,tillconfig.fc(net),tillconfig.fc(vat),rate,
                        tillconfig.fc(gross)),font=1)
            driver.printline("")
        driver.printline("\tReceipt number %d"%trans.id)
    driver.printline("\t%s"%ui.formatdate(date))
    driver.end()

def print_sessioncountup(s):
    driver.start()
    driver.printline("\t%s"%tillconfig.pubname,emph=1)
    driver.printline("\tSession %d"%s.id,colour=1)
    driver.printline("\t%s"%ui.formatdate(s.date),colour=1)
    driver.printline("Started %s"%ui.formattime(s.starttime))
    driver.printline("  Ended %s"%ui.formattime(s.endtime))
    driver.printline()
    driver.printline("Amounts registered:")
    for paytype,total in s.payment_totals:
        driver.printline("%s: %s"%(paytype.description,tillconfig.fc(total)))
    driver.printline()
    for i in ("    50","    20","    10",
              "     5","     2","     1",
              "  0.50","  0.20","  0.10",
              "  0.05","  0.02","  0.01",
              "  Bags","  Misc","-Float"):
        driver.printline("   %s"%i)
        driver.printline()
    driver.printline(underline=1)
    driver.printline("Cash Total",colour=1,emph=1)
    driver.printline()
    driver.printline(underline=1)
    for paytype,total in s.payment_totals:
        if paytype.paytype=='CASH': continue
        driver.printline("%s Total"%paytype.description,colour=1,emph=1)
        driver.printline()
        driver.printline(underline=1)
    driver.printline("Enter totals into till using")
    driver.printline("management menu option 1,3.")
    driver.end()

def print_sessiontotals(s):
    """Print a session totals report given a Session object.

    """
    depts=s.dept_totals
    paytotals=dict(s.payment_totals)
    payments=dict([(x.paytype,x) for x in s.actual_totals])
    paytypes=set(list(paytotals.keys())+list(payments.keys()))
    driver.start()
    driver.printline("\t%s"%tillconfig.pubname,emph=1)
    driver.printline("\tSession %d"%s.id,colour=1)
    driver.printline("\t%s"%ui.formatdate(s.date),colour=1)
    driver.printline("Started %s"%ui.formattime(s.starttime))
    if s.endtime is None:
        driver.printline("Session still in progress")
        driver.printline("Printed %s"%ui.formattime(ui.now()))
    else:
        driver.printline("  Ended %s"%ui.formattime(s.endtime))
    driver.printline("Till total:\t\tActual total:")
    ttt=Decimal("0.00")
    att=Decimal("0.00")
    for i in paytypes:
        desc=i.description
        if i in paytotals:
            tt=tillconfig.fc(paytotals[i])
            ttt=ttt+paytotals[i]
        else:
            tt=""
        if i in payments:
            at=tillconfig.fc(payments[i].amount)
            att=att+payments[i].amount
        else:
            at=""
        driver.printline("%s: %s\t\t%s"%(desc,tt,at))
    if len(paytypes)>1:
        tt=tillconfig.fc(ttt)
        if att>Decimal("0.00"):
            at=tillconfig.fc(att)
        else:
            at=""
        driver.printline("Total: %s\t\t%s"%(tt,at),colour=1,emph=1)
    driver.printline()
    dt=Decimal("0.00")
    for dept,total in depts:
        driver.printline("%2d %s\t\t%s"%(dept.id,dept.description,
                                         tillconfig.fc(total)))
        dt=dt+total
    driver.printline("\t\tTotal: %s"%tillconfig.fc(dt),colour=1,emph=1)
    driver.printline()
    driver.printline("\tPrinted %s"%ui.formattime(ui.now()))
    driver.end()

def label_print_delivery(delivery):
    d=td.s.query(Delivery).get(delivery)
    stocklabel_print(d.items)

def stocklabel_print(sl):
    """Print stock labels for a list of stock numbers.

    """
    td.s.add_all(sl)
    labeldriver.start()
    def stock_label(f,width,height,d):
        # Item name
        # Supplier
        # Delivery date
        # Stock unit
        # Stock number
        fontsize=12
        margin=12
        pitch=fontsize+2
        fontname="Times-Roman"
        f.setFont(fontname,fontsize)
        def fits(s):
            sw=f.stringWidth(s,fontname,fontsize)
            return sw<(width-(2*margin))
        y=height-margin-fontsize
        f.drawCentredString(width/2,y,d.stocktype.format(fits))
        y=y-pitch
        f.drawCentredString(width/2,y,d.delivery.supplier.name)
        y=y-pitch
        f.drawCentredString(width/2,y,ui.formatdate(d.delivery.date))
        y=y-pitch
        f.drawCentredString(width/2,y,d.stockunit.name)
        if tillconfig.checkdigit_print:
            y=y-pitch
            f.drawCentredString(width/2,y,"Check digits: %s"%(d.checkdigits,))
        f.setFont(fontname,y-margin)
        f.drawCentredString(width/2,margin,str(d.id))
    for sd in sl:
        labeldriver.addlabel(stock_label,sd)
    labeldriver.end()

def print_delivery(delivery):
    d=td.s.query(Delivery).get(delivery)
    driver.start()
    driver.printline("\t%s"%tillconfig.pubname,emph=1)
    driver.printline("\tDelivery %d"%d.id,colour=1)
    driver.printline("Supplier: %s"%d.supplier.name)
    driver.printline("Date: %s"%ui.formatdate(d.date))
    driver.printline("Delivery note: %s"%d.docnumber)
    if not d.checked:
        driver.printline("Details not yet confirmed -")
        driver.printline("may still be edited.")
    driver.printline()
    for s in d.items:
        driver.printline("Stock number %d"%s.id,colour=1)
        driver.printline(s.stocktype.format(maxw=driver.checkwidth))
        driver.printline("%s cost %s"%(
            s.stockunit.name,tillconfig.fc(s.costprice)))
        driver.printline("sale %s BB %s"%(
            tillconfig.fc(s.saleprice),ui.formatdate(s.bestbefore)))
        driver.printline()
    driver.printline("\tEnd of list")
    driver.end()

def print_stocklist(sl,title="Stock List"):
    from . import stock
    driver.start()
    driver.printline("\t%s"%tillconfig.pubname,emph=1)
    driver.printline("\t%s"%title,colour=1)
    driver.printline("\t Printed %s"%ui.formattime(ui.now()))
    driver.printline()
    for sd in sl:
        driver.printline("Stock number %d"%sd['stockid'],colour=1)
        driver.printline(stock.format_stock(sd,maxw=driver.checkwidth))
        driver.printline("%s cost %s"%(
            sd['stockunit'],tillconfig.fc(sd['costprice'])))
        driver.printline("sale %s BB %s"%(
            tillconfig.fc(sd['saleprice']),ui.formatdate(sd['bestbefore'])))
        driver.printline()
    driver.printline("\tEnd of list")
    driver.end()

def print_restock_list(rl):
    driver.start()
    driver.printline("\t%s"%tillconfig.pubname,emph=1)
    driver.printline("\tRe-stock list")
    driver.printline("\tPrinted %s"%ui.formattime(ui.now()))
    driver.printline()
    for stockline,name,ondisplay,capacity,sl in rl:
        driver.printline("%s:"%name)
        driver.printline("%d/%d displayed"%(ondisplay,capacity))
        for sd,move,newdisplayqty,stockqty_after_move in sl:
            if move>0:
                driver.printline(" %d from item %d leaving %d"%(
                    move,sd['stockid'],stockqty_after_move))
            if move<0:
                driver.printline(" %d to item %d making %d"%(
                    -move,sd['stockid'],stockqty_after_move),colour=1)
    driver.printline()
    driver.printline("\tEnd of list")
    driver.end()

def print_food_order(driver,number,ol,verbose=True,tablenumber=None,footer="",
                     transid=None):
    """This function prints a food order to the _specified_ printer.

    """
    driver.start()
    if verbose:
        driver.printline("\t%s"%tillconfig.pubname,emph=1)
        for i in tillconfig.pubaddr:
            driver.printline("\t%s"%i,colour=1)
        driver.printline("\tTel. %s"%tillconfig.pubnumber)
        driver.printline()
    if tablenumber is not None:
        driver.printline("\tTable number %s"%tablenumber,colour=1,emph=1)
        driver.printline()
    if transid is not None:
        driver.printline("\tTransaction %s"%transid)
        driver.printline()
    driver.printline("\tFood order %d"%number,colour=1,emph=1)
    driver.printline()
    driver.printline("\t%s"%ui.formattime(ui.now()))
    driver.printline()
    tot=0.0
    for item in ol:
        driver.printline("%s\t\t%s"%(item.ltext,item.rtext))
        tot+=item.price
    driver.printline("\t\tTotal %s"%tillconfig.fc(tot),emph=1)
    driver.printline()
    driver.printline("\tFood order %d"%number,colour=1,emph=1)
    if verbose:
        driver.printline()
        driver.printline("\t%s"%footer)
    else:
        driver.printline()
        driver.printline()
    driver.end()

def print_order_cancel(driver,number):
    driver.start()
    driver.printline("\tCANCEL order %d"%number,colour=1,emph=1)
    driver.printline()
    driver.printline("\t%s"%ui.formattime(ui.now()))
    driver.printline()
    driver.printline()
    driver.end()

def print_qrcode(btcinfo):
    driver.start()
    driver.printline("\t%s"%tillconfig.pubname,emph=1)
    driver.printline("\tBitcoin payment")
    driver.printline("\t%s"%btcinfo[u'description'])
    driver.printline("\t%s"%tillconfig.fc(float(btcinfo[u'amount'])))
    driver.printline("\t%s BTC to pay"%btcinfo[u'to_pay'])
    driver.printqrcode(str(btcinfo[u'to_pay_url']))
    driver.printline()
    driver.printline()
    driver.end()

def kickout():
    pass

