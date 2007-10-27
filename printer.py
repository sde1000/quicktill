import string,td,time,ui,stock,tillconfig,sets

driver=None

dateformat="%Y/%m/%d"
timeformat="%Y/%m/%d %H:%M:%S"

def print_receipt(trans):
    transopen=False
    (lines,payments)=td.trans_getlines(trans)
    (linestotal,paymentstotal)=td.trans_balance(trans)
    if linestotal!=paymentstotal: transopen=True
    driver.start()
    driver.setdefattr(font=1)
    driver.printline("\t%s"%tillconfig.pubname,emph=1)
    for i in tillconfig.pubaddr:
        driver.printline("\t%s"%i,colour=1)
    driver.printline("\tTel. %s"%tillconfig.pubnumber)
    driver.printline("")
    for i in lines:
        (trans,items,amount,dept,deptstr,stockref,
         transcode)=td.trans_getline(i)
        if stockref is not None:
            (qty,removecode,stockid,manufacturer,name,shortname,abv,
             unitname)=td.stock_fetchline(stockref)
            qty=qty/items
            qtys=tillconfig.qtystring(qty,unitname)
            ss="%s %s"%(shortname,qtys)
        else:
            ss=deptstr
        if items==1:
            astr=tillconfig.fc(amount)
        else:
            astr="%d @ %s = %s"%(items,tillconfig.fc(amount),tillconfig.fc(items*amount))
        if not driver.printline("%s\t\t%s"%(ss,astr),allowwrap=False):
            driver.printline(ss)
            driver.printline("\t\t%s"%astr)
    driver.printline("\t\tSubtotal %s"%tillconfig.fc(linestotal),
                     colour=1,emph=1)
    for amount,paytype,description,ref in payments:
        if paytype=='CASH':
            driver.printline("\t\t%s %s"%(ref,tillconfig.fc(amount)))
        else:
            if ref is None:
                driver.printline("\t\t%s %s"%(description,tillconfig.fc(amount)))
            else:
                driver.printline("\t\t%s %s %s"%(
                    description,ref,tillconfig.fc(amount)))
    driver.printline("")
    if transopen:
        driver.printline("\tThis is not a VAT receipt",colour=1,emph=1)
        driver.printline("\tTransaction number %d"%trans)
    else:
        net=linestotal/(tillconfig.vatrate+1.0)
        vat=linestotal-net
        driver.printline("\t\tNet total: %s"%tillconfig.fc(net))
        driver.printline("\t\tVAT @ %0.1f%%: %s"%(tillconfig.vatrate*100.0,
                                                  tillconfig.fc(vat)))
        driver.printline("\t\tReceipt total: %s"%tillconfig.fc(linestotal))
        driver.printline("")
        driver.printline("\tReceipt number %d"%trans)
    driver.printline("\t%s"%time.strftime(dateformat,td.trans_date(trans)))
    driver.printline("")
    for i in tillconfig.companyaddr:
        driver.printline("\t%s"%i)
    driver.printline()
    driver.printline("\tVAT reg. no. %s"%tillconfig.vatno)
    driver.end()

def print_sessioncountup(session):
    (start,end,accdate)=td.session_dates(session)
    driver.start()
    driver.setdefattr(font=1)
    driver.printline("\t%s"%tillconfig.pubname,emph=1)
    driver.printline("\tSession %d"%session,colour=1)
    driver.printline("\t%s"%time.strftime(dateformat,accdate),colour=1)
    driver.printline("Started %s"%time.strftime(timeformat,start))
    driver.printline("  Ended %s"%time.strftime(timeformat,end))
    driver.printline()
    tots=td.session_paytotals(session)
    driver.printline("Amounts registered:")
    for i in tots:
        driver.printline("%s: %s"%(tots[i][0],tillconfig.fc(tots[i][1])))
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
    if 'CASH' in tots: del tots['CASH']
    for i in tots:
        driver.printline("%s Total"%tots[i][0],colour=1,emph=1)
        driver.printline()
        driver.printline(underline=1)
    driver.printline("Enter totals into till using")
    driver.printline("management menu option 3.")
    driver.end()

def print_sessiontotals(session):
    (start,end,accdate)=td.session_dates(session)
    depts=td.session_depttotals(session)
    paytotals=td.session_paytotals(session)
    payments=td.session_actualtotals(session)
    paytypes=sets.Set(paytotals.keys()+payments.keys())
    driver.start()
    driver.setdefattr(font=1)
    driver.printline("\t%s"%tillconfig.pubname,emph=1)
    driver.printline("\tSession %d"%session,colour=1)
    driver.printline("\t%s"%time.strftime(dateformat,accdate),colour=1)
    driver.printline("Started %s"%time.strftime(timeformat,start))
    if end is None:
        driver.printline("Session still in progress")
        driver.printline("Printed %s"%
                         time.strftime(timeformat))
    else:
        driver.printline("  Ended %s"%time.strftime(timeformat,end))
    driver.printline("Till total:\t\tActual total:")
    ttt=0.0
    att=0.0
    for i in paytypes:
        desc=""
        if i in paytotals:
            desc=paytotals[i][0]
            tt=tillconfig.fc(paytotals[i][1])
            ttt=ttt+paytotals[i][1]
        else:
            tt=""
        if i in payments:
            desc=payments[i][0]
            at=tillconfig.fc(payments[i][1])
            att=att+payments[i][1]
        else:
            at=""
        driver.printline("%s: %s\t\t%s"%(desc,tt,at))
    if len(paytypes)>1:
        tt=tillconfig.fc(ttt)
        if att>0.0:
            at=tillconfig.fc(att)
        else:
            at=""
        driver.printline("Total: %s\t\t%s"%(tt,at),colour=1,emph=1)
    driver.printline()
    dt=0.0
    for i in depts:
        driver.printline("%2d %s\t\t%s"%(i[0],i[1],tillconfig.fc(i[2])))
        dt=dt+i[2]
    driver.printline("\t\tTotal: %s"%tillconfig.fc(dt),colour=1,emph=1)
    driver.printline()
    driver.printline("\tPrinted %s"%time.strftime(timeformat))
    driver.end()

def print_delivery(delivery):
    (id,supplier,docnumber,date,checked,supname)=td.delivery_get(number=delivery)[0]
    (name,tel,email)=td.supplier_fetch(supplier)
    items=td.delivery_items(delivery)
    driver.start()
    driver.setdefattr(font=1)
    driver.printline("\t%s"%tillconfig.pubname,emph=1)
    driver.printline("\tDelivery %d"%delivery,colour=1)
    driver.printline("Supplier: %s"%name)
    driver.printline("Date: %s"%ui.formatdate(date))
    driver.printline("Delivery note: %s\n"%docnumber)
    if not checked:
        driver.printline("Details not yet confirmed -")
        driver.printline("may still be edited.")
    driver.printline()
    items_sdl=td.stock_info(items)
    for sd in items_sdl:
        driver.printline("Stock number %d"%sd['stockid'],colour=1)
        driver.printline(stock.format_stock(sd,maxw=driver.width()))
        driver.printline("%s cost %s"%(
            sd['stockunit'],tillconfig.fc(sd['costprice'])))
        driver.printline("sale %s BB %s"%(
            tillconfig.fc(sd['saleprice']),ui.formatdate(sd['bestbefore'])))
        driver.printline()
    driver.printline("\tEnd of list")
    driver.end()

def print_stocklist(sl,title="Stock List"):
    driver.start()
    driver.setdefattr(font=1)
    driver.printline("\t%s"%tillconfig.pubname,emph=1)
    driver.printline("\t%s"%title,colour=1)
    driver.printline("\t Printed %s"%time.strftime(timeformat))
    driver.printline()
    for sd in sl:
        driver.printline("Stock number %d"%sd['stockid'],colour=1)
        driver.printline(stock.format_stock(sd,maxw=driver.width()))
        driver.printline("%s cost %s"%(
            sd['stockunit'],tillconfig.fc(sd['costprice'])))
        driver.printline("sale %s BB %s"%(
            tillconfig.fc(sd['saleprice']),ui.formatdate(sd['bestbefore'])))
        driver.printline()
    driver.printline("\tEnd of list")
    driver.end()

def print_restock_list(rl):
    driver.start()
    driver.setdefattr(font=1)
    driver.printline("\t%s"%tillconfig.pubname,emph=1)
    driver.printline("\tRe-stock list")
    driver.printline("\tPrinted %s"%time.strftime(timeformat))
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

driver=None

def kickout():
    pass

