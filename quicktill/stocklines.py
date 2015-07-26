from __future__ import unicode_literals
import logging
from . import keyboard,ui,td,tillconfig,printer,user,linekeys,modifiers
from .models import Department,StockLine,KeyboardBinding
from .models import StockType,StockLineTypeLog
from sqlalchemy.sql import select
from decimal import Decimal
log=logging.getLogger(__name__)

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
                 colour=ui.colour_confirm,dismiss=None).\
        unsaved_data="confirm stock movements"

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

@user.permission_required('restock',"Re-stock items on display stocklines")
def restock_location():
    """Display a menu of locations, and then invoke restock_list for
    all stocklines in the selected location.

    """
    selectlocation(restock_list,title="Re-stock location",caponly=True)

@user.permission_required('restock',"Re-stock items on display stocklines")
def restock_all():
    """Invoke restock_list for all stocklines, sorted by location.

    """
    restock_list(td.s.query(StockLine).filter(StockLine.capacity!=None).all())

class stockline_associations(user.permission_checked,ui.listpopup):
    """
    A window showing the list of stocklines and their associated stock
    types.  Pressing Cancel on a line deletes the association.

    """
    permission_required=('manage-stockline-associations',
                         "View and delete stocktype <-> stockline links")
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
        headerline=f("Stock line","Stock type")
        lines=[f(stl.stockline.name,stl.stocktype.fullname,userdata=stl)
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
                 colour=ui.colour_confirm).\
        unsaved_data="confirm removal of stock from sale"

def completelocation(m):
    """
    An editfield validator that completes based on stockline location.

    """
    result=td.s.execute(
        select([StockLine.location]).\
            where(StockLine.location.ilike(m+'%'))
        )
    return [x[0] for x in result]

def validate_location(s,c):
    t=s[:c+1]
    l=completelocation(t)
    if len(l)>0: return l[0]
    # If a string one character shorter matches then we know we
    # filled it in last time, so we should return the string with
    # the rest chopped off rather than just returning the whole
    # thing unedited.
    if len(completelocation(t[:-1]))>0:
        return t
    return s

class create(user.permission_checked,ui.dismisspopup):
    """
    Create a new stockline.

    """
    permission_required=('create-stockline',"Create a new stock line")
    def __init__(self,func):
        ui.dismisspopup.__init__(self,12,55,title="Create Stock Line",
                                 colour=ui.colour_input,
                                 dismiss=keyboard.K_CLEAR)
        self.func=func
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
        self.locfield=ui.editfield(3,23,20,validate=validate_location)
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
        self.func(sl)

class modify(user.permission_checked,ui.dismisspopup):
    """
    Modify a stockline.  Shows the name and location, and allows any
    pull-through amount or display capacity to be edited.

    Buttons:
      Save    Delete    Use Stock

    List of current keyboard bindings; when one of these is
    highlighted, you can press Enter to edit the quantity or Cancel to
    remove the binding.

    """
    permission_required=('alter-stockline','Modify or delete an existing stock line')
    def __init__(self,stockline):
        td.s.add(stockline)
        self.stockline=stockline
        ui.dismisspopup.__init__(self,22,58,title="Stock Line",
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
        self.locfield=ui.editfield(3,23,20,f=stockline.location,
                                   validate=validate_location)
        fl=[self.namefield,self.locfield]
        if stockline.capacity is None:
            self.pullthrufield=ui.editfield(
                5,23,5,f=stockline.pullthru,validate=ui.validate_float)
            fl.append(self.pullthrufield)
        else:
            self.capacityfield=ui.editfield(
                5,23,5,f=stockline.capacity,validate=ui.validate_int)
            fl.append(self.capacityfield)
        self.savebutton=ui.buttonfield(7,2,8,"Save",keymap={
                keyboard.K_CASH: (self.save,None)})
        self.deletebutton=ui.buttonfield(7,14,10,"Delete",keymap={
                keyboard.K_CASH: (self.delete,None)})
        # Stock control terminals won't have a dedicated "Use Stock"
        # button.  This button fakes that keypress.
        self.usestockbutton=ui.buttonfield(7,28,13,"Use Stock",keymap={
                keyboard.K_CASH: (
                    lambda:ui.handle_keyboard_input(keyboard.K_USESTOCK),None)})
        fl.append(self.savebutton)
        fl.append(self.deletebutton)
        fl.append(self.usestockbutton)
        self.addstr(9,2,'Press "Use Stock" to add or remove stock.')
        self.addstr(11,2,"To add a keyboard binding, press a line key now.")
        self.addstr(12,2,"To edit or delete a keyboard binding, choose it")
        self.addstr(13,2,"below and press Enter or Cancel.")
        self.kbs=ui.scrollable(16,1,56,4,[],keymap={
                keyboard.K_CASH: (self.editbinding,None),
                keyboard.K_CANCEL: (self.deletebinding,None)})
        fl.append(self.kbs)
        ui.map_fieldlist(fl)
        self.reload_bindings()
        self.namefield.focus()
    def keypress(self,k):
        # Handle keypresses that the fields pass up to the main popup
        if k==keyboard.K_USESTOCK:
            from . import usestock
            usestock.line_chosen(self.stockline)
        elif hasattr(k,'line'):
            linekeys.addbinding(self.stockline,k,
                                self.reload_bindings,
                                modifiers.defined_modifiers())
    def save(self):
        td.s.add(self.stockline)
        if (self.namefield.f=='' or self.locfield.f==''):
            ui.infopopup(["You may not make either of the first two fields"
                          "blank."],
                         title="Error")
            return
        if self.stockline.capacity is None:
            cap=None
            pullthru=(Decimal(self.pullthrufield.f) if self.pullthrufield.f!=''
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
    def delete(self):
        self.dismiss()
        td.s.add(self.stockline)
        if len(self.stockline.stockonsale)>0:
            # Set displayqtys to none - if we don't do this explicitly here
            # then setting the stockline field to null will violate the
            # displayqty_null_if_no_stockline constraint
            for si in self.stockline.stockonsale:
                si.displayqty=None
            message=["The stock line has been deleted.  Note that it still "
                     "had stock attached to it; this stock is now available "
                     "to be attached to another stock line.  The stock items "
                     "affected are shown below.",""]
            message=message+[
                "  %d %s"%(x.id,x.stocktype.format())
                for x in self.stockline.stockonsale]
        else:
            message=["The stock line has been deleted."]
        td.s.delete(self.stockline)
        # Any StockItems that point to this stockline should have their
        # stocklineid set to null by the database.  XXX check that sqlalchemy
        # isn't trying to delete StockItems here!
        td.s.flush()
        ui.infopopup(message,title="Stock line deleted",colour=ui.colour_info,
                     dismiss=keyboard.K_CASH)
    def editbinding(self):
        if self.kbs.cursor is None: return
        line=self.kbs.dl[self.kbs.cursor]
        linekeys.changebinding(line.userdata,self.reload_bindings,
                               modifiers.defined_modifiers())
    def deletebinding(self):
        # We should only be called when the scrollable has the focus
        if self.kbs.cursor is None: return
        line=self.kbs.dl.pop(self.kbs.cursor)
        self.kbs.redraw()
        td.s.add(line.userdata)
        td.s.delete(line.userdata)
        td.s.flush()
    def reload_bindings(self):
        td.s.add(self.stockline)
        f=ui.tableformatter(' l   c   l ')
        kbl=linekeys.keyboard_bindings_table(self.stockline.keyboard_bindings,f)
        self.addstr(15,1," "*56)
        self.addstr(15,1,f("Line key","Menu key","Default modifier").
                    display(56)[0])
        self.kbs.set(kbl)

class listunbound(ui.listpopup):
    """
    Pop up a list of stock lines with no key bindings on any keyboard.

    """
    def __init__(self):
        l=td.s.query(StockLine).outerjoin(KeyboardBinding).\
            filter(KeyboardBinding.stocklineid==None).\
            all()
        if len(l)==0:
            ui.infopopup(
                ["There are no stock lines that lack key bindings.",
                 "","Note that other tills may have key bindings to "
                 "a stock line even if this till doesn't."],
                title="Unbound stock lines",colour=ui.colour_info,
                dismiss=keyboard.K_CASH)
            return
        f=ui.tableformatter(' l l l l ')
        headerline=f("Name","Location","Department","Stock")
        self.ll=[f(x.name,x.location,x.department.description,
                   "Yes" if len(x.stockonsale)>0 else "No",
                   userdata=x) for x in l]
        ui.listpopup.__init__(self,self.ll,title="Unbound stock lines",
                              colour=ui.colour_info,header=[headerline])
    def keypress(self,k):
        if k==keyboard.K_CASH:
            self.dismiss()
            modify(self.ll[self.s.cursor].userdata)
        else:
            ui.listpopup.keypress(self,k)

class selectline(ui.listpopup):
    """
    A pop-up menu of stocklines, sorted by department, location and
    name.  Optionally can remove stocklines that have no capacities.
    Stocklines with key bindings can be selected through that binding.

    Optional arguments:
      blurb - text for the top of the window
      caponly - only list "display" stocklines
      exccap - don't list "display" stocklines
      create_new - allow a new stockline to be created
      select_none - a string for a menu item which will result in a call
        to func(None)

    """
    def __init__(self,func,title="Stock Lines",blurb=None,caponly=False,
                 exccap=False,keymap={},create_new=False,select_none=None):
        self.func=func
        q=td.s.query(StockLine).order_by(StockLine.dept_id,StockLine.location,
                                         StockLine.name)
        if caponly: q=q.filter(StockLine.capacity!=None)
        if exccap: q=q.filter(StockLine.capacity==None)
        stocklines=q.all()
        f=ui.tableformatter(' l l l r r ')
        self.sl=[f(x.name,x.location,x.department,
                   x.capacity or "",x.pullthru or "",
                   userdata=x)
                 for x in stocklines]
        self.create_new=create_new
        if create_new:
            self.sl=[ui.line(" New stockline")]+self.sl
        elif select_none:
            self.sl=[ui.line(" %s"%select_none)]+self.sl
        hl=[f("Name","Location","Department","DC","PT")]
        if blurb:
            hl=[ui.lrline(blurb),ui.emptyline()]+hl
        ui.listpopup.__init__(self,self.sl,title=title,header=hl,keymap=keymap)
    def line_selected(self,kb):
        self.dismiss()
        td.s.add(kb)
        self.func(kb.stockline)
    def keypress(self,k):
        log.debug("selectline keypress %s",k)
        if hasattr(k,'line'):
            linekeys.linemenu(k,self.line_selected)
        elif k==keyboard.K_CASH and len(self.sl)>0:
            self.dismiss()
            line=self.sl[self.s.cursor]
            if line.userdata: self.func(line.userdata)
            else:
                if self.create_new: create(self.func)
                else: self.func(None)
        else:
            ui.listpopup.keypress(self,k)

def stocklinemenu():
    """
    Menu allowing stocklines to be created, modified and deleted.

    """
    selectline(
        modify,blurb="Choose a stock line to modify from the list below, "
        "or press a line key that is already bound to the "
        "stock line.",create_new=True)

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
