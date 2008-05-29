"""Implements the 'Manage Stock' menu."""

import ui,td,keyboard,curses,curses.ascii,time,printer
import stock,delivery,department

import logging
log=logging.getLogger()

def newdelivery():
    # New deliveries need a supplier to be chosen before they can be edited.
    log.info("New delivery")
    delivery.selectsupplier(delivery.create_and_edit_delivery,allow_new=True)

def editdelivery():
    log.info("Edit delivery")
    delivery.deliverylist(delivery.delivery,unchecked_only=True)

def displaydelivery():
    log.info("Display delivery")
    delivery.deliverylist(delivery.delivery,checked_only=True)

def finish_reason(sn,reason):
    td.stock_finish(sn,reason)
    log.info("Stock: finished item %d reason %s"%(sn,reason))
    ui.infopopup(["Stock item %d is now finished."%sn],dismiss=keyboard.K_CASH,
                  title="Stock Finished",colour=ui.colour_info)

def finish_item(sn):
    sd=td.stock_info([sn])[0]
    fl=[(x[1],finish_reason,(sn,x[0])) for x in td.stockfinish_list()]
    ui.menu(fl,blurb="Please indicate why you are finishing stock number %d:"%
            sn,title="Finish Stock",w=60)

def finishstock(dept=None):
    log.info("Finish stock")
    sl=td.stock_search(dept=dept)
    sinfo=td.stock_info(sl)
    lines=ui.table([("%d"%x['stockid'],stock.format_stock(x))
                    for x in sinfo]).format(' r l ')
    sl=[(x,finish_item,(y['stockid'],)) for x,y in zip(lines,sinfo)]
    ui.menu(sl,title="Finish stock not currently on sale",
            blurb="Choose a stock item to finish.")

def format_stockmenuline(sd):
    return ("%d"%sd['stockid'],
            stock.format_stock(sd,maxw=40),
            "%.0f %ss"%(sd['remaining'],sd['unitname']))

def print_stocklist_menu(sinfo,title):
    if printer.labeldriver is not None:
        menu=[
            (keyboard.K_ONE,"Print list",
             printer.print_stocklist,(sinfo,title)),
            (keyboard.K_TWO,"Print sticky labels",
             printer.stocklabel_print,([x['stockid'] for x in sinfo],)),
            ]
        ui.keymenu(menu,"Stock print options",colour=ui.colour_confirm)
    else:
        printer.print_stocklist(sinfo,title)

def stockdetail(sinfo):
    if len(sinfo)==1:
        return stock.stockinfo_popup(sinfo[0]['stockid'])
    lines=ui.table([format_stockmenuline(x) for x in sinfo]).format(' r l l ')
    sl=[(x,stock.stockinfo_popup,(y['stockid'],))
        for x,y in zip(lines,sinfo)]
    print_title="Stock Check"
    ui.menu(sl,title="Stock Detail",blurb="Select a stock item and press "
            "Cash/Enter for more information.",
            dismiss_on_select=False,keymap={
            keyboard.K_PRINT: (print_stocklist_menu,(sinfo,print_title),False)},
            colour=ui.colour_confirm)

def stockcheck(dept=None):
    # Build a list of all not-finished stock items.
    log.info("Stock check")
    sl=td.stock_search(exclude_stock_on_sale=False,dept=dept)
    sinfo=td.stock_info(sl)
    # Split into groups by stocktype
    st={}
    for i in sinfo:
        st.setdefault(i['stocktype'],[]).append(i)
    # Convert to a list
    st=[x for x in st.values()]
    # We might want to sort the list at this point... sorting by ascending
    # amount remaining will put the things that are closest to running out
    # near the start - handy!
    remfunc=lambda a:reduce(lambda x,y:x+y,[x['remaining'] for x in a])
    cmpfunc=lambda a,b:(0,-1)[remfunc(a)<remfunc(b)]
    st.sort(cmpfunc)
    # We want to show name, remaining, items in each line
    # and when a line is selected we want to pop up the list of individual
    # items.
    lines=[]
    details=[]
    for i in st:
        name=stock.format_stock(i[0],maxw=40)
        remaining=reduce(lambda x,y:x+y,[x['remaining'] for x in i])
        items=len(i)
        unit=i[0]['unitname']
        lines.append((name,"%.0f %ss"%(remaining,unit),"(%d item%s)"%(
            items,("s","")[items==1])))
        details.append(i)
    lines=ui.table(lines).format(' l l l ')
    sl=[(x,stockdetail,(y,)) for x,y in zip(lines,details)]
    title="Stock Check" if dept is None else "Stock Check department %d"%dept
    ui.menu(sl,title=title,blurb="Select a stock type and press "
            "Cash/Enter for details on individual items.",
            dismiss_on_select=False,keymap={
            keyboard.K_PRINT: (print_stocklist_menu,(sinfo,title),False)})

def stockhistory(dept=None):
    # Build a list of all finished stock items.  Things we want to show:
    log.info("Stock history")
    sl=td.stock_search(finished_stock_only=True,dept=dept)
    sl.reverse()
    sinfo=td.stock_info(sl)
    lines=ui.table([format_stockmenuline(x) for x in sinfo]).format(' r l l ')
    sl=[(x,stock.stockinfo_popup,(y['stockid'],))
        for x,y in zip(lines,sinfo)]
    title=("Stock History" if dept is None
           else "Stock History department %d"%dept)
    ui.menu(sl,title=title,blurb="Select a stock item and press "
            "Cash/Enter for more information.  The number of units remaining "
            "when the stock was finished is shown.",dismiss_on_select=False,
            keymap={
            keyboard.K_PRINT: (printer.print_stocklist,(sinfo,title),False)})

def updatesupplier():
    log.info("Update supplier")
    delivery.selectsupplier(
        lambda x:delivery.editsupplier(lambda a:None,x),allow_new=False)

class stocklevelcheck(ui.dismisspopup):
    def __init__(self):
        depts=td.department_list()
        self.deptlist=[x[0] for x in depts]
        ui.dismisspopup.__init__(self,10,50,title="Stock level check",
                                 colour=ui.colour_input)
        self.addstr(2,2,'Department:')
        self.deptfield=ui.listfield(2,14,20,self.deptlist,d=dict(depts),
                                    keymap={
                keyboard.K_CLEAR: (self.dismiss,None)})
        self.addstr(3,2,'    Period:')
        self.pfield=ui.editfield(3,14,3,validate=ui.validate_int,keymap={
                keyboard.K_CASH: (self.enter,None)})
        self.addstr(3,18,'weeks')
        self.addstr(5,2,'The period should usually be one-and-a-half')
        self.addstr(6,2,'times the usual time between deliveries.  For')
        self.addstr(7,2,'weekly deliveries use 2; for fortnightly')
        self.addstr(8,2,'deliveries use 3.')
        ui.map_fieldlist([self.deptfield,self.pfield])
        self.deptfield.focus()
    def enter(self):
        if self.pfield=='':
            ui.infopopup(["You must enter a period."],title="Error")
            return
        weeks=int(self.pfield.f)
        dept=(None if self.deptfield.f is None
              else self.deptlist[self.deptfield.f])
        self.dismiss()
        r=td.stocklevel_check(dept,'%d weeks'%weeks)
        r=[(name,str(sold),str(understock)) for (st,name,sold,understock) in r]
        r=[('Name','Sold','Buy')]+r
        lines=ui.table(r).format(' l r  r ')
        header=["Do not order any stock if the 'Buy' amount",
               "is negative!",""]
        ui.linepopup(header+lines,title="Stock level check - %d weeks"%weeks,
                     colour=ui.colour_info,headerlines=len(header)+1,
                     dismiss=keyboard.K_CASH)

def popup():
    "Pop up the stock management menu."
    log.info("Stock management popup")
    menu=[
        (keyboard.K_ONE,"Record a new delivery",newdelivery,None),
        (keyboard.K_TWO,"Edit an existing (unconfirmed) delivery",
         editdelivery,None),
        (keyboard.K_THREE,"Display an old (confirmed) delivery",
         displaydelivery,None),
        (keyboard.K_FOUR,"Finish stock not currently on sale",
         department.menu,(finishstock,"Finish Stock",False)),
        (keyboard.K_FIVE,"Stock check (unfinished stock)",
         department.menu,(stockcheck,"Stock Check",True)),
        (keyboard.K_SIX,"Stock history (finished stock)",
         department.menu,(stockhistory,"Stock History",True)),
        (keyboard.K_SEVEN,"Update supplier details",updatesupplier,None),
        (keyboard.K_EIGHT,"Annotate a stock item",stock.annotate,None),
        (keyboard.K_NINE,"Check stock levels",stocklevelcheck,None),
#        (keyboard.K_ZEROZERO,"Correct a stock type record",selectstocktype,
#         (lambda x:selectstocktype(lambda:None,default=x,mode=2),)),
        ]
    ui.keymenu(menu,"Stock Management options")
