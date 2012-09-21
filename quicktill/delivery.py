import curses.ascii
import ui,stock,td,keyboard,printer,tillconfig,stocklines

def create_and_edit_delivery(supplier):
    dn=td.delivery_new(supplier)
    delivery(dn)

def new_delivery():
    selectsupplier(create_and_edit_delivery,allow_new=True)

def deliverylist(func,unchecked_only=False,checked_only=False,createfunc=None):
    def d(x):
        did,supid,docnum,date,checked,name=x
        return ("%d"%did,name,ui.formatdate(date),("not confirmed","")[checked])
    dl=td.delivery_get(unchecked_only=unchecked_only,checked_only=checked_only)
    lines=ui.table([d(x) for x in dl]).format(' r l l l ')
    m=[(x,func,(y[0],)) for x,y in zip(lines,dl)]
    if createfunc is not None:
        m.insert(0,("Record new delivery",createfunc,None))
    ui.menu(m,title="Delivery List",
            blurb="Select a delivery and press Cash/Enter.")

class deliveryline(ui.line):
    def __init__(self,stockid):
        ui.line.__init__(self)
        self.stockid=stockid
        self.update()
    def update(self):
        sd=td.stock_info([self.stockid])[0]
        typestr=stock.format_stock(sd,maxw=37)
        try:
            coststr="%-6.2f"%sd['costprice']
        except:
            coststr="????? "
        s="%7d %-37s %-8s %s %-5.2f %-10s"%(
            self.stockid,typestr,sd['stockunit'],coststr,
            sd['saleprice'],ui.formatdate(sd['bestbefore']))
        self.text=s

class delivery(ui.basicpopup):
    """The delivery window allows a delivery to be edited, printed or
    confirmed.  Prior to confirmation all details of a delivery can be
    changed.  After confirmation the delivery is read-only.  The window
    contains a header area, with supplier name, delivery date and
    document number; a couple of prompts, and a scrollable list of stock
    items.  If the window is not read-only, there is always a blank line
    at the bottom of the list to enable new entries to be made."""
    def __init__(self,dn):
        (mh,mw)=ui.stdwin.getmaxyx()
        if mw<80 or mh<14:
            ui.infopopup(["Error: the screen is too small to display "
                          "the delivery dialog box.  It must be at least "
                          "80x14 characters."],
                         title="Screen width problem")
            return
        self.dn=dn
        (id,supplier,docnumber,date,checked,supname)=td.delivery_get(
            number=dn)[0]
        self.dl=[deliveryline(x) for x in td.delivery_items(dn)]
        if checked:
            self.readonly=True
            title="Delivery Details - read only (already confirmed)"
            cleartext="Press Clear to go back"
        else:
            self.readonly=False 
            title="Delivery Details"
            cleartext=None
        # Keymap for the scrollable field
        if self.readonly:
            skm={keyboard.K_CASH: (self.view_line,None)}
        else:
            skm={keyboard.K_CASH: (self.edit_line,None),
                 keyboard.K_CANCEL: (self.deleteline,None),
                 keyboard.K_QUANTITY: (self.duplicate_item,None)}
        # The window can be as tall as the screen; we expand the scrollable
        # field to fit.  The scrollable field must be at least three lines
        # high!
        ui.basicpopup.__init__(self,mh-1,80,title=title,cleartext=cleartext,
                               colour=ui.colour_input)
        self.addstr(2,2,"       Supplier:")
        self.addstr(3,2,"           Date:")
        self.addstr(4,2,"Document number:")
        self.addstr(6,1,"StockNo Stock Type........................... "
                        "Unit.... Cost.. Sale  BestBefore")
        self.supfield=ui.popupfield(2,19,59,selectsupplier,self.supplier_value,
                                    f=supplier,readonly=self.readonly)
        self.datefield=ui.datefield(3,19,f=date,readonly=self.readonly)
        self.docnumfield=ui.editfield(4,19,40,f=docnumber,
                                      readonly=self.readonly)
        self.entryprompt=None if self.readonly else ui.line(
            " [ New item ]")
        self.s=ui.scrollable(
            7,1,78,mh-9 if self.readonly else mh-11,self.dl,
            lastline=self.entryprompt,keymap=skm)
        if self.readonly:
            self.s.focus()
        else:
            self.deletefield=ui.buttonfield(
                mh-3,2,24,"Delete this delivery",keymap={
                    keyboard.K_CASH: (self.confirmdelete,None)})
            self.confirmfield=ui.buttonfield(
                mh-3,28,31,"Confirm details are correct",keymap={
                    keyboard.K_CASH: (self.confirmcheck,None)})
            self.savefield=ui.buttonfield(
                mh-3,61,17,"Save and exit",keymap={
                    keyboard.K_CASH: (self.finish,None)})
            ui.map_fieldlist(
                [self.supfield,self.datefield,self.docnumfield,self.s,
                 self.deletefield,self.confirmfield,self.savefield])
            self.datefield.focus()
    def reallydeleteline(self):
        td.stock_delete(self.dl[self.s.cursor].stockid)
        del self.dl[self.s.cursor]
        self.s.drawdl()
    def deleteline(self):
        if not self.s.cursor_on_lastline():
            ui.infopopup(
                ["Press Cash/Enter to confirm deletion of stock "
                 "number %d.  Note that once it's deleted you can't "
                 "create a new stock item with the same number; new "
                 "stock items always get fresh numbers."%(
                        self.dl[self.s.cursor].stockid)],
                title="Confirm Delete",
                keymap={keyboard.K_CASH:(self.reallydeleteline,None,True)})
    def pack_fields(self):
        # Check that there's still a supplier selected
        if self.supfield.f is None:
            ui.infopopup(["Select a supplier before continuing!"],title="Error")
            return
        # Check that the date field is valid
        d=self.datefield.read()
        if d is None:
            ui.infopopup(["Check that the delivery date is correct before "
                          "continuing!"],title="Error")
            return
        # Check that there's a document number
        if self.docnumfield.f=="":
            ui.infopopup(["Enter a document number before continuing!"],
                         title="Error")
            return
        return (self.supfield.f,self.datefield.read(),self.docnumfield.f)
    def finish(self):
        pf=self.pack_fields()
        if pf is not None:
            td.delivery_update(self.dn,*pf)
            self.dismiss()
    def printout(self):
        pf=self.pack_fields()
        if pf is None: return
        if not self.readonly:
            td.delivery_update(self.dn,*pf)
        if printer.labeldriver is not None:
            menu=[
                (keyboard.K_ONE,"Print list",
                 printer.print_delivery,(self.dn,)),
                (keyboard.K_TWO,"Print sticky labels",
                 printer.label_print_delivery,(self.dn,)),
                ]
            ui.keymenu(menu,"Delivery print options",colour=ui.colour_confirm)
        else:
            printer.print_delivery(self.dn)
    def reallyconfirm(self):
        # Set the Confirm flag
        self.finish()
        td.delivery_check(self.dn)
        stocklines.auto_allocate(deliveryid=self.dn,confirm=False)
    def confirmcheck(self):
        if self.pack_fields() is None: return
        # The confirm button was pressed; set the flag
        ui.infopopup(["When you confirm a delivery you are asserting that "
                      "you have received and checked every item listed as part "
                      "of the delivery.  Once the delivery is confirmed, you "
                      "can't go back and change any of the details.  Press "
                      "Cash/Enter to confirm this delivery now, or Clear to "
                      "continue editing it."],title="Confirm Details",
                     keymap={keyboard.K_CASH:(self.reallyconfirm,None,True)})
    def line_edited(self,sn):
        # Only called when a line has been edited; not called for new
        # lines or deletions
        if self.dl[self.s.cursor].stockid==sn:
            self.dl[self.s.cursor].update()
            self.s.cursor_down()
    def newline(self,sn):
        self.dl.append(deliveryline(sn))
        self.s.cursor_down()
    def edit_line(self):
        # If it's the "lastline" then we create a new stock item
        if self.s.cursor_on_lastline():
            stockline(self.newline,self.dn)
        else:
            stockline(self.line_edited,self.dn,self.dl[self.s.cursor].stockid)
    def view_line(self):
        # In read-only mode there is no "lastline"
        stock.stockinfo_popup(self.dl[self.s.cursor].stockid)
    def duplicate_item(self):
        ln=self.dl[len(self.dl)-1 if self.s.cursor_on_lastline()
                   else self.s.cursor].stockid
        sn=td.stock_duplicate(ln)
        self.newline(sn)
    def reallydelete(self):
        td.delivery_delete(self.dn)
        self.dismiss()
    def confirmdelete(self):
        ui.infopopup(["Do you want to delete the entire delivery and all "
                      "the stock items that have been entered for it?  "
                      "Press Cancel to delete or Clear to go back."],
                     title="Confirm Delete",
                     keymap={keyboard.K_CANCEL:(self.reallydelete,None,True)})
    def supplier_value(self,sup):
        (name,tel,email)=td.supplier_fetch(sup)
        return name
    def keypress(self,k):
        if k==keyboard.K_PRINT:
            self.printout()
        elif k==keyboard.K_CLEAR:
            self.dismiss()

class stockline(ui.basicpopup):
    def __init__(self,func,dn,sn=None):
        self.func=func
        self.sn=sn
        self.dn=dn
        cleartext=(
            "Press Clear to exit, forgetting all changes" if sn else
            "Press Clear to exit without creating a new stock item")
        ui.basicpopup.__init__(self,12,78,title="Stock Item",
                               cleartext=cleartext,colour=ui.colour_line)
        self.units=[]
        if sn is None:
            self.addstr(2,2,"Stock number not yet assigned")
        else:
            self.addstr(2,2,"        Stock number: %d"%sn)
        self.addstr(3,2,"          Stock type:")
        self.addstr(4,2,"                Unit:")
        self.addstr(5,2," Cost price (ex VAT): %s"%tillconfig.currency)
        self.addstr(6,2,"Sale price (inc VAT): %s"%tillconfig.currency)
        self.addstr(7,2,"         Best before:")
        self.typefield=ui.popupfield(3,24,52,stock.stocktype,
                                     stock.format_stocktype,keymap={
                keyboard.K_CLEAR: (self.dismiss,None)})
        self.typefield.sethook=self.updateunitfield
        self.unitfield=ui.listfield(4,24,20,None)
        self.costfield=ui.editfield(5,24+len(tillconfig.currency),6,
                                    validate=ui.validate_float)
        self.costfield.sethook=self.guesssaleprice
        self.salefield=ui.editfield(6,24+len(tillconfig.currency),6,
                                    validate=ui.validate_float)
        self.bestbeforefield=ui.datefield(7,24)
        self.acceptbutton=ui.buttonfield(9,28,21,"Accept values",keymap={
                keyboard.K_CASH: (self.accept,None)})
        ui.map_fieldlist(
            [self.typefield,self.unitfield,self.costfield,self.salefield,
             self.bestbeforefield,self.acceptbutton])
        if sn is not None:
            self.fill_fields(sn)
            if self.bestbeforefield.f=="":
                self.bestbeforefield.focus()
            else:
                self.acceptbutton.focus()
        else:
            self.typefield.focus()
    def fill_fields(self,sn):
        sd=td.stock_info([sn])[0]
        self.typefield.set(sd['stocktype'])
        self.updateunitfield(default=sd['stockunit'])
        if sd['costprice'] is None:
            self.costfield.set("")
        else:
            self.costfield.set("%0.2f"%sd['costprice'])
        self.salefield.set("%0.2f"%sd['saleprice'])
        self.bestbeforefield.set(sd['bestbefore'])
    def pack_fields(self):
        if self.typefield.f is None: return None
        if self.unitfield.f is None: return None
        if len(self.costfield.f)==0:
            cost=None
        else:
            cost=float(self.costfield.f)
        if len(self.salefield.f)==0: return None
        return (self.typefield.f,self.units[self.unitfield.f],
                cost,float(self.salefield.f),
                self.bestbeforefield.read())
    def accept(self):
        pf=self.pack_fields()
        if pf is None:
            ui.infopopup(["You have not filled in all the fields.  "
                          "The only optional fields are 'Best Before' "
                          "and 'Cost Price'."],
                         title="Error")
            return
        self.dismiss()
        if self.sn is None:
            self.sn=td.stock_receive(self.dn,*pf)
        else:
            td.stock_update(self.sn,*pf)
        self.func(self.sn)
    def updateunitfield(self,default=None):
        # If the unit field contains a value which is not valid for
        # the unittype of the selected stock type, rebuild the list of
        # stockunits
        if self.typefield.f==None:
            self.unitfield.l=[]
            self.unitfield.set(None)
            return
        (dept,manufacturer,name,shortname,abv,unit)=td.stocktype_info(
            self.typefield.f)
        ul=td.stockunits_list(unit)
        if default is not None:
            oldunit=default
        elif self.unitfield.f is not None:
            oldunit=self.units[self.unitfield.f]
        else: oldunit=None
        self.units=[x[0] for x in ul]
        if oldunit in self.units:
            newunit=self.units.index(oldunit)
        else: newunit=0
        self.unitfield.l=self.units
        self.unitfield.d=dict([(x[0],x[1]) for x in ul])
        self.unitfield.set(newunit)
    def guesssaleprice(self):
        # Called when the Cost field has been filled in
        if self.typefield.f is None or self.unitfield.f is None: return
        (dept,manufacturer,name,shortname,abv,unit)=td.stocktype_info(
            self.typefield.f)
        (uname,size)=td.stockunits_info(self.units[self.unitfield.f])
        if len(self.costfield.f)>0:
            wholeprice=float(self.costfield.f)
            g=tillconfig.priceguess(dept,(wholeprice/size),abv)
            if g is not None and self.salefield.f=="":
                self.salefield.set("%0.2f"%g)
    def keypress(self,k):
        # If the user starts typing into the stocktype field, be nice
        # to them and pop up the stock type entry dialog.  Then
        # synthesise the keypress again to enter it into the
        # manufacturer field.
        if (ui.focus==self.typefield and self.typefield.f is None
            and curses.ascii.isprint(k)):
            self.typefield.popup() # Grabs the focus
            ui.handle_keyboard_input(k)
        else:
            ui.basicpopup.keypress(self,k)

def selectsupplier(func,default=0,allow_new=True):
    sl=td.supplier_list()
    if allow_new: m=[("New supplier",editsupplier,(func,))]
    else: m=[]
    m=m+[(x[1],func,(x[0],)) for x in sl]
    ui.menu(m,blurb="Select a supplier from the list and press Cash/Enter.",
            title="Select Supplier",default=default)

class editsupplier(ui.basicpopup):
    def __init__(self,func,sn=None):
        self.func=func
        self.sn=sn
        if sn is not None: (name,tel,email)=td.supplier_fetch(sn)
        else: (name,tel,email)=("","","")
        ui.basicpopup.__init__(self,10,70,title="Supplier Details",
                               colour=ui.colour_input,cleartext=
                               "Press Clear to go back")
        self.addstr(2,2,"Please enter the supplier's details. You may ")
        self.addstr(3,2,"leave the telephone and email fields blank if you wish.")
        self.addstr(5,2,"     Name:")
        self.addstr(6,2,"Telephone:")
        self.addstr(7,2,"    Email:")
        self.namefield=ui.editfield(5,13,55,flen=60,keymap={
                keyboard.K_CLEAR: (self.dismiss,None)},f=name)
        self.telfield=ui.editfield(6,13,20,f=tel)
        self.emailfield=ui.editfield(7,13,55,flen=60,f=email,keymap={
                keyboard.K_CASH:(
                    self.confirmwin if sn is None else self.confirmed,None)})
        ui.map_fieldlist([self.namefield,self.telfield,self.emailfield])
        self.namefield.focus()
    def confirmwin(self):
        # Called when Cash/Enter is pressed on the last field, for new
        # suppliers only
        self.dismiss()
        ui.infopopup(["Press Cash/Enter to confirm new supplier details:",
                      "Name: %s"%self.namefield.f,
                      "Telephone: %s"%self.telfield.f,
                      "Email: %s"%self.emailfield.f],
                     title="Confirm New Supplier Details",
                     colour=ui.colour_input,keymap={
            keyboard.K_CASH: (self.confirmed,None,True)})
    def confirmed(self):
        if self.sn is None:
            self.sn=td.supplier_new(self.namefield.f,self.telfield.f,
                                    self.emailfield.f)
        else:
            self.dismiss()
            td.supplier_update(self.sn,self.namefield.f,self.telfield.f,
                               self.emailfield.f)
        self.func(self.sn)
