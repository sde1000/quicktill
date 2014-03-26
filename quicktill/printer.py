from __future__ import unicode_literals
import string,time
from . import td,ui,tillconfig,payment
from decimal import Decimal
from .models import Delivery,VatBand,Business,Transline,Transaction
from .models import zero,penny

import datetime
now=datetime.datetime.now

driver=None
labeldriver=None

# All of these functions assume there's a database session in td.s
# This should be the case if called during a keypress!  If being used
# in any other context, use with td.orm_session(): around the call.

def print_receipt(transid):
    trans=td.s.query(Transaction).get(transid)
    if trans is None: return
    if len(trans.lines)==0: return
    with driver as d:
        d.printline("\t%s"%tillconfig.pubname,emph=1)
        for i in tillconfig.pubaddr:
            d.printline("\t%s"%i,colour=1)
        d.printline("\tTel. %s"%tillconfig.pubnumber)
        d.printline()
        bandtotals={}
        for tl in trans.lines:
            bandtotals[tl.department.vatband]=bandtotals.get(
                tl.department.vatband,Decimal("0.00"))+tl.total
        for tl in trans.lines:
            left=tl.description
            right=tl.regtotal(tillconfig.currency)
            if len(bandtotals)>1 and trans.closed:
                d.printline(
                    "%s\t\t%s %s"%(left,right,tl.department.vatband),font=1)
            else:
                d.printline("%s\t\t%s"%(left,right),font=1)
        totalpad="  " if len(bandtotals)>1 else ""
        d.printline("\t\tSubtotal %s%s"%(tillconfig.fc(trans.total),totalpad),
                    colour=1,emph=1)
        for p in trans.payments:
            pl=payment.pline(p)
            d.printline("\t\t{}{}".format(pl.text,totalpad))
        d.printline("")
        if not trans.closed:
            d.printline("\tThis is not a VAT receipt",colour=1,emph=1)
            d.printline("\tTransaction number %d"%trans.id)
        else:
            # We have a list of VAT bands; we need to look up rate and
            # business information for each of them.  Once we have the
            # list of businesses, we can print out a section per
            # business.  In each section, show the business name and
            # address, VAT number, and then for each VAT band the net
            # amount, VAT and total.
            businesses={} # Keys are business IDs, values are (band,rate) tuples
            for i in list(bandtotals.keys()):
                vr=td.s.query(VatBand).get(i).at(trans.session.date)
                businesses.setdefault(vr.business.id,[]).append((i,vr.rate))
                for i in list(businesses.keys()):
                    business=td.s.query(Business).get(i)
                    bands=businesses[i]
                # Print the business info
                d.printline("\t%s"%business.name)
                # The business address may be stored in the database
                # with either the string "\n" (legacy) or a newline
                # character (current) to separate the lines.
                if "\\n" in business.address:
                    addrlines=business.address.split("\\n")
                else: addrlines=business.address.splitlines()
                for l in addrlines:
                    d.printline("\t%s"%l)
                d.printline()
                d.printline("VAT reg no. %s"%business.vatno)
                for band,rate in bands:
                    # Print the band, amount ex VAT, amount inc VAT, gross
                    gross=bandtotals[band]
                    net=(gross/((rate/Decimal("100.0"))+Decimal("1.0"))).\
                        quantize(penny)
                    vat=gross-net
                    d.printline("%s: %s net, %s VAT @ %0.1f%%\t\tTotal %s"%(
                            band,tillconfig.fc(net),tillconfig.fc(vat),rate,
                            tillconfig.fc(gross)),font=1)
                d.printline("")
        d.printline("\tReceipt number %d"%trans.id)
        d.printline("\t%s"%ui.formatdate(trans.session.date))

def print_sessioncountup(s):
    with driver as d:
        d.printline("\t%s"%tillconfig.pubname,emph=1)
        d.printline("\tSession %d"%s.id,colour=1)
        d.printline("\t%s"%ui.formatdate(s.date),colour=1)
        d.printline("Started %s"%ui.formattime(s.starttime))
        d.printline("  Ended %s"%ui.formattime(s.endtime))
        d.printline()
        d.printline("Amounts registered:")
        for paytype,total in s.payment_totals:
            d.printline("%s: %s"%(paytype.description,tillconfig.fc(total)))
        d.printline()
        # Now go through the current payment methods printing out their
        # input fields, with countup totals if necessary
        d.printline("",underline=1)
        for pm in tillconfig.all_payment_methods:
            for name,validator,print_fields in pm.total_fields:
                for i in print_fields if print_fields else []:
                    d.printline(u"{:>10}".format(i))
                    d.printline()
                if print_fields: d.printline("",underline=1)
                if len(pm.total_fields)>1:
                    d.printline(u"{} {}".format(pm.description,name),
                                     colour=1,emph=1)
                else:
                    d.printline(pm.description,colour=1,emph=1)
                d.printline()
                d.printline("",underline=1)
        d.printline("Enter totals into till using")
        d.printline("management menu option 1,3.")

def print_sessiontotals(s):
    """
    Print a session totals report given a Session object.

    """
    td.s.add(s)
    depts=s.dept_totals
    paytotals=dict(s.payment_totals)
    payments=dict([(x.paytype,x) for x in s.actual_totals])
    paytypes=set(list(paytotals.keys())+list(payments.keys()))
    with driver as d:
        d.printline("\t%s"%tillconfig.pubname,emph=1)
        d.printline("\tSession %d"%s.id,colour=1)
        d.printline("\t%s"%ui.formatdate(s.date),colour=1)
        d.printline("Started %s"%ui.formattime(s.starttime))
        if s.endtime is None:
            d.printline("Session still in progress")
            d.printline("Printed %s"%ui.formattime(now()))
        else:
            d.printline("  Ended %s"%ui.formattime(s.endtime))
        d.printline("Till total:\t\tActual total:")
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
            d.printline("%s: %s\t\t%s"%(desc,tt,at))
        if len(paytypes)>1:
            tt=tillconfig.fc(ttt)
            if att>Decimal("0.00"):
                at=tillconfig.fc(att)
            else:
                at=""
            d.printline("Total: %s\t\t%s"%(tt,at),colour=1,emph=1)
        d.printline()
        dt=Decimal("0.00")
        for dept,total in depts:
            d.printline("%2d %s\t\t%s"%(dept.id,dept.description,
                                        tillconfig.fc(total)))
            dt=dt+total
        d.printline("\t\tTotal: %s"%tillconfig.fc(dt),colour=1,emph=1)
        d.printline()
        d.printline("\tPrinted %s"%ui.formattime(now()))

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
    with driver as dr:
        dr.printline("\t%s"%tillconfig.pubname,emph=1)
        dr.printline("\tDelivery %d"%d.id,colour=1)
        dr.printline("Supplier: %s"%d.supplier.name)
        dr.printline("Date: %s"%ui.formatdate(d.date))
        dr.printline("Delivery note: %s"%d.docnumber)
        if not d.checked:
            dr.printline("Details not yet confirmed -")
            dr.printline("may still be edited.")
        dr.printline()
        for s in d.items:
            dr.printline("Stock number %d"%s.id,colour=1)
            dr.printline(s.stocktype.format(maxw=dr.checkwidth))
            dr.printline("%s cost %s"%(
                    s.stockunit.name,tillconfig.fc(s.costprice)))
            dr.printline("sale %s BB %s"%(
                    tillconfig.fc(s.stocktype.saleprice),ui.formatdate(s.bestbefore)))
            dr.printline()
        dr.printline("\tEnd of list")

def print_stocklist(sl,title="Stock List"):
    with driver as d:
        d.printline("\t%s"%tillconfig.pubname,emph=1)
        d.printline("\t%s"%title,colour=1)
        d.printline("\t Printed %s"%ui.formattime(now()))
        d.printline()
        for s in sl:
            td.s.add(s)
            d.printline("Stock number %d"%s.id,colour=1)
            d.printline(s.stocktype.format(maxw=d.checkwidth))
            d.printline("%s cost %s"%(
                s.stockunit_id,tillconfig.fc(s.costprice)))
            d.printline("sale %s BB %s"%(
                tillconfig.fc(s.stocktype.saleprice),ui.formatdate(s.bestbefore)))
            d.printline()
        d.printline("\tEnd of list")

def print_restock_list(rl):
    """
    Print a list of (stockline,stockmovement) tuples.
    A stockmovement tuple is (stockitem,fetchqty,newdisplayqty,qtyremain).

    We can't assume that any of these objects are in the current
    session.

    """
    with driver as d:
        d.printline("\t%s"%tillconfig.pubname,emph=1)
        d.printline("\tRe-stock list")
        d.printline("\tPrinted %s"%ui.formattime(now()))
        d.printline()
        for sl,sm in rl:
            td.s.add(sl)
            d.printline("%s:"%sl.name)
            d.printline("%d/%d displayed"%(sl.ondisplay,sl.capacity))
            for item,move,newdisplayqty,stockqty_after_move in sm:
                td.s.add(item)
                if move>0:
                    d.printline(" %d from item %d leaving %d"%(
                        move,item.id,stockqty_after_move))
                if move<0:
                    d.printline(" %d to item %d making %d"%(
                        -move,item.id,stockqty_after_move),colour=1)
        d.printline()
        d.printline("\tEnd of list")

def kickout():
    o=driver.offline()
    if o:
        ui.infopopup(["Could not kick out the cash drawer: {}".format(o)],
                     title="Printer offline")
        return
    with driver as d:
        d.kickout()
