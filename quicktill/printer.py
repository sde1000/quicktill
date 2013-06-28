import string,td,time,ui,stock,tillconfig

driver=None
labeldriver=None

def print_receipt(trans):
    transopen=False
    (lines,payments)=td.trans_getlines(trans)
    if len(lines)==0: return
    (linestotal,paymentstotal)=td.trans_balance(trans)
    if linestotal!=paymentstotal: transopen=True
    driver.start()
    driver.setdefattr(font=1)
    driver.printline("\t%s"%tillconfig.pubname,emph=1)
    for i in tillconfig.pubaddr:
        driver.printline("\t%s"%i,colour=1)
    driver.printline("\tTel. %s"%tillconfig.pubnumber)
    driver.printline()
    multiband=td.trans_multiband(trans)
    date=td.trans_date(trans)
    bandtotals={}
    for i in lines:
        tli=td.trans_getline(i)
        (transx,items,amount,dept,deptstr,stockref,
         transcode,transtime,text,vatband)=tli
        bandtotals[vatband]=bandtotals.get(vatband,0.0)+(items*amount)
        left,right=stock.format_transline(tli)
        if multiband and not transopen:
            driver.printline("%s\t\t%s %s"%(left,right,vatband))
        else:
            driver.printline("%s\t\t%s"%(left,right))
    totalpad="  " if multiband else ""
    driver.printline("\t\tSubtotal %s%s"%(tillconfig.fc(linestotal),totalpad),
                     colour=1,emph=1)
    for amount,paytype,description,ref in payments:
        if paytype=='CASH':
            driver.printline("\t\t%s %s%s"%(ref,tillconfig.fc(amount),totalpad))
        else:
            if ref is None:
                driver.printline("\t\t%s %s%s"%(description,
                                                tillconfig.fc(amount),
                                                totalpad))
            else:
                driver.printline("\t\t%s %s %s%s"%(
                    description,ref,tillconfig.fc(amount),totalpad))
    driver.printline("")
    if transopen:
        driver.printline("\tThis is not a VAT receipt",colour=1,emph=1)
        driver.printline("\tTransaction number %d"%trans)
    else:
        # We have a list of VAT bands; we need to look up rate and
        # business information for each of them.  Once we have the
        # list of businesses, we can print out a section per business.
        # In each section, show the business name and address, VAT
        # number, and then for each VAT band the net amount, VAT and
        # total.
        businesses={} # Keys are business IDs, values are (band,rate) tuples
        for i in bandtotals.keys():
            rate,business=td.vat_info(i,date)
            businesses.setdefault(business,[]).append((i,rate))
        for i in businesses.keys():
            name,abbrev,address,vatno=td.business_info(i)
            bands=businesses[i]
            # Print the business info
            driver.printline("\t%s"%name)
            for l in address.split('\\n'):
                driver.printline("\t%s"%l)
            driver.printline()
            driver.printline("VAT reg no. %s"%vatno)
            for band,rate in bands:
                # Print the band, amount ex VAT, amount inc VAT, gross
                gross=bandtotals[band]
                net=gross/((rate/100.0)+1.0)
                vat=gross-net
                driver.printline("%s: %s net, %s VAT @ %0.1f%%\t\tTotal %s"%(
                        band,tillconfig.fc(net),tillconfig.fc(vat),rate,
                        tillconfig.fc(gross)))
            driver.printline("")
        driver.printline("\tReceipt number %d"%trans)
    driver.printline("\t%s"%ui.formatdate(date))
    driver.end()

def print_sessioncountup(session):
    (start,end,accdate)=td.session_dates(session)
    driver.start()
    driver.setdefattr(font=1)
    driver.printline("\t%s"%tillconfig.pubname,emph=1)
    driver.printline("\tSession %d"%session,colour=1)
    driver.printline("\t%s"%ui.formatdate(accdate),colour=1)
    driver.printline("Started %s"%ui.formattime(start))
    driver.printline("  Ended %s"%ui.formattime(end))
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
    driver.printline("management menu option 1,3.")
    driver.end()

def print_sessiontotals(session):
    (start,end,accdate)=td.session_dates(session)
    depts=td.session_depttotals(session)
    paytotals=td.session_paytotals(session)
    payments=td.session_actualtotals(session)
    paytypes=set(paytotals.keys()+payments.keys())
    driver.start()
    driver.setdefattr(font=1)
    driver.printline("\t%s"%tillconfig.pubname,emph=1)
    driver.printline("\tSession %d"%session,colour=1)
    driver.printline("\t%s"%ui.formatdate(accdate),colour=1)
    driver.printline("Started %s"%ui.formattime(start))
    if end is None:
        driver.printline("Session still in progress")
        driver.printline("Printed %s"%ui.formattime(ui.now()))
    else:
        driver.printline("  Ended %s"%ui.formattime(end))
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
    driver.printline("\tPrinted %s"%ui.formattime(ui.now()))
    driver.end()

def label_print_delivery(delivery):
    items=td.delivery_items(delivery)
    stocklabel_print(items)

def stocklabel_print(sl):
    """Print stock labels for a list of stock numbers.

    """
    items_sdl=td.stock_info(sl)
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
        f.drawCentredString(width/2,y,stock.format_stock(d,fits))
        y=y-pitch
        f.drawCentredString(width/2,y,d['suppliername'])
        y=y-pitch
        f.drawCentredString(width/2,y,ui.formatdate(d['deliverydate']))
        y=y-pitch
        f.drawCentredString(width/2,y,d['sunitname'])
        if tillconfig.checkdigit_print:
            y=y-pitch
            f.drawCentredString(width/2,y,"Check digits: %s"%(
                    stock.checkdigits(d['stockid'])))
        f.setFont(fontname,y-margin)
        f.drawCentredString(width/2,margin,str(d['stockid']))
    for sd in items_sdl:
        labeldriver.addlabel(stock_label,sd)
    labeldriver.end()

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
    driver.printline("Delivery note: %s"%docnumber)
    if not checked:
        driver.printline("Details not yet confirmed -")
        driver.printline("may still be edited.")
    driver.printline()
    items_sdl=td.stock_info(items)
    for sd in items_sdl:
        driver.printline("Stock number %d"%sd['stockid'],colour=1)
        driver.printline(stock.format_stock(sd,maxw=driver.checkwidth))
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
    driver.setdefattr(font=1)
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
    driver.setdefattr(font=1)
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
    driver.setdefattr(font=1)
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

