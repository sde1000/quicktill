import keyboard,ui,td,logging,tillconfig,printer
log=logging.getLogger()

def calculate_sale(stocklineid,items):
    """Given a line, work out a plan to remove a number of items from
    display.  They may be sold, wasted, etc.

    Returns (list of (stockid,items) pairs, the number of items that
    could not be allocated, a dictionary of all involved stock items,
    remaining stock (ondisplay,instock)).

    """
    name,location,capacity,dept,pullthru=td.stockline_info(stocklineid)
    sl=td.stock_onsale(stocklineid)
    if len(sl)==0:
        return ([],items,{},(0,0))
    sinfo=td.stock_info([x[0] for x in sl])
    snd={}
    for a,b in zip(sl,sinfo):
        if a[1] is None: b['displayqty']=0
        else: b['displayqty']=a[1]
        snd[b['stockid']]=b
    # Iterate over the stock items attached to the line and produce a
    # list of (stockid,items) pairs if possible; otherwise produce an
    # error message If the stockline has no capacity mentioned
    # ("capacity is None") then bypass this and just sell the
    # appropriate number of items from the only stockitem in the list!
    if capacity is None:
        return ([(sl[0][0],items)],0,snd,None)
    unallocated=items
    leftondisplay=0
    totalinstock=0
    sell=[]
    for i in sinfo:
        ondisplay=max(i['displayqty']-i['used'],0)
        sellqty=min(unallocated,ondisplay)
        log.debug("ondisplay=%d, sellqty=%d"%(ondisplay,sellqty))
        unallocated=unallocated-sellqty
        leftondisplay=leftondisplay+ondisplay-sellqty
        totalinstock=totalinstock+i['remaining']-sellqty
        if sellqty>0:
            sell.append((i['stockid'],sellqty))
    return (sell,unallocated,snd,(leftondisplay,totalinstock-leftondisplay))

def calculate_restock(stockline,target=None):
    """Given a stocklineid and optionally a different target quantity
    (used when removing stock from display prior to stockline
    deletion, for example) calculate the stock movements required.
    This function DOES NOT commit the movements to the database; there
    is a separate function for that.  Returns a list of
    (stockdict,fetchqty,newdisplayqty,qtyremain) tuples for the
    affected stock items.

    """
    name,location,capacity,dept,pullthru=td.stockline_info(stockline)
    if capacity is None: return None
    if target is not None: capacity=target
    log.info("Re-stock line '%s' capacity %d"%(name,capacity))
    sl=td.stock_onsale(stockline)
    sinfo=td.stock_info([x[0] for x in sl])
    # Merge the displayqty from sl into sinfo, and count up the amount
    # on display
    ondisplay=0
    for a,b in zip(sl,sinfo):
        if a[1] is None: dq=0
        else: dq=a[1]
        b['displayqty']=max(dq,b['used'])
        b['ondisplay']=b['displayqty']-b['used']
        ondisplay=ondisplay+b['ondisplay']
    del sl # Make sure we don't refer to it later
    needed=capacity-ondisplay
    # If needed is negative we need to return some stock!  The list
    # returned by td.stock_onsale is sorted by best before date and
    # delivery date, so if we're returning stock we need to reverse
    # the list to return stock with the latest best before date /
    # latest delivery first.
    if needed<0:
        sinfo.reverse()
    sm=[]
    for i in sinfo:
        iondisplay=i['ondisplay'] # number already on display
        available=i['size']-i['displayqty'] # number available to go on display
        move=0
        if needed>0:
            move=min(needed,available)
        if needed<0:
            move=max(needed,0-iondisplay)
        needed=needed-move
        newdisplayqty=i['displayqty']+move
        stockqty_after_move=i['size']-newdisplayqty
        if move!=0:
            sm.append((i,move,newdisplayqty,stockqty_after_move))
    if sm==[]: return None
    return (stockline,name,ondisplay,capacity,sm)
        
def restock_list(stockline_list):
    # Print out list of things to fetch and put on display
    # Display prompt: have you fetched them all?
    # If yes, update records.  If no, don't.
    sl=[]
    for i in stockline_list:
        sl.append(calculate_restock(i))
    sl=[x for x in sl if x is not None]
    if sl==[]:
        ui.infopopup(["There is no stock to be put on display."],
                     title="Stock movement")
        return
    printer.print_restock_list(sl)
    ui.infopopup([
        "The list of stock to be put on display has been printed.  "
        "For each line that needs re-stocking it shows the number "
        "of units that need to be fetched from each "
        "container, and the number of units of stock that should "
        "be left in the container afterwards.","Please note any "
        "discrepancies on the printout and enter them later using "
        "the 'Record Waste' button.","","Press Cash/Enter to "
        "confirm that you've fetched all the items on the list and "
        "allow the till to update its records.  Pressing Clear "
        "at this point will completely cancel the re-stock."],
                 title="Confirm stock movement",
                 keymap={keyboard.K_CASH:(finish_restock,(sl,),True)},
                 colour=ui.colour_confirm)

def finish_restock(sl):
    for stockline,name,ondisplay,capacity,stockmovements in sl:
        td.stockline_restock(stockline,stockmovements)
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
    lines=[x[0] for x in td.stockline_list(caponly=True)]
    return restock_list(lines)

def auto_allocate():
    """Automatically allocate stock to stock lines.

    """
    td.stock_autoallocate()
    ui.infopopup(["New stock of the same type as stock already on display "
                  "has automatically been allocated to those display lines."],
                 title="Auto-allocate confirmation",colour=ui.colour_confirm,
                 dismiss=keyboard.K_CASH)

def return_stock(stockline):
    sl=calculate_restock(stockline,target=0)
    if sl is None:
        ui.infopopup(["The till has no record of stock on display for "
                      "this line."],title="Remove stock")
        return
    printer.print_restock_list([sl])
    ui.infopopup([
        "The list of stock to be taken off display has been printed.",
        "","Press Cash/Enter to "
        "confirm that you've removed all the items on the list and "
        "allow the till to update its records.  Pressing Clear "
        "at this point will completely cancel the operation."],
                 title="Confirm stock movement",
                 keymap={keyboard.K_CASH:(finish_restock,([sl],),True)},
                 colour=ui.colour_confirm)

class create(ui.dismisspopup):
    def __init__(self):
        ui.dismisspopup.__init__(self,9,63,title="Create Stock Line",
                                 colour=ui.colour_input,
                                 dismiss=keyboard.K_CLEAR)
        depts=td.department_list()
        self.deptlist=[x[0] for x in depts]
        self.addstr(2,2,"    Stock line name:")
        self.addstr(3,2,"           Location:")
        self.addstr(4,2,"         Department:")
        self.addstr(5,2,"   Display capacity:")
        self.addstr(6,2,"Pull-through amount:")
        self.namefield=ui.editfield(self.win,2,23,30,keymap={
            keyboard.K_CLEAR: (self.dismiss,None,True)})
        self.locfield=ui.editfield(self.win,3,23,20)
        self.deptfield=ui.listfield(self.win,4,23,20,self.deptlist,
                                    d=dict(depts))
        self.capacityfield=ui.editfield(self.win,5,23,5,
                                        validate=ui.validate_int)
        self.pullthrufield=ui.editfield(self.win,6,23,5,
                                        validate=ui.validate_float,
                                        keymap={
            keyboard.K_CASH: (self.enter,None,False)})
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
        name=self.namefield.f
        loc=self.locfield.f
        dept=self.deptlist[self.deptfield.f]
        if self.capacityfield.f!='': cap=int(self.capacityfield.f)
        else: cap=None
        if self.pullthrufield.f!='': pullthru=float(self.pullthrufield.f)
        else: pullthru=None
        if pullthru is not None and cap is not None:
            ui.infopopup(["You may specify display capacity or quantity "
                          "to pull through, but not both."],title="Error")
            return
        slid=td.stockline_create(name,loc,dept,cap,pullthru)
        if slid is None:
            ui.infopopup(["Could not create display space '%s'; there is "
                          "a display space with that name already."%name],
                         title="Error")
        else:
            self.dismiss()
            editbindings(slid)

class modify(ui.dismisspopup):
    def __init__(self,stocklineid):
        self.stocklineid=stocklineid
        name,location,capacity,dept,pullthru=td.stockline_info(stocklineid)
        self.oldcapacity=capacity
        depts=dict(td.department_list())
        ui.dismisspopup.__init__(self,9,63,title="Modify Stock Line",
                                 colour=ui.colour_input,
                                 dismiss=keyboard.K_CLEAR)
        # Can change name, location, capacity or pullthru,
        # but not any other property.  Also, capacity cannot be set from
        # non-null to null or null to non-null.
        self.addstr(2,2,"    Stock line name:")
        self.addstr(3,2,"           Location:")
        self.addstr(4,2,"         Department: %s"%depts[dept])
        self.addstr(5,2,"   Display capacity:")
        self.addstr(6,2,"Pull-through amount:")
        if capacity is not None: capacity=str(capacity)
        if pullthru is not None: pullthru="%0.2f"%pullthru
        self.namefield=ui.editfield(self.win,2,23,30,f=name,keymap={
            keyboard.K_CLEAR: (self.dismiss,None,True)})
        self.locfield=ui.editfield(self.win,3,23,20,f=location)
        self.capacityfield=ui.editfield(self.win,5,23,5,f=capacity,
                                        validate=ui.validate_int)
        self.pullthrufield=ui.editfield(self.win,6,23,5,f=pullthru,
                                        validate=ui.validate_float,
                                        keymap={
            keyboard.K_CASH: (self.enter,None,False)})
        ui.map_fieldlist([self.namefield,self.locfield,
                          self.capacityfield,self.pullthrufield])
        self.namefield.focus()
    def enter(self):
        if (self.namefield.f=='' or self.locfield.f==''):
            ui.infopopup(["You may not make either of the first two fields"
                          "blank."],
                         title="Error")
            return
        name=self.namefield.f
        loc=self.locfield.f
        if self.capacityfield.f!='': cap=int(self.capacityfield.f)
        else: cap=None
        if self.pullthrufield.f!='': pullthru=float(self.pullthrufield.f)
        else: pullthru=None
        if self.oldcapacity is None and cap is not None:
            ui.infopopup(["You may not change a line from one with no "
                          "display space to one that has display space.  "
                          "You should delete it and re-create it instead."],
                         title="Error")
            return
        if self.oldcapacity is not None and cap is None:
            ui.infopopup(["You may not change a line from one with "
                          "display space to one that does not have display "
                          "space.  You should delete and re-create it "
                          "instead."],title="Error")
            return
        if pullthru is not None and cap is not None:
            ui.infopopup(["You may specify display capacity or quantity "
                          "to pull through, but not both."],title="Error")
            return
        ok=td.stockline_update(self.stocklineid,name,loc,cap,pullthru)
        if cap!=self.oldcapacity:
            capmsg=("  The change in display capacity will take effect next "
                    "time the line is re-stocked.")
        else:
            capmsg=""
        if ok:
            self.dismiss()
            ui.infopopup(["Updated stock line '%s'.%s"%(name,capmsg)],
                         colour=ui.colour_info,dismiss=keyboard.K_CASH,
                         title="Confirmation")
        else:
            ui.infopopup(["Could not update stock line '%s'."%name],
                         title="Error")

def editbindings(stocklineid):
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

    (name,location,capacity,dept,pullthru)=td.stockline_info(stocklineid)
    bindings=td.keyboard_checkstockline(tillconfig.kbtype,stocklineid)
    blurb=("To add a keyboard binding for '%s', press the appropriate line "
           "key now."%name)
    if len(bindings)>0:
        blurb=blurb+("  Existing bindings, for '%s' are listed "
                     "below; if you would like to modify or delete one "
                     "then select it and press Cash/Enter."%name)
    menu=[("%s (%s) -> %s (%s), qty %0.1f"%(
        ui.kb.keycap(keyboard.keycodes[keycode]),
        keycode,ui.kb.keycap(keyboard.keycodes[menukey]),
        menukey,qty),
           changebinding,(stocklineid,keycode,menukey,qty))
          for keycode,menukey,qty in bindings]
    kb={}
    for i in keyboard.lines:
        kb[i]=(addbinding,(stocklineid,i),True)
    ui.menu(menu,blurb=blurb,title="Edit keyboard bindings",keymap=kb)

class addbinding(ui.linepopup):
    def __init__(self,stocklineid,keycode):
        self.stocklineid=stocklineid
        self.keycode=keyboard.kcnames[keycode]
        self.existing=td.keyboard_checklines(tillconfig.kbtype,self.keycode)
        self.exdict={}
        lines=[]
        if len(self.existing)>0:
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
        for (linename,qty,dept,pullthru,menukey,
             stocklineid,location,capacity) in self.existing:
            lines.append("%s: %s"%(menukey,linename))
            self.exdict[menukey]=linename
        ui.linepopup.__init__(self,lines,title="Add keyboard binding",
                              colour=ui.colour_input)
    def keypress(self,k):
        if k==keyboard.K_CLEAR:
            self.dismiss()
            return
        name=keyboard.kcnames[k]
        if name in self.exdict: return
        td.keyboard_addbinding(tillconfig.kbtype,self.keycode,name,
                               self.stocklineid,1.0)
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
        km={keyboard.K_CANCEL: (self.deletebinding,None,False),
            keyboard.K_CASH: (self.setqty,None,False),
            keyboard.K_CLEAR: (self.dismiss,None,False)}
        self.qtyfield=ui.editfield(self.win,5,12,5,f=str(qty),
                                   validate=ui.validate_float,
                                   keymap=km)
        self.qtyfield.focus()
    def deletebinding(self):
        self.dismiss()
        td.keyboard_delbinding(tillconfig.kbtype,self.keycode,self.menukey)
    def setqty(self):
        if self.qtyfield.f=="":
            ui.infopopup(["You must specify a quantity (1 is the most usual)"],
                         title="Error")
            return
        q=float(self.qtyfield.f)
        td.keyboard_delbinding(tillconfig.kbtype,self.keycode,self.menukey)
        td.keyboard_addbinding(tillconfig.kbtype,self.keycode,self.menukey,
                               self.stocklineid,q)
        self.dismiss()

def delete(stocklineid):
    """Delete a stock line.  Key bindings to the line are deleted at
    the same time.

    """
    sl=td.stock_onsale(stocklineid)
    td.stockline_delete(stocklineid)
    if len(sl)>0:
        message=["The stock line has been deleted.  Note that it still "
                 "had stock attached to it; this stock is now available "
                 "to be attached to another stock line."]
    else:
        message=["The stock line has been deleted."]
    ui.infopopup(message,title="Stock line deleted",colour=ui.colour_info,
                 dismiss=keyboard.K_CASH)

def listunbound():
    """Pop up a list of stock lines with no key bindings on any keyboard.

    """
    l=td.stockline_listunbound()
    if len(l)==0:
        ui.infopopup(["There are no stock lines that lack key bindings.",
                      "","Note that other tills may have key bindings to "
                      "a stock line even if this till doesn't."],
                     title="Unbound stock lines",colour=ui.colour_info,
                     dismiss=keyboard.K_CASH)
    else:
        ll=["%s %s"%(x[0],x[1]) for x in l]
        ui.linepopup(ll,title="Unbound stock lines",colour=ui.colour_info,
                     dismiss=keyboard.K_CASH)

def purge():
    """Stock items that have been completely used up through the
    display mechanism should be marked as 'finished' in the stock
    table, and purged from the stockonsale table.  This is usually
    done automatically at the end of each session because stock items
    may be put back on display through the voiding mechanism during
    the session, but is also available as an option on the till
    management menu.

    """
    td.stock_purge()

class translate_keyline_to_stockline:
    def __init__(self,func):
        self.func=func
    def linekey(self,kl):
        (name,qty,dept,pullthru,menukey,stocklineid,location,capacity)=kl
        self.func(stocklineid)

def selectline(func,title="Stock Lines",blurb=None,caponly=False,exccap=False):
    """A pop-up menu of stocklines, sorted by department, location and
    name.  Optionally can remove stocklines that have no capacities.
    Stocklines with key bindings to the current keyboard can be
    selected through that binding.

    """
    stocklines=td.stockline_list(caponly=caponly,exccap=exccap)
    mlines=ui.table([(name,location,"%d"%dept)
                     for stocklineid,name,location,capacity,dept,pullthru
                     in stocklines]).format(' l l l ')
    ml=[(x,func,(y[0],)) for x,y in zip(mlines,stocklines)]
    km={}
    for i in keyboard.lines:
        km[i]=(linemenu,(i,translate_keyline_to_stockline(func).linekey),True)
    ui.menu(ml,title=title,blurb=blurb,keymap=km)

def selectlocation(func,title="Stock Locations",blurb=None,caponly=False):
    """A pop-up menu of stock locations.  Calls func with a list of
    stocklines for the selected location.

    """
    stocklines=td.stockline_list(caponly=caponly)
    l={}
    for stocklineid,name,location,capacity,dept,pullthru in stocklines:
        if location in l: l[location].append(stocklineid)
        else: l[location]=[stocklineid]
    ml=[(x,func,(l[x],)) for x in l.keys()]
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
        (keyboard.K_NINE,"Purge finished stock items",purge,None),
        ]
    ui.keymenu(menu,"Stock line options")

def linemenu(keycode,func):
    """Pop up a menu to select a line from a list.  Call func with the
    line as an argument when a selection is made.  No call is made if
    Clear is pressed.  If there's only one line in the list, or it's
    not a list, shortcut to the function."""
    linelist=td.keyboard_checklines(tillconfig.kbtype,
                                    keyboard.kcnames[keycode])
    if type(linelist) is list:
        if len(linelist)==1:
            func(linelist[0])
        else:
            il=[(keyboard.keycodes[x[4]],x[0],func,(x,))
                for x in linelist]
            # XXX sort the list here?
            il.sort()
            ui.keymenu(il,title="Choose an item",colour=ui.colour_line)
