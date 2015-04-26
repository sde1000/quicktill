"""Useful routines for dealing with stock.

"""

from __future__ import unicode_literals
import logging
from decimal import Decimal
from . import ui,td,keyboard,tillconfig,stocklines,department
from .models import Department,StockType,StockItem,StockAnnotation
from .models import AnnotationType,Delivery,desc,StockLineTypeLog
from sqlalchemy.orm import joinedload,undefer
log=logging.getLogger(__name__)

# XXX should probably convert this to take a StockItem object rather
# than a stock ID at some point
def stockinfo_linelist(sn):
    s=td.s.query(StockItem).get(sn)
    l=[]
    l.append(s.stocktype.format()+" - %d"%s.id)
    l.append("Sells for %s%s/%s.  "
             "%s %ss used; %s %ss remaining."%(
            tillconfig.currency,s.stocktype.saleprice,s.stocktype.unit.name,
            s.used,s.stocktype.unit.name,s.remaining,s.stocktype.unit.name))
    l.append("")
    l.append("Delivered %s by %s"%(s.delivery.date,s.delivery.supplier.name))
    if s.bestbefore: l.append("Best Before %s"%s.bestbefore)
    if s.onsale: l.append("Put on sale %s"%s.onsale)
    if s.firstsale:
        l.append("First sale: %s  Last sale: %s"%(s.firstsale,s.lastsale))
    if s.finished:
        l.append("Finished %s; %s"%(s.finished,s.finishcode.description))
    l.append("")
    for code,qty in s.removed:
        l.append("%s: %s"%(code.reason,qty))
    if len(s.annotations)>0:
        l.append("Annotations:")
    for a in s.annotations:
        l.append("%s: %s: %s"%(a.time,a.type.description,a.text))
    return l

def stockinfo_popup(sn,keymap={}):
    keymap=keymap.copy()
    ui.listpopup(stockinfo_linelist(sn),
                 title="Stock Item %d"%sn,
                 dismiss=keyboard.K_CASH,
                 show_cursor=False,
                 colour=ui.colour_info,keymap=keymap)

class annotate(ui.dismisspopup):
    """
    This class permits annotations to be made to stock items.

    """
    def __init__(self):
        ui.dismisspopup.__init__(self,9,70,"Annotate Stock",
                                 colour=ui.colour_input)
        self.addstr(2,2,"Press stock line key or enter stock number.")
        self.addstr(3,2,"       Stock item:")
        stockfield_km={keyboard.K_CLEAR: (self.dismiss,None),}
        self.stockfield=stockfield(3,21,47,keymap=stockfield_km,
                                   filter=stockfilter(
                allow_finished=True,sort_descending_stockid=True),
                                   title="Choose stock item to annotate",
                                   check_checkdigits=False)
        self.addstr(4,2,"Annotation type:")
        annlist=td.s.query(AnnotationType).\
            filter(~AnnotationType.id.in_(['start','stop'])).\
            all()
        self.anntypefield=ui.listfield(
            4,21,30,annlist,d=lambda x:x.description)
        self.addstr(5,2,"Annotation:")
        self.annfield=ui.editfield(6,2,60,keymap={
                keyboard.K_CASH: (self.finish,None)})
        ui.map_fieldlist([self.stockfield,self.anntypefield,self.annfield])
        self.stockfield.focus()
        ui.handle_keyboard_input(keyboard.K_CASH) # Pop up picker
    def finish(self):
        item=self.stockfield.read()
        if item is None:
            ui.infopopup(["You must choose a stock item."],title="Error")
            return
        anntype=self.anntypefield.read()
        if anntype is None:
            ui.infopopup(["You must choose an annotation type!"],title="Error")
            return
        if not self.annfield.f:
            ui.infopopup(["You can't add a blank annotation!"],title="Error")
            return
        annotation=self.annfield.f or ""
        cu=ui.current_user()
        user=cu.dbuser if cu and hasattr(cu,"dbuser") else None
        td.s.add(StockAnnotation(stockitem=item,type=anntype,text=annotation,
                                 user=user))
        td.s.flush()
        self.dismiss()
        ui.infopopup(["Recorded annotation against stock item %d (%s)."%(
                    item.id,item.stocktype.format())],
                     title="Annotation Recorded",dismiss=keyboard.K_CASH,
                     colour=ui.colour_info)

class stockfilter(object):
    """
    Filter and sort available stock items according to various
    criteria.  Stock items that are in unchecked deliveries can never
    be returned.

    """
    def __init__(self,department=None,allow_on_sale=True,allow_finished=False,
                 allow_has_bestbefore=True,
                 stockline_affinity=None,sort_descending_stockid=False):
        self.department=department
        self.allow_on_sale=allow_on_sale
        self.allow_finished=allow_finished
        self.allow_has_bestbefore=allow_has_bestbefore
        self.stockline_affinity=stockline_affinity
        self.sort_descending_stockid=sort_descending_stockid
    @property
    def is_single_department(self):
        return self.department is not None
    def query_items(self,department=None):
        """
        Return a query that lists matching items.  If a department is
        passed, this overrides the department restriction in the
        object.

        """
        if department is None:
            department=td.s.merge(self.department) if self.department else None
        q=td.s.query(StockItem).join(Delivery).filter(Delivery.checked==True)
        # Unfinished items are sorted to the top
        q=q.order_by(StockItem.finished!=None)
        if department:
            td.s.add(department)
            q=q.join(StockType)
            q=q.filter(StockType.department==department)
        if not self.allow_on_sale:
            q=q.filter(StockItem.stocklineid==None)
        if not self.allow_finished:
            q=q.filter(StockItem.finished==None)
        if not self.allow_has_bestbefore:
            q=q.filter(StockItem.bestbefore==None)
        if self.stockline_affinity:
            td.s.add(self.stockline_affinity)
            q=q.order_by(desc(StockItem.stocktype_id.in_(
                        td.select([StockLineTypeLog.stocktype_id],
                                  whereclause=(
                                StockLineTypeLog.stocklineid==self.stockline_affinity.id),
                                  correlate=True))))
        if self.sort_descending_stockid:
            q=q.order_by(desc(StockItem.id))
        else:
            q=q.order_by(StockItem.id)
        return q
    def item_problem(self,item):
        """
        If the passed item matches the criteria, returns None.
        Otherwise returns a string describing at least one problem
        with the item.  The item is expected to be attached to an ORM
        session.

        """
        if not item.delivery.checked: return "delivery not checked"
        if self.department:
            d=td.s.merge(self.department)
            if item.stocktype.department!=d: return "wrong department"
        if item.stocklineid is not None and not self.allow_on_sale:
            return "already on sale on %s"%item.stockline.name
        if item.finished is not None and not self.allow_finished:
            return "finished at %s"%ui.formattime(item.finished)
        if item.bestbefore is not None and not self.allow_has_bestbefore:
            return "already has a best-before date: %s"%ui.formatdate(item.bestbefore)

class stockpicker(ui.dismisspopup):
    """
    A popup window that allows a stock item to be chosen.  Contains
    one field for the stock number, and optionally another field for
    the check digits.  Pressing Enter on a blank stock number field
    will yield a popup list of departments (if no department
    constraint is specified) leading to a popup list of stock items.

    If a StockLine is specified for stockline_affinity then items of
    stock that have previously been on sale on that StockLine will be
    sorted to the top of the list.

    When the StockItem has been chosen, func is called with it as an
    argument.

    """
    def __init__(self,func,default=None,title="Choose stock item",
                 filter=stockfilter(),check_checkdigits=True):
        if default: td.s.add(default)
        self.title=title
        self.func=func
        self.filter=filter
        self.check=check_checkdigits and tillconfig.checkdigit_on_usestock
        h=9 if self.check else 7
        ui.dismisspopup.__init__(self,h,62,title,colour=ui.colour_input)
        self.addstr(2,2,"   Stock ID:")
        self.numfield=ui.editfield(
            2,15,8,validate=ui.validate_int,f=default.id if default else None,
            keymap={keyboard.K_CASH:(self.numfield_enter,None),
                    keyboard.K_DOWN:(self.numfield_enter,None)})
        self.numfield.sethook=self.numfield_set
        if self.check:
            self.addstr(6,2,"Checkdigits:")
            self.checkfield=ui.editfield(
                6,15,3,validate=ui.validate_int,
                keymap={keyboard.K_CASH:(self.checkfield_enter,None),
                        keyboard.K_CLEAR:(self.numfield.focus,None),
                        keyboard.K_UP:(self.numfield.focus,None)})
            self.checkfield.sethook=self.checkfield_set
        self.numfield.focus()
    def numfield_set(self):
        self.addstr(3,15," "*45)
        self.addstr(4,15," "*45)
        if self.numfield.f:
            stockid=int(self.numfield.f)
            item=td.s.query(StockItem).\
                options(joinedload('stocktype')).\
                get(stockid)
            if item:
                self.addstr(3,15,item.stocktype.format(maxw=43))
                not_ok=self.filter.item_problem(item)
                if not_ok: self.addstr(4,15,"(%s)"%not_ok)
    def checkfield_set(self):
        self.addstr(6,20," "*7)
        if len(self.checkfield.f)!=3: return
        stockid=int(self.numfield.f)
        item=td.s.query(StockItem).get(stockid)
        self.addstr(6,20,"(OK)" if item and item.checkdigits==self.checkfield.f
                    else "(wrong)")
    def numfield_enter(self):
        if self.numfield.f:
            # Only advance if there's a valid stock item there
            stockid=int(self.numfield.f)
            item=self.filter.query_items().\
                filter(StockItem.id==stockid).first()
            if item:
                if self.check:
                    self.checkfield.focus()
                else:
                    self.dismiss()
                    self.func(item)
        else:
            if self.filter.is_single_department:
                self.popup_menu(None)
            else:
                depts=td.s.query(Department).order_by(Department.id).all()
                f=ui.tableformatter(' r l ')
                lines=[(f(d.id,d.description),
                        self.popup_menu,(d,)) for d in depts]
                ui.menu(lines)
    def popup_menu(self,department):
        items=self.filter.query_items(department).\
            options(joinedload('stocktype')).\
            options(undefer('remaining'))[:100]
        f=ui.tableformatter(' r l c ')
        sl=[(f(s.id,s.stocktype.format(),"%s %ss"%(
            s.remaining,s.stockunit.unit.name)),
             self.item_chosen,(s.id,))
            for s in items]
        ui.menu(sl,title=self.title)
    def item_chosen(self,stockid):
        # An item has been chosen from the popup menu
        self.numfield.set(str(stockid))
        if self.check: self.checkfield.set("")
        self.numfield_enter()
    def checkfield_enter(self):
        stockid=int(self.numfield.f)
        item=td.s.query(StockItem).get(stockid)
        if self.checkfield.f==item.checkdigits:
            self.dismiss()
            self.func(item)
    def linekey(self,kb):
        td.s.add(kb)
        line=kb.stockline
        if len(line.stockonsale)==0: return
        if len(line.stockonsale)==1:
            item=line.stockonsale[0]
            problem=self.filter.item_problem(item)
            if problem:
                ui.infopopup(["You can't choose %s: %s"%(
                            item.stocktype.format(),problem)],title="Error")
                return
            self.item_chosen(item.id)
        else:
            ui.infopopup(["There's more than one stock item on sale on %s"%
                          line.name],title="Error")
    def keypress(self,k):
        if hasattr(k,'line'):
            stocklines.linemenu(k,self.linekey)
        else:
            ui.dismisspopup.keypress(self,k)

class stockfield(ui.popupfield):
    """
    A field that allows a stock item to be chosen.  If
    check_checkdigits is True then manual entry of stock numbers will
    result in a checkdigits check; choosing stock items on sale on a
    stock line will skip the check.

    """
    def __init__(self,y,x,w,f=None,keymap={},readonly=False,
                 filter=stockfilter(),check_checkdigits=True,
                 title="Choose stock item"):
        ui.popupfield.__init__(
            self,y,x,w,popupfunc=stockpicker, # Pass on args?
            valuefunc=lambda x:"%d: %s"%(
                x.id,x.stocktype.format(maxw=w-2-len(str(x.id)))),
            f=f,readonly=readonly,keymap=keymap)
        self.filter=filter
        self.check_checkdigits=check_checkdigits
        self.title=title
    def popup(self):
        # If we're popping up the stockpicker, it's because we want to
        # pick a different stock item!  Setting the current one as
        # default doesn't make sense - the user would just have to
        # press 'Clear' to get rid of it.
        if not self.readonly:
            stockpicker(self.setf,filter=self.filter,
                        check_checkdigits=self.check_checkdigits,
                        title=self.title)
    def linekey(self,kb):
        td.s.add(kb)
        line=kb.stockline
        if len(line.stockonsale)==0: return
        if len(line.stockonsale)==1:
            item=line.stockonsale[0]
            problem=self.filter.item_problem(item)
            if problem:
                ui.infopopup(["You can't choose %s: %s"%(
                            item.stocktype.format(),problem)],title="Error")
                return
            self.setf(item)
        else:
            ui.infopopup(["There's more than one stock item on sale on %s"%
                          line.name],title="Error")
    def keypress(self,k):
        if k in keyboard.numberkeys and not self.readonly:
            # Pass on the keypress to the stocknumber entry popup
            self.popup()
            ui.handle_keyboard_input(k)
        if hasattr(k,'line'):
            stocklines.linemenu(k,self.linekey)
        else:
            ui.popupfield.keypress(self,k)
