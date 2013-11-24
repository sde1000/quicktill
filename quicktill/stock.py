"""Useful routines for dealing with stock.

"""

import logging
from decimal import Decimal
from . import ui,td,keyboard,tillconfig,stocklines,department
from .models import Department,StockType,StockItem,StockAnnotation
from .models import AnnotationType
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
    # Not sure what this is doing here!  Was it for testing?
    keymap[ord('l')]=(annotate_location,(sn,),False)
    ui.listpopup(stockinfo_linelist(sn),
                 title="Stock Item %d"%sn,
                 dismiss=keyboard.K_CASH,
                 show_cursor=False,
                 colour=ui.colour_info,keymap=keymap)

class annotate(ui.dismisspopup):
    """This class permits annotations to be made to stock items.  If
    it is called with a stockid then the stockid field is pre-filled;
    otherwise a numeric entry may be made, or a pop-up list may be
    used to select the stockid.

    """
    def __init__(self,stockid=None):
        ui.dismisspopup.__init__(self,11,64,"Annotate Stock",
                                 colour=ui.colour_input)
        self.addstr(2,2,"Press stock line key or enter stock number.")
        self.addstr(3,2,"       Stock item:")
        stockfield_km={keyboard.K_CLEAR: (self.dismiss,None),
                       keyboard.K_CASH: (self.stock_enter_key,None)}
        # XXX this requires updating after the keyboard change.
        # Suggest a new type of field for choosing a stock item.
        for i in keyboard.lines:
            stockfield_km[i]=(stocklines.linemenu,(i,self.stock_line))
        self.stockfield=ui.editfield(3,21,30,validate=ui.validate_int,
                                     keymap=stockfield_km)
        self.stockfield.focus()
        if stockid is not None:
            self.stockfield.set(str(stockid))
            self.stock_enter_key()
    def stock_line(self,line):
        td.s.add(line)
        if line.capacity is None:
            # Look up the stock number, put it in the field, and invoke
            # stock_enter_key
            sl=line.stockonsale
            if len(sl)==0:
                ui.infopopup(["There is nothing on sale on %s."%line.name],
                             title="Error")
            else:
                self.stockfield.set(str(sl[0].id))
                self.stock_enter_key()
    def stock_dept_selected(self,dept):
        sinfo=td.s.query(StockItem).join(StockItem.stocktype).\
            filter(StockItem.finished==None).\
            filter(StockType.dept_id==dept).\
            order_by(StockItem.id).\
            all()
        f=ui.tableformatter(' r l ')
        sl=[(ui.tableline(f,(x.id,x.stocktype.format())),
             self.stock_item_selected,(x.id,)) for x in sinfo]
        ui.menu(sl,title="Select Item",blurb="Select a stock item and press "
                "Cash/Enter.")
    def stock_item_selected(self,stockid):
        self.stockfield.set(str(stockid))
        self.stock_enter_key()
    def stock_enter_key(self):
        if self.stockfield.f=='':
            department.menu(self.stock_dept_selected,"Select Department")
            return
        sn=int(self.stockfield.f)
        sd=td.s.query(StockItem).get(sn)
        if sd is None:
            ui.infopopup(["Stock number %d does not exist."%sn],
                         title="Error")
            return
        if not sd.delivery.checked:
            ui.infopopup(["Stock number %d is part of a delivery that has "
                          "not yet been confirmed.  You can't annotate "
                          "it until the whole delivery is confirmed."%(sd.id)],
                         title="Error")
            return
        # We want the popup to be focused while creating the next two
        # fields; if the stocknumber field is focused then it will be
        # their parent and focus may return there in error!
        self.focus()
        self.sn=sn
        self.addstr(4,21,sd.stocktype.format(maxw=40))
        self.addstr(5,2,"Annotation type:")
        self.addstr(7,2,"Annotation:")
        annlist=td.s.query(AnnotationType).\
            filter(~AnnotationType.id.in_(['start','stop'])).\
            all()
        self.anntypefield=ui.listfield(5,21,30,annlist,
                                       d=lambda x:x.description,keymap={
                keyboard.K_CLEAR:(self.dismiss,None)})
        self.annfield=ui.editfield(8,2,60,keymap={
                keyboard.K_CASH: (self.finish,None)})
        ui.map_fieldlist([self.anntypefield,self.annfield])
        self.anntypefield.focus()
    def finish(self):
        anntype=self.anntypefield.read()
        if anntype is None:
            ui.infopopup(["You must choose an annotation type!"],title="Error")
            return
        annotation=self.annfield.f or ""
        item=td.s.query(StockItem).get(self.sn)
        log.debug("%s %s %s",item,anntype,annotation)
        td.s.add(
            StockAnnotation(stockitem=item,type=anntype,text=annotation))
        td.s.flush()
        self.dismiss()
        ui.infopopup(["Recorded annotation against stock item %d (%s)."%(
                    item.id,item.stocktype.format())],
                     title="Annotation Recorded",dismiss=keyboard.K_CASH,
                     colour=ui.colour_info)

class annotate_location(ui.dismisspopup):
    """A special, simplified version of the stock annotation popup, that
    only allows the location to be set.  Must be called with a stock ID;
    doesn't permit stock ID entry.

    """
    def __init__(self,stockid):
        sd=td.s.query(StockItem).get(stockid)
        if sd is None:
            ui.infopopup(["Stock number %d does not exist."%sn],
                         title="Error")
            return
        if not sd.delivery.checked:
            ui.infopopup(["Stock number %d is part of a delivery that has "
                          "not yet been confirmed.  You can't annotate "
                          "it until the whole delivery is confirmed."%sd.id],
                         title="Error")
            return
        ui.dismisspopup.__init__(self,7,64,"Stock Location",
                                 colour=ui.colour_input)
        self.sd=sd
        self.addstr(2,2,sd.stocktype.format(maxw=60))
        self.addstr(4,2,"Enter location:")
        self.locfield=ui.editfield(4,18,40,keymap={
            keyboard.K_CASH: (self.finish,None),
            keyboard.K_CLEAR: (self.dismiss,None)})
        self.locfield.focus()
    def finish(self):
        td.s.add(self.sd)
        td.s.add(StockAnnotation(
                stockitem=self.sd,atype='location',text=self.locfield.f))
        td.s.flush()
        self.dismiss()

