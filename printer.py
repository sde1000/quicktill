# -*- coding: iso-8859-1 -*-
import string,td,time,ui

dev="/dev/lp0"
# Characters per line with fonts 0 and 1
cpl=(25,30)

def l2s(l):
    return string.join([chr(x) for x in l],"")

def lr(l,r,w):
    w=w-len(l)-len(r)
    return "%s%s%s\n"%(l,' '*w,r)

def r(r,w):
    return "%s%s\n"%(" "*(w-len(r)),r)

# Some handy control sequences
reset=l2s([27,64,27,116,16])
pulse=l2s([27,ord('p'),0,50,50])
underline=(l2s([27,45,0]),l2s([27,45,1]),l2s([27,45,2]))
emph=(l2s([27,69,0]),l2s([27,69,1]))
colour=(l2s([27,114,0]),l2s([27,114,1]))
font=(l2s([27,77,0]),l2s([27,77,1]))
left=l2s([27,97,0])
center=l2s([27,97,1])
right=l2s([27,97,2])
ff=l2s([27,100,7])

def print_receipt(trans):
    f=file(dev,'w')
    (lines,payments)=td.trans_getlines(trans)
    (linestotal,paymentstotal)=td.trans_balance(trans)
    w=cpl[1]
    f.write(reset)
    f.write(center)
    f.write(font[1])
    f.write(emph[1]+"The Coalheavers Arms\n"+emph[0])
    f.write(colour[1]+"5 Park Street, Peterborough\n"+colour[0])
    f.write("Tel. 01733 565664\n\n")
    f.write(left)
    for i in lines:
        (trans,items,amount,dept,deptstr,stockref,
         transcode)=td.trans_getline(i)
        if stockref is not None:
            (qty,removecode,stockid,manufacturer,name,shortname,abv,
             unitname)=td.stock_fetchline(stockref)
            qty=qty/items
            if qty==1.0:
                qtys=""
            elif qty==0.5:
                qtys="half "
            else:
                qtys="%.1f "%qty
            ss="%s %s%s"%(shortname,qtys,unitname)
            if len(ss)>w:
                ss=shortname
            if len(ss)>w:
                ss=ss[:w]
        else:
            ss=deptstr
        if items==1:
            astr="£%0.2f"%amount
        else:
            astr="%d @ £%0.2f = £%0.2f"%(items,amount,items*amount)
        if len(ss)+len(astr)>w:
            f.write("%s\n"%ss)
            f.write(r(astr,w))
        else:
            f.write("%s%s%s\n"%(ss," "*(w-len(ss)-len(astr)),astr))
    st="Subtotal £%0.2f"%linestotal
    f.write(colour[1]+emph[1])
    f.write(r(st,w))
    f.write(colour[0]+emph[0])
    for i in payments:
        if i[0]>0.0:
            ps="Cash £%0.2f"%i[0]
        else:
            ps="Change £%0.2f"%i[0]
        f.write(r(ps,w))
    f.write("\n")
    net=linestotal/1.175
    vat=linestotal-net
    f.write(r("Net total: £%0.2f"%net,w))
    f.write(r("VAT @ 17.5%%: £%0.2f"%vat,w))
    f.write(r("Receipt total: £%0.2f"%linestotal,w))
    f.write(center)
    f.write("\nReceipt number %d\n"%trans)
    date=td.trans_date(trans)
    if date is not None: f.write("%s\n"%
            time.strftime("%Y/%m/%d %H:%M",td.trans_date(trans)))
    f.write("\nIndividual Pubs Limited\n")
    f.write("Unit 111, Norman Ind. Estate\n")
    f.write("Cambridge Road, Milton\nCambridge CB4 6AT\n")
    f.write("VAT reg. no. 783 9983 50\n\n")
    f.write(left)
    f.write(ff)
    f.close()
            
def print_sessioncountup(session):
    (start,end)=td.session_startend(session)
    f=file(dev,'w')
    f.write(reset+emph[1]+center)
    f.write("Coalheavers Arms\n")
    f.write(colour[1])
    f.write("Session %d\n"%session)
    f.write(left+colour[0]+emph[0])
    f.write("Started %s\n"%time.strftime("%Y/%m/%d %H:%M:%S",start))
    f.write("  Ended %s\n"%time.strftime("%Y/%m/%d %H:%M:%S",end))
    tot=td.session_transtotal(session)
    if tot is None: tot=0.0
    f.write("\nAmount registered £%0.2f\n\n"%tot)
    f.write('\n\n'.join(["   %s"%x for x
                         in ("    50","    20","    10",
                             "     5","     2","     1",
                             "  0.50","  0.20","  0.10",
                             "  0.05","  0.02","  0.01",
                             "  Bags","  Misc","-Float")]))
    f.write("\n"+underline[1]+(" "*cpl[1])+underline[0]+"\n")
    f.write(colour[1]+emph[1]+"Total\n"+colour[0]+emph[0])
    f.write("\n"+underline[1]+(" "*cpl[1])+underline[0]+"\n")
    f.write("Enter total into till using\n")
    f.write("management menu option 3.\n")
    f.write(ff)
    f.close()

def print_sessiontotals(session):
    w=cpl[1]
    depts=td.session_depttotals(session)
    paytotal=td.session_transtotal(session)
    if paytotal is None: paytotal=0.0
    (start,end)=td.session_startend(session)
    payments=td.session_actualtotals(session)
    f=file(dev,'w')
    f.write(reset+emph[1]+center)
    f.write("Coalheavers Arms\n")
    f.write(colour[1])
    f.write("Session %d\n"%session)
    f.write(left+colour[0]+emph[0])
    f.write("Started %s\n"%time.strftime("%Y/%m/%d %H:%M:%S",start))
    if end is None:
        f.write("Session still in progress\nPrinted %s\n"%
                time.strftime("%Y/%m/%d %H:%M:%S"))
    else:
        f.write("  Ended %s\n"%time.strftime("%Y/%m/%d %H:%M:%S",end))
        if len(payments)==0:
            f.write("The actual amount taken has\nnot yet been recorded.\n")
        else:
            pt=0.0
            f.write("Actual takings:\n")
            for i in payments:
                f.write("%s: £%0.2f\n"%(i[0],i[1]))
                pt=pt+i[1]
            if len(payments)>1:
                f.write(colour[1]+emph[1]+("Total: £%0.2f\n"%pt)+emph[0]+
                        colour[0])
    dt=0.0
    f.write("\n")
    for i in depts:
        f.write(lr("%2d %s"%(i[0],i[1]),"£%0.2f"%i[2],w))
        dt=dt+i[2]
    f.write(colour[1]+emph[1]+r("Total: £%0.2f"%dt,w)+colour[0]+emph[0])
    f.write("\nPrinted %s\n"%time.strftime("%Y/%m/%d %H:%M:%S"))
    f.write(ff)
    f.close()

def print_delivery(delivery):
    (id,supplier,docnumber,date,checked,supname)=td.delivery_get(number=delivery)[0]
    (name,tel,email)=td.supplier_fetch(supplier)
    items=td.delivery_items(delivery)
    f=file(dev,'w')
    f.write(reset+emph[1]+center)
    f.write("Coalheavers Arms\n")
    f.write(colour[1])
    f.write("Delivery %d\n"%delivery)
    f.write(left+colour[0]+emph[0])
    f.write("Supplier: %s\n"%name)
    f.write("Date: %s\n"%ui.formatdate(date))
    f.write("Delivery note: %s\n"%docnumber)
    if not checked: f.write("Details not yet confirmed - \nmay still be edited.\n")
    f.write("\n")
    for i in items:
        sd=td.stock_info(i)
        f.write(colour[1]+("Stock number %d\n"%i)+colour[0])
        f.write("%s\n"%stock.format_stock(sd,maxw=cpl[1]))
        f.write("%s cost £%0.2f sale £%0.2f\nBest Before %s\n"%(
            sd['stockunit'],sd['costprice'],sd['saleprice'],
            ui.formatdate(sd['bestbefore'])))
        f.write("\n")
    f.write("End of list\n")
    f.write(ff)
    f.close()
        
def kickout():
    f=file(dev,'w')
    f.write(pulse)
    f.close()

if __name__=='__main__':
    kickout()
