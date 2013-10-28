import logging
from . import keyboard,ui,td,tillconfig,printer
from .models import Department,StockLine,KeyboardBinding
from .models import StockType,StockLineTypeLog
log=logging.getLogger(__name__)

def calculate_sale(stocklineid,items):
    """
    Given a line, work out a plan to remove a number of items from
    display.  They may be sold, wasted, etc.

    Returns (list of (stockitem,items) pairs, the number of items that
    could not be allocated, remaining stock (ondisplay,instock)).

    """
    stockline=td.s.query(StockLine).get(stocklineid)
    stocklist=stockline.stockonsale
    if len(stocklist)==0:
        return ([],items,(0,0))
    # Iterate over the stock items attached to the line and produce a
    # list of (stockid,items) pairs if possible; otherwise produce an
    # error message If the stockline has no capacity mentioned
    # ("capacity is None") then bypass this and just sell the
    # appropriate number of items from the only stockitem in the list!
    if stockline.capacity is None:
        return ([(stocklist[0],items)],0,None)
    unallocated=items
    leftondisplay=0
    totalinstock=0
    sell=[]
    # Iterate through the StockItem objects for this stock line

    # XXX this can probably be stated more simply now that StockOnSale
    # and StockItem have been merged, and StockItem has lots of nice
    # informative properties!
    for item in stocklist:
        ondisplay=item.ondisplay
        sellqty=min(unallocated,ondisplay)
        log.debug("ondisplay=%d, sellqty=%d"%(ondisplay,sellqty))
        unallocated=unallocated-sellqty
        leftondisplay=leftondisplay+ondisplay-sellqty
        totalinstock=totalinstock+item.remaining-sellqty
        if sellqty>0:
            sell.append((item,sellqty))
    return (sell,unallocated,(leftondisplay,totalinstock-leftondisplay))

def restock_list(stockline_list):
    # Print out list of things to fetch and put on display
    # Display prompt: have you fetched them all?
    # If yes, update records.  If no, don't.
    sl=[]
    for i in stockline_list:
        td.s.add(i)
        r=i.calculate_restock()
        if len(r)>0: sl.append((i,r))
    if sl==[]:
        ui.infopopup(["There is no stock to be put on display."],
                     title="Stock movement")
        return
    printer.print_restock_list(sl)
    ui.infopopup([
        "The list of stock to be put on display has been printed.","",
        "Please choose one of the following options:","",
        "1. I have finished moving the stock on the printed list.",
        "2. I have not moved any stock and I have thrown the list away."],
                 title="Confirm stock movement",
                 keymap={keyboard.K_ONE:(finish_restock,(sl,),True),
                         keyboard.K_TWO:(abandon_restock,(sl,),True)},
                 colour=ui.colour_confirm,dismiss=None)

def abandon_restock(sl):
    ui.infopopup(["The stock movements in the list HAVE NOT been recorded."],
                 title="Stock movement abandoned")

def finish_restock(rsl):
    for stockline,stockmovement in rsl:
        td.s.add(stockline)
        for sos,move,newdisplayqty,instock_after_move in stockmovement:
            td.s.add(sos)
            sos.displayqty=newdisplayqty
    td.s.flush()
    ui.infopopup(["The till has recorded all the stock movements "
                  "in the list."],title="Stock movement confirmed",
                 colour=ui.colour_info,dismiss=keyboard.K_CASH)

def restock_item(stockline):
    return restock_list([stockline])

def restock_location():
    """Display a menu of locations, and then invoke restock_list for
    all stocklines in the selected location.

    """
    selectlocation(restock_list,title="Re-stock location",caponly=True)

def restock_all():
    """Invoke restock_list for all stocklines, sorted by location.

    """
    restock_list(td.s.query(StockLine).filter(StockLine.capacity!=None).all())

class stockline_associations(ui.listpopup):
    """
    A window showing the list of stocklines and their associated stock
    types.  Pressing Cancel on a line deletes the association.

    """
    def __init__(self,stocklines=None,
                 blurb="To create a new association, use the 'Use Stock' "
                 "button to assign stock to a line."):
        """
        If a list of stocklines is passed, restrict the editor to just
        those; otherwise list all of them.

        """
        stllist=td.s.query(StockLineTypeLog).\
            join(StockLineTypeLog.stockline).\
            join(StockLineTypeLog.stocktype).\
            order_by(StockLine.dept_id,StockLine.name,StockType.fullname)
        if stocklines:
            stllist=stllist.filter(StockLine.id.in_(stocklines))
        stllist=stllist.all()
        f=ui.tableformatter(' l l ')
        headerline=ui.tableline(f,["Stock line","Stock type"])
        lines=[ui.tableline(f,(stl.stockline.name,stl.stocktype.fullname),
                            userdata=stl)
               for stl in stllist]
        ui.listpopup.__init__(
            self,lines,title="Stockline / Stock type associations",
            header=["Press Cancel to delete an association.  "+blurb,
                    headerline])
    def keypress(self,k):
        if k==keyboard.K_CANCEL and self.s:
            line=self.s.dl.pop(self.s.cursor)
            self.s.redraw()
            td.s.add(line.userdata)
            td.s.delete(line.userdata)
            td.s.flush()
        else:
            ui.listpopup.keypress(self,k)

def auto_allocate(deliveryid=None,confirm=True):
    """
    Automatically allocate stock to stock lines.  If there's a potential
    clash (the same type of stock has been allocated to more than one
    stock line in the past) then enter a reduced version of the stockline
    associations dialogue and let them sort out the clash; then retry.

    """
    cl=td.stock_autoallocate_candidates(deliveryid)
    # Check for duplicate stockids
    seen={}
    duplines={}
    for item,line in cl:
        if item in seen:
            duplines[line.id]=item
            duplines[seen[item].id]=item
        seen[item]=line
    if duplines!={}:
        # Oops, there were duplicate stockids.  Dump the user into the
        # stockline associations editor to sort it out.
        stockline_associations(
            list(duplines.keys()),"The following stock line and stock type "
            "associations meant an item of stock could not be allocated "
            "unambiguously.  Delete associations from the list below "
            "until there is only one stock line per stock type, then "
            "press Clear and re-try the stock allocation using 'Use Stock' "
            "option 3.")
    else:
        if len(cl)>0:
            for item,line in cl:
                item.stockline=line
                item.displayqty=item.used
            td.s.flush()
            message=("The following stock items have been allocated to "
                     "display lines: %s."%(
                    ', '.join(["%d"%item.id for item,line in cl])))
            confirm=True
        else:
            message=("There was nothing available for automatic allocation.  "
                     "To allocate stock to a stock line manually, press the "
                     "'Use Stock' button, then the button for the stock line, "
                     "and choose option 2.")
        if confirm:
            ui.infopopup([message],
                         title="Auto-allocate confirmation",
                         colour=ui.colour_confirm,
                         dismiss=keyboard.K_CASH)

def return_stock(stockline):
    td.s.add(stockline)
    rsl=stockline.calculate_restock(target=0)
    if not rsl:
        ui.infopopup(["The till has no record of stock on display for "
                      "this line."],title="Remove stock")
        return
    restock=[(stockline,rsl)]
    printer.print_restock_list(restock)
    ui.infopopup([
        "The list of stock to be taken off display has been printed.",
        "","Press Cash/Enter to "
        "confirm that you've removed all the items on the list and "
        "allow the till to update its records.  Pressing Clear "
        "at this point will completely cancel the operation."],
                 title="Confirm stock movement",
                 keymap={keyboard.K_CASH:(finish_restock,(restock,),True)},
                 colour=ui.colour_confirm)

class create(ui.dismisspopup):
    def __init__(self):
        ui.dismisspopup.__init__(self,12,55,title="Create Stock Line",
                                 colour=ui.colour_input,
                                 dismiss=keyboard.K_CLEAR)
        depts=td.s.query(Department).order_by(Department.id).all()
        self.addstr(2,2,"    Stock line name:")
        self.addstr(3,2,"           Location:")
        self.addstr(4,2,"         Department:")
        self.addstr(5,2,"   Display capacity:")
        self.addstr(6,2,"Pull-through amount:")
        self.addstr(8,2,"Leave \"Display capacity\" blank unless you are")
        self.addstr(9,2,"creating a stockline for the fridge.")
        self.namefield=ui.editfield(2,23,30,keymap={
            keyboard.K_CLEAR: (self.dismiss,None)})
        self.locfield=ui.editfield(3,23,20)
        self.deptfield=ui.listfield(4,23,20,depts,d=lambda x:x.description)
        self.capacityfield=ui.editfield(5,23,5,validate=ui.validate_int)
        self.pullthrufield=ui.editfield(
            6,23,5,validate=ui.validate_float,keymap={
                keyboard.K_CASH: (self.enter,None)})
        ui.map_fieldlist([self.namefield,self.locfield,self.deptfield,
                          self.capacityfield,self.pullthrufield])
        self.namefield.focus()
    def enter(self):
        if (self.namefield.f=='' or
            self.locfield.f=='' or
            self.deptfield.f is None):
            ui.infopopup(["You must enter values in the first three fields."],
                         title="Error")
            return
        if self.capacityfield.f!='': cap=int(self.capacityfield.f)
        else: cap=None
        if self.pullthrufield.f!='': pullthru=float(self.pullthrufield.f)
        else: pullthru=None
        if pullthru is not None and cap is not None:
            ui.infopopup(["You may specify display capacity or quantity "
                          "to pull through, but not both."],title="Error")
            return
        sl=StockLine(name=self.namefield.f,
                     location=self.locfield.f,
                     department=self.deptfield.read(),
                     capacity=cap,pullthru=pullthru)
        td.s.add(sl)
        try:
            td.s.flush()
        except td.IntegrityError:
            td.s.rollback()
            ui.infopopup(["Could not create display space '%s'; there is "
                          "a display space with that name already."%(
                        self.namefield.f,)],
                         title="Error")
            return
        self.dismiss()
        editbindings(sl)

class modify(ui.dismisspopup):
    def __init__(self,stockline):
        td.s.add(stockline)
        self.stockline=stockline
        ui.dismisspopup.__init__(self,8,63,title="Modify Stock Line",
                                 colour=ui.colour_input,
                                 dismiss=keyboard.K_CLEAR)
        # Can change name, location, capacity or pullthru,
        # but not any other property.  Also, capacity cannot be set from
        # non-null to null or null to non-null.
        self.addstr(2,2,"    Stock line name:")
        self.addstr(3,2,"           Location:")
        self.addstr(4,2,"         Department: %s"%stockline.department)
        if stockline.capacity is None:
            self.addstr(5,2,"Pull-through amount:")
        else:
            self.addstr(5,2,"   Display capacity:")
        self.namefield=ui.editfield(2,23,30,f=stockline.name,keymap={
            keyboard.K_CLEAR: (self.dismiss,None)})
        self.locfield=ui.editfield(3,23,20,f=stockline.location)
        fl=[self.namefield,self.locfield]
        if stockline.capacity is None:
            self.pullthrufield=ui.editfield(
                5,23,5,f=stockline.pullthru,validate=ui.validate_float,
                keymap={keyboard.K_CASH: (self.enter,None)})
            fl.append(self.pullthrufield)
        else:
            self.capacityfield=ui.editfield(
                5,23,5,f=stockline.capacity,validate=ui.validate_int,
                keymap={keyboard.K_CASH: (self.enter,None)})
            fl.append(self.capacityfield)
        ui.map_fieldlist(fl)
        self.namefield.focus()
    def enter(self):
        td.s.add(self.stockline)
        if (self.namefield.f=='' or self.locfield.f==''):
            ui.infopopup(["You may not make either of the first two fields"
                          "blank."],
                         title="Error")
            return
        if self.stockline.capacity is None:
            cap=None
            pullthru=(float(self.pullthrufield.f) if self.pullthrufield.f!=''
                      else None)
        else:
            cap=(int(self.capacityfield.f) if self.capacityfield.f!=''
                 else None)
            pullthru=None
        if self.stockline.capacity is not None and cap is None:
            ui.infopopup(["You may not change a line from one with "
                          "display space to one that does not have display "
                          "space.  You should delete and re-create it "
                          "instead."],title="Error")
            return
        capmsg=("  The change in display capacity will take effect next "
                "time the line is re-stocked." if cap!=self.stockline.capacity
                else "")
        self.stockline.name=self.namefield.f
        self.stockline.location=self.locfield.f
        self.stockline.capacity=cap
        self.stockline.pullthru=pullthru
        try:
            td.s.flush()
        except:
            ui.infopopup(["Could not update stock line '%s'."%(
                        self.stockline.name,)],title="Error")
            return
        self.dismiss()
        ui.infopopup(["Updated stock line '%s'.%s"%(
                    self.stockline.name,capmsg)],
                     colour=ui.colour_info,dismiss=keyboard.K_CASH,
                     title="Confirmation")

def editbindings(stockline):
    """Allow keyboard bindings for a stock line to be added and
    deleted.  A keyboard binding consists of two parts: the line key
    and the menu key; if a line key has more than one stock line
    associated with it then a popup appears to enable selection using
    the menu key.  Keyboard bindings also have a quantity associated
    with them; this is useful for (for example) half-pint keys,
    although other possibilities exist (a key for a 4-pint jug of some
    product, for example).

    We display a list of existing key bindings (if any); selecting
    them enables the quantity to be edited or the binding deleted.
    Pressing a line key produces a further dialog box which lists
    existing menu key allocations for that line key, and prompts for a
    new one; a default quantity of '1' is assumed.

    """

    td.s.add(stockline)
    bindings=td.s.query(KeyboardBinding).\
        filter(KeyboardBinding.layout==tillconfig.kbtype).\
        filter(KeyboardBinding.stockline==stockline).\
        all()
    blurb=("To add a keyboard binding for '%s', press the appropriate line "
           "key now."%(stockline.name,))
    if len(bindings)>0:
        blurb=blurb+("  Existing bindings for '%s' are listed "
                     "below; if you would like to modify or delete one "
                     "then select it and press Cash/Enter."%(stockline.name,))
    menu=[("%s (%s) -> %s (%s), qty %s"%(
        ui.kb.keycap(keyboard.keycodes[kb.keycode]),
        kb.keycode,ui.kb.keycap(keyboard.keycodes[kb.menukey]),
        kb.menukey,kb.qty),
           changebinding,(stockline,kb.keycode,kb.menukey,kb.qty))
          for kb in bindings]
    kb={}
    for i in keyboard.lines:
        kb[i]=(addbinding,(stockline,i),True)
    ui.menu(menu,blurb=blurb,title="Edit keyboard bindings",keymap=kb)

class addbinding(ui.linepopup):
    def __init__(self,stockline,keycode):
        td.s.add(stockline)
        self.stocklineid=stockline.id
        self.keycode=keyboard.kcnames[keycode]
        existing=td.s.query(KeyboardBinding).\
            filter(KeyboardBinding.layout==tillconfig.kbtype).\
            filter(KeyboardBinding.keycode==self.keycode).\
            all()
        self.exdict={}
        lines=[]
        if len(existing)>0:
            lines=[
                "That key already has some other stock lines",
                "associated with it; they are listed below.",
                "",
                "When the key is pressed, a menu will be displayed",
                "enabling the till user to choose between them.",
                "You must now choose which key the user must press",
                "to select this stock line; make sure it isn't",
                "already in the list!"]
        else:
            lines=[
                "There are no other stock lines associated with",
                "that key, so when it's used there is no need",
                "for a menu to be displayed.  However, in case",
                "you add more stock lines to the key in the future,",
                "you must now choose which key the user will have",
                "to press to select this line.",
                "",
                "Pressing '1' now is usually the right thing to do!"]
        for kb in existing:
            lines.append("%s: %s"%(kb.menukey,kb.stockline.name))
            self.exdict[kb.menukey]=kb.stockline.name
        ui.linepopup.__init__(self,lines,title="Add keyboard binding",
                              colour=ui.colour_input)
    def keypress(self,k):
        if k==keyboard.K_CLEAR:
            self.dismiss()
            return
        name=keyboard.kcnames[k]
        if name in self.exdict: return
        td.s.add(KeyboardBinding(layout=tillconfig.kbtype,keycode=self.keycode,
                                 menukey=name,stocklineid=self.stocklineid,
                                 qty=1))
        td.s.flush()
        self.dismiss()
        changebinding(self.stocklineid,self.keycode,name,1.0)

class changebinding(ui.dismisspopup):
    def __init__(self,stocklineid,keycode,menukey,qty):
        ui.dismisspopup.__init__(self,7,50,title="Change keyboard binding",
                                 colour=ui.colour_input)
        self.stocklineid=stocklineid
        self.keycode=keycode
        self.menukey=menukey
        self.addstr(2,2,"Check the quantity and press Cash/Enter,")
        self.addstr(3,2,"or press Cancel to delete the binding.")
        self.addstr(5,2,"Quantity:")
        km={keyboard.K_CANCEL: (self.deletebinding,None),
            keyboard.K_CASH: (self.setqty,None),
            keyboard.K_CLEAR: (self.dismiss,None)}
        self.qtyfield=ui.editfield(5,12,5,f=str(qty),validate=ui.validate_float,
                                   keymap=km)
        self.qtyfield.focus()
    def deletebinding(self):
        self.dismiss()
        binding=td.s.query(KeyboardBinding).get(
            (tillconfig.kbtype,self.keycode,self.menukey))
        if binding: td.s.delete(binding)
        td.s.flush()
    def setqty(self):
        if self.qtyfield.f=="":
            ui.infopopup(["You must specify a quantity (1 is the most usual)"],
                         title="Error")
            return
        q=float(self.qtyfield.f)
        binding=td.s.query(KeyboardBinding).get(
            (tillconfig.kbtype,self.keycode,self.menukey))
        if binding:
            binding.qty=q
        td.s.flush()
        self.dismiss()

def delete(stockline):
    """Delete a stock line.  Key bindings to the line are deleted at
    the same time.

    """
    td.s.add(stockline)
    sl=stockline.stockonsale
    if len(sl)>0:
        message=["The stock line has been deleted.  Note that it still "
                 "had stock attached to it; this stock is now available "
                 "to be attached to another stock line.  The stock items "
                 "affected are shown below.",""]
        message=message+[
            "  %d %s"%(x.id,x.stocktype.format())
            for x in sl]
    else:
        message=["The stock line has been deleted."]
    
    td.s.delete(stockline)
    # Any StockItems that point to this stockline should have their
    # stocklineid set to null by the database.  XXX check that sqlalchemy
    # isn't trying to delete StockItems here!
    td.s.flush()
    ui.infopopup(message,title="Stock line deleted",colour=ui.colour_info,
                 dismiss=keyboard.K_CASH)

def listunbound():
    """Pop up a list of stock lines with no key bindings on any keyboard.

    """
    l=td.s.query(StockLine).outerjoin(KeyboardBinding).\
        filter(KeyboardBinding.stocklineid==None).\
        all()
    if len(l)==0:
        ui.infopopup(["There are no stock lines that lack key bindings.",
                      "","Note that other tills may have key bindings to "
                      "a stock line even if this till doesn't."],
                     title="Unbound stock lines",colour=ui.colour_info,
                     dismiss=keyboard.K_CASH)
    else:
        f=ui.tableformatter(' l l l l ')
        headerline=ui.tableline(f,["Name","Location","Department","Stock"])
        ll=[ui.tableline(f,(x.name,x.location,x.department.description,
                            "Yes" if len(x.stockonsale)>0 else "No"))
            for x in l]
        # Items in this list are selectable but doing so currently
        # does nothing.  At some point the "edit" and "delete"
        # stockline menu options should be merged into a single
        # stockline editor, and selecting a line here should open the
        # editor.
        ui.listpopup(ll,title="Unbound stock lines",colour=ui.colour_info,
                     header=[headerline])

class translate_keyline_to_stockline:
    def __init__(self,func):
        self.func=func
    def linekey(self,kb):
        td.s.add(kb)
        self.func(kb.stockline)

def selectline(func,title="Stock Lines",blurb=None,caponly=False,exccap=False):
    """A pop-up menu of stocklines, sorted by department, location and
    name.  Optionally can remove stocklines that have no capacities.
    Stocklines with key bindings to the current keyboard can be
    selected through that binding.

    """
    q=td.s.query(StockLine).order_by(StockLine.dept_id,StockLine.location,
                                     StockLine.name)
    if caponly: q=q.filter(StockLine.capacity!=None)
    if exccap: q=q.filter(StockLine.capacity==None)
    stocklines=q.all()
    f=ui.tableformatter(' l l l ')
    ml=[(ui.tableline(f,(x.name,x.location,x.dept_id)),func,(x,))
        for x in stocklines]
    km={}
    for i in keyboard.lines:
        km[i]=(linemenu,(i,translate_keyline_to_stockline(func).linekey),True)
    ui.menu(ml,title=title,blurb=blurb,keymap=km)

def selectlocation(func,title="Stock Locations",blurb="Choose a location",
                   caponly=False):
    """A pop-up menu of stock locations.  Calls func with a list of
    stocklines for the selected location.

    """
    stocklines=td.s.query(StockLine)
    if caponly: stocklines=stocklines.filter(StockLine.capacity!=None)
    stocklines=stocklines.all()
    l={}
    for sl in stocklines:
        if sl.location in l: l[sl.location].append(sl)
        else: l[sl.location]=[sl]
    ml=[(x,func,(l[x],)) for x in list(l.keys())]
    ui.menu(ml,title=title,blurb=blurb)

def popup():
    log.info("Stock line management popup")
    menu=[
        (keyboard.K_ONE,"Create a new stock line",create,None),
        (keyboard.K_TWO,"Modify a stock line",selectline,
         (modify,"Modify Stock Line",
          "Select a line to modify and press Cash/Enter")),
        (keyboard.K_THREE,"Delete a stock line",selectline,
         (delete,"Delete Stock Line",
          "Select a line to delete and press Cash/Enter")),
        (keyboard.K_FOUR,"Edit key bindings for a stock line",selectline,
         (editbindings,"Edit Key Bindings",
          "Select the line whose key bindings you want to edit and "
          "press Cash/Enter")),
        (keyboard.K_FIVE,"List stock lines with no key bindings",
         listunbound,None),
        (keyboard.K_SIX,"Return stock from display",selectline,
         (return_stock,"Return Stock","Select the stock line to remove "
          "from display",True)),
        (keyboard.K_NINE,"Purge finished stock items",td.stock_purge,None),
        ]
    ui.keymenu(menu,"Stock line options")

def linemenu(keycode,func):
    """
    Pop up a menu to select a line from a list.  Call func with the
    keyboard binding as an argument when a selection is made (NB it
    may be a detached instance).  No call is made if Clear is pressed.
    If there's only one keyboard binding in the list, shortcut to the
    function.

    This function returns the number of keyboard bindings found.  Some
    callers may wish to use this to inform the user that a key has no
    bindings rather than having an uninformative empty menu pop up.
    
    """
    # Find the keyboard bindings associated with this keycode
    kb=td.s.query(KeyboardBinding).\
        filter(KeyboardBinding.keycode==keyboard.kcnames[keycode]).\
        filter(KeyboardBinding.layout==tillconfig.kbtype).\
        all()

    if len(kb)==1: func(kb[0])
    elif len(kb)>1:
        il=sorted([(keyboard.keycodes[x.menukey],x.stockline.name,func,(x,))
                   for x in kb])
        ui.keymenu(il,title="Choose an item",colour=ui.colour_line)
    return len(kb)
