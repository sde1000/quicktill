from . import pricecheck
from . import ui, td, keyboard, user, tillconfig, linekeys, modifiers
from .models import PriceLookup,Department,KeyboardBinding
from sqlalchemy.exc import IntegrityError
from decimal import Decimal
import logging
log = logging.getLogger(__name__)

def _decimal_or_none(x):
    return Decimal(x) if x else None

class create(user.permission_checked,ui.dismisspopup):
    """Create a new price lookup.

    """
    permission_required=('create-plu','Create a new price lookup')
    def __init__(self):
        ui.dismisspopup.__init__(self,12,57,title="Create PLU",
                                 colour=ui.colour_input,
                                 dismiss=keyboard.K_CLEAR)
        self.addstr(2,2,"Description:")
        self.addstr(3,2,"       Note:")
        self.addstr(4,2," Department:")
        self.addstr(6,2,"The Note field may be looked at by modifier keys;")
        self.addstr(7,2,"they may do different things depending on its value.")
        self.descfield=ui.editfield(2,15,40,flen=160,keymap={
            keyboard.K_CLEAR: (self.dismiss,None)})
        self.notefield=ui.editfield(3,15,40,flen=160)
        self.deptfield = ui.modellistfield(
            4, 15, 20, Department, lambda q: q.order_by(Department.id),
            d=lambda x: x.description)
        self.createfield=ui.buttonfield(9,23,10,"Create",keymap={
            keyboard.K_CASH: (self.enter,None)})
        ui.map_fieldlist([self.descfield,self.notefield,self.deptfield,
                          self.createfield])
        self.descfield.focus()

    def enter(self):
        if self.descfield.f == '' or self.deptfield.read() is None:
            ui.infopopup(["You must enter values for Description and "
                          "Department."],title="Error")
            return
        p=PriceLookup(description=self.descfield.f,
                      note=self.notefield.f or "",
                      department=self.deptfield.read())
        td.s.add(p)
        try:
            td.s.flush()
        except IntegrityError:
            td.s.rollback()
            ui.infopopup(["There is already a PLU with this description."],
                         title="Error")
            return
        self.dismiss()
        modify(p,focus_on_price=True)

class modify(user.permission_checked,ui.dismisspopup):
    permission_required=('alter-plu','Modify or delete an existing price lookup')
    def __init__(self,p,focus_on_price=False):
        td.s.add(p)
        self.plu=p
        ui.dismisspopup.__init__(self,24,58,title="Price Lookup",
                                 colour=ui.colour_input,
                                 dismiss=keyboard.K_CLEAR)
        self.addstr(2,2,"Description:")
        self.addstr(3,2,"       Note:")
        self.addstr(4,2," Department:")
        self.addstr(5,2,"      Price: "+tillconfig.currency)
        self.addstr(6,2,"Alternative prices:")
        self.addstr(7,2,"       1: {c}         2: {c}         3: {c}"
                    .format(c=tillconfig.currency))
        self.descfield=ui.editfield(
            2,15,30,flen=160,f=self.plu.description,
            keymap={keyboard.K_CLEAR: (self.dismiss,None)})
        self.notefield=ui.editfield(
            3,15,30,flen=160,f=self.plu.note)
        self.deptfield = ui.modellistfield(
            4, 15, 20, Department, lambda q: q.order_by(Department.id),
            d=lambda x: x.description,
            f=self.plu.department)
        self.pricefield=ui.editfield(
            5,15+len(tillconfig.currency),8,
            f=self.plu.price,validate=ui.validate_float)
        self.altprice1=ui.editfield(
            7,12+len(tillconfig.currency),8,
            f=self.plu.altprice1,validate=ui.validate_float)
        self.altprice2=ui.editfield(
            7,24+len(tillconfig.currency)*2,8,
            f=self.plu.altprice2,validate=ui.validate_float)
        self.altprice3=ui.editfield(
            7,36+len(tillconfig.currency)*3,8,
            f=self.plu.altprice3,validate=ui.validate_float)
        self.savebutton=ui.buttonfield(9,2,8,"Save",keymap={
                keyboard.K_CASH: (self.save,None)})
        self.deletebutton=ui.buttonfield(9,14,10,"Delete",keymap={
                keyboard.K_CASH: (self.delete,None)})
        self.addstr(11,2,"The Note field and alternative prices 1-3 can be ")
        self.addstr(12,2,"accessed by modifier keys.")
        self.addstr(14,2,"To add a keyboard binding, press a line key now.")
        self.addstr(15,2,"To edit or delete a keyboard binding, choose it ")
        self.addstr(16,2,"below and press Enter or Cancel.")
        self.kbs=ui.scrollable(19,1,56,4,[],keymap={
                keyboard.K_CASH: (self.editbinding,None),
                keyboard.K_CANCEL: (self.deletebinding,None)})
        ui.map_fieldlist([self.descfield,self.notefield,self.deptfield,
                          self.pricefield,self.altprice1,
                          self.altprice2,self.altprice3,
                          self.savebutton,self.deletebutton,self.kbs])
        self.reload_bindings()
        if focus_on_price: self.pricefield.focus()
        else: self.descfield.focus()
    def keypress(self,k):
        # Handle keypresses that the fields pass up to the main popup
        if hasattr(k,'line'):
            linekeys.addbinding(self.plu,k,self.reload_bindings,
                                modifiers.defined_modifiers())
    def save(self):
        td.s.add(self.plu)
        if self.descfield.f=='':
            ui.infopopup(["You may not make the description blank."],
                         title="Error")
            return
        if self.deptfield.read() is None:
            ui.infopopup(["You must specify a department."],
                          title="Error")
            return
        self.plu.description=self.descfield.f
        self.plu.note=self.notefield.f
        self.plu.department=self.deptfield.read()
        self.plu.price=_decimal_or_none(self.pricefield.f)
        self.plu.altprice1=_decimal_or_none(self.altprice1.f)
        self.plu.altprice2=_decimal_or_none(self.altprice2.f)
        self.plu.altprice3=_decimal_or_none(self.altprice3.f)
        try:
            td.s.flush()
        except IntegrityError:
            ui.infopopup(["You may not rename a price lookup to have the "
                          "same description as another price lookup."],
                         title="Duplicate price lookup error")
            return
        self.dismiss()
        ui.infopopup(["Updated price lookup '{}'.".format(
            self.plu.description)],colour=ui.colour_info,
                     dismiss=keyboard.K_CASH,title="Confirmation")
    def delete(self):
        self.dismiss()
        td.s.add(self.plu)
        td.s.delete(self.plu)
        td.s.flush()
        ui.infopopup(["The price lookup has been deleted."],
                     title="Price Lookup deleted",colour=ui.colour_info,
                     dismiss=keyboard.K_CASH)
    def editbinding(self):
        if self.kbs.cursor is None: return
        line=self.kbs.dl[self.kbs.cursor]
        linekeys.changebinding(line.userdata,self.reload_bindings,
                               modifiers.defined_modifiers())
    def deletebinding(self):
        if self.kbs.cursor is None: return
        line=self.kbs.dl.pop(self.kbs.cursor)
        self.kbs.redraw()
        td.s.add(line.userdata)
        td.s.delete(line.userdata)
        td.s.flush()
    def reload_bindings(self):
        td.s.add(self.plu)
        f=ui.tableformatter(' l   c   l ')
        kbl=linekeys.keyboard_bindings_table(self.plu.keyboard_bindings,f)
        self.addstr(18,1," "*56)
        self.addstr(18,1,f("Line key","Menu key","Default modifier").
                    display(56)[0])
        self.kbs.set(kbl)

class listunbound(ui.listpopup):
    """Pop up a list of price lookups with no key bindings on any keyboard.

    """
    def __init__(self):
        l=td.s.query(PriceLookup).outerjoin(KeyboardBinding).\
            filter(KeyboardBinding.pluid==None).\
            all()
        if len(l)==0:
            ui.infopopup(
                ["There are no price lookups that lack key bindings.",
                 "","Note that other tills may have key bindings to "
                 "a price lookup even if this till doesn't."],
                title="Unbound price lookups",colour=ui.colour_info,
                dismiss=keyboard.K_CASH)
            return
        f=ui.tableformatter(' l l ')
        headerline=f("Description","Note")
        self.ll=[f(x.description,x.note,userdata=x) for x in l]
        ui.listpopup.__init__(self,self.ll,title="Unbound price lookups",
                              colour=ui.colour_info,header=[headerline])
    def keypress(self,k):
        if k==keyboard.K_CASH:
            self.dismiss()
            modify(self.ll[self.s.cursor].userdata)
        else:
            ui.listpopup.keypress(self,k)

class plumenu(ui.listpopup):
    def __init__(self):
        plus=td.s.query(PriceLookup).order_by(PriceLookup.dept_id).\
              order_by(PriceLookup.description).all()
        f=ui.tableformatter(' l l r l ')
        self.ml=[ui.line(" New PLU")]+ \
            [f(x.description,x.note,tillconfig.fc(x.price),x.department,
               userdata=x)
             for x in plus]
        hl=[f("Description","Note","Price","Department")]
        ui.listpopup.__init__(self,self.ml,title="Price Lookups",header=hl)
    def keypress(self,k):
        log.debug("plumenu keypress %s",k)
        if hasattr(k,'line'):
            linekeys.linemenu(k,self.plu_selected,allow_stocklines=False,
                              allow_plus=True)
        elif k==keyboard.K_CASH and len(self.ml)>0:
            self.dismiss()
            line=self.ml[self.s.cursor]
            if line.userdata: modify(line.userdata)
            else:
                create()
        else:
            ui.listpopup.keypress(self,k)
    def plu_selected(self,kb):
        self.dismiss()
        td.s.add(kb)
        modify(kb.plu)
