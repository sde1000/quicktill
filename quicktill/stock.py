"""Useful routines for dealing with stock.

"""

import logging
from decimal import Decimal
from . import ui,td,keyboard,tillconfig,stocklines,department
from .models import Department,UnitType,StockType,StockItem,StockAnnotation
from .models import penny,func,lazyload
log=logging.getLogger(__name__)

def abvstr(abv):
    if abv is None: return ""
    return " (%0.1f%% ABV)"%abv

class stocktype(ui.dismisspopup):
    """Select/modify a stock type.  Has two modes:

    1) Select a stock type. Auto-completes fields as they are typed
       at, hopefully to find a match with an existing stock type.
       (After selecting manufacturer/name, other fields are filled in
       if possible, but can still be edited.)  If, when form is
       completed, there is no match with an existing stock type, a new
       stock type will be created, provided "allownew" is set.  (This
       is the only way to create stock types.)

    2) Modify a stock type.  Allows all details of an existing stock
       type to be changed.  Has major warnings - should only be used
       for correcting minor typos!

    """
    def __init__(self,func,default=None,mode=1,allownew=True):
        """default, if present, is a models.StockType object.

        """
        self.func=func
        self.mode=mode
        self.allownew=allownew
        if mode==1:
            prompt="Select"
            title="Select Stock Type"
            blurb1="Enter stock details and then press"
            blurb2="Cash/Enter on the [Select] button."
        elif mode==2:
            prompt="Save Changes"
            title="Edit Stock Type"
            blurb1="NOTE: this is the wrong mode for"
            blurb2="creating new stock types!"
        else:
            raise Exception("Bad mode")
        self.st=td.s.merge(default) if default else None
        self.depts=td.s.query(Department).order_by(Department.id).all()
        self.units=td.s.query(UnitType).all()
        ui.dismisspopup.__init__(self,15,48,title=title,colour=ui.colour_input)
        self.addstr(2,2,blurb1)
        self.addstr(3,2,blurb2)
        self.addstr(5,2,"Manufacturer:")
        self.addstr(6,2,"        Name:")
        self.addstr(7,2,"  Short name:")
        self.addstr(8,2,"  Department:")
        self.addstr(8,38,"ABV:")
        self.addstr(9,2,"        Unit:")
        self.addstr(13,2,"Note: 'Short Name' may be printed on receipts.")
        self.manufield=ui.editfield(
            5,16,30,validate=self.validate_manufacturer,
            keymap={keyboard.K_CLEAR: (self.dismiss,None)})
        self.namefield=ui.editfield(
            6,16,30,validate=self.validate_name)
        self.snamefield=ui.editfield(7,16,25)
        self.deptfield=ui.listfield(
            8,16,20,self.depts,d=dict((x,x.description) for x in self.depts),
            readonly=(mode==2))
        self.abvfield=ui.editfield(8,42,4,validate=ui.validate_float)
        self.unitfield=ui.listfield(
            9,16,30,self.units,d=dict((x,x.name) for x in self.units),
            readonly=(mode==2))
        self.confirmbutton=ui.buttonfield(11,15,20,prompt,keymap={
                keyboard.K_CASH: (self.finish_mode1 if mode==1
                                  else self.finish_mode2, None)})
        ui.map_fieldlist(
            [self.manufield,self.namefield,self.snamefield,self.deptfield,
             self.abvfield,self.unitfield,self.confirmbutton])
        if self.st:
            self.fill_fields(self.st)
        if mode==1:
            # Some overrides; we want to be called when Enter is
            # pressed on the manufacturer field so we can pre-fill the
            # name field if possible, and on the name field so we can
            # pre-fill the other fields if possible.  Only in mode 1;
            # in mode 2 we're just editing
            self.manufield.keymap[keyboard.K_CASH]=(self.defaultname,None)
            self.namefield.keymap[keyboard.K_CASH]=(self.lookupname,None)
        self.manufield.focus()
    def fill_fields(self,st):
        "Fill all fields from the specified stock type"
        self.manufield.set(st.manufacturer)
        self.namefield.set(st.name)
        self.snamefield.set(st.shortname)
        self.deptfield.set(self.depts.index(st.department))
        self.abvfield.set(st.abv)
        self.unitfield.set(self.units.index(st.unit))
    def validate_fields(self):
        "Returns True or None."
        if self.deptfield.f is None: return None
        if self.unitfield.f is None: return None
        if len(self.snamefield.f)==0: return None
        if len(self.manufield.f)==0: return None
        if len(self.namefield.f)==0: return None
        return True
    def get_abv(self):
        try:
            return float(self.abvfield.f)
        except:
            return None
    def update_model(self,model):
        model.manufacturer=self.manufield.f
        model.name=self.namefield.f
        model.shortname=self.snamefield.f
        model.abv=self.get_abv()
        model.department=self.deptfield.read()
        model.unit=self.unitfield.read()
    def validate_manufacturer(self,s,c):
        if self.mode==2: return s
        t=s[:c+1]
        l=td.stocktype_completemanufacturer(t)
        if len(l)>0: return l[0]
        # If a string one character shorter matches then we know we
        # filled it in last time, so we should return the string with
        # the rest chopped off rather than just returning the whole
        # thing unedited.
        if len(td.stocktype_completemanufacturer(t[:-1]))>0:
            return t
        return s
    def validate_name(self,s,c):
        if self.mode==2: return s
        t=s[:c+1]
        l=td.stocktype_completename(self.manufield.f,t)
        if len(l)>0: return l[0]
        if len(td.stocktype_completename(self.manufield.f,t[:-1]))>0:
            return t
        return s
    def defaultname(self):
        if self.mode==2: return
        l=td.stocktype_completename(self.manufield.f,"")
        if len(l)==1:
            self.namefield.set(l[0])
        self.namefield.focus()
    def lookupname(self):
        # Called when Enter is pressed on the Name field.  Fills in
        # other fields if there's a match with an existing item.
        # When the StockType object is loaded, we need to make sure it
        # re-uses the Department and StockUnit objects we loaded
        # earlier for the ui.listfield() fields.  Add them to the
        # session here so it knows about them.
        for d in self.depts:
            td.s.add(d)
        for u in self.units:
            td.s.add(u)
        l=td.s.query(StockType).\
            filter_by(manufacturer=self.manufield.f).\
            filter_by(name=self.namefield.f).\
            all()
        if len(l)>0:
            self.fill_fields(l[0])
            self.confirmbutton.focus()
        else:
            if len(self.manufield.f)+len(self.namefield.f)<25:
                self.snamefield.set("%s %s"%
                                    (self.manufield.f,self.namefield.f))
            self.snamefield.focus()
    def finish_save(self):
        self.dismiss()
        st=StockType()
        self.update_model(st)
        td.s.add(st)
        self.func(st)
    def finish_mode1(self):
        # If there's an exact match then return the existing stock
        # type.  Otherwise pop up a confirmation box asking whether we
        # can create a new one.
        if self.validate_fields() is None:
            ui.infopopup(["You must fill in all the fields (except ABV, "
                          "which should be left blank for non-alcoholic "
                          "stock types)."],title="Error")
            return
        td.s.add(self.unitfield.read())
        td.s.add(self.deptfield.read())
        st=td.s.query(StockType).\
            filter_by(manufacturer=self.manufield.f).\
            filter_by(name=self.namefield.f).\
            filter_by(shortname=self.snamefield.f).\
            filter_by(abv=self.get_abv()).\
            filter_by(unit=self.unitfield.read()).\
            filter_by(department=self.deptfield.read()).\
            first()
        # Confirmation box time...
        if st is None:
            if self.allownew:
                ui.infopopup(["There's no existing stock type that matches the "
                              "details you've entered.  Press Cash/Enter to "
                              "create a new stock type, or Clear to go back."],
                             title="New Stock Type?",keymap={
                        keyboard.K_CASH: (self.finish_save,None,True)})
            else:
                ui.infopopup(["There is no stock type that matches the "
                              "details you have entered."],
                              title="No Match")
                return
        else:
            self.dismiss()
            self.func(st)
    def finish_mode2(self):
        if self.validate_fields() is None:
            ui.infopopup(["You are not allowed to leave any field other "
                          "than ABV blank."],title="Error")
        else:
            self.dismiss()
            self.st=td.s.merge(self.st)
            self.update_model(self.st)

# XXX should probably convert this to take a StockItem object rather
# than a stock ID at some point
def stockinfo_linelist(sn):
    s=td.s.query(StockItem).get(sn)
    l=[]
    l.append(s.stocktype.format()+" - %d"%s.id)
    l.append("Sells for %s%s/%s.  "
             "%s %ss used; %s %ss remaining."%(
            tillconfig.currency,s.saleprice,s.stocktype.unit.name,
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
    ui.linepopup(stockinfo_linelist(sn),
                 title="Stock Item %d"%sn,
                 dismiss=keyboard.K_CASH,
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
        lines=ui.table([("%d"%x.id,x.stocktype.format(maxw=40))
                        for x in sinfo]).format(' r l ')
        sl=[(x,self.stock_item_selected,(y.id,))
            for x,y in zip(lines,sinfo)]
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
        self.sd=sd
        self.addstr(4,21,sd.stocktype.format(maxw=40))
        self.create_extra_fields()
    def create_extra_fields(self):
        self.addstr(5,2,"Annotation type:")
        self.addstr(7,2,"Annotation:")
        annlist=['location','memo','vent']
        anndict={'location':'Location',
                 'memo':'Memo',
                 'vent':'Vented'}
        self.anntypefield=ui.listfield(5,21,30,annlist,anndict,keymap={
                keyboard.K_CLEAR:(self.dismiss,None)})
        self.annfield=ui.editfield(8,2,60,keymap={
                keyboard.K_CASH: (self.finish,None)})
        ui.map_fieldlist([self.anntypefield,self.annfield])
        self.anntypefield.set(0)
        self.anntypefield.focus()
    def finish(self):
        anntype=self.anntypefield.read()
        if anntype is None or anntype=="":
            ui.infopopup(["You must choose an annotation type!"],title="Error")
            return
        annotation=self.annfield.f
        td.s.add(self.sd)
        td.s.add(
            StockAnnotation(stockitem=self.sd,atype=anntype,text=annotation))
        td.s.flush()
        self.dismiss()
        ui.infopopup(["Recorded annotation against stock item %d (%s)."%(
            self.sd.id,self.sd.stocktype.format())],
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

class reprice_stockitem(ui.dismisspopup):
    """Re-price a particular stock item.  Call func when done.

    """
    def __init__(self,stockitem,func):
        td.s.add(stockitem)
        self.stockitem=stockitem
        self.func=func
        ui.dismisspopup.__init__(
            self,5,30,title="Re-price stock item %d"%stockitem.id,
            colour=ui.colour_line)
        self.addstr(2,2,"New price:")
        self.field=ui.editfield(
            2,13,5,validate=ui.validate_float,
            keymap={keyboard.K_CASH: (self.finish,None)})
        self.field.focus()
    def finish(self):
        if self.field.f is None or self.field.f=='': return
        number=Decimal(self.field.f).quantize(penny)
        self.dismiss()
        td.s.add(self.stockitem)
        self.stockitem.saleprice=number
        td.s.flush()
        self.func()

class reprice_stocktype(ui.listpopup):
    """Allow all items of stock of a particular type to be re-priced.

    Options include:
    1. Set all items to the highest price
    2. Set all items to the lowest price
    3. Set all items to the guide price

    """
    def __init__(self,stn):
        """
        We are passed a StockType that may not be in the current session.

        """
        td.s.add(stn)
        name=stn.format()
        self.sl=td.s.query(StockItem).filter(StockItem.stocktype==stn).\
            filter(StockItem.finished==None).order_by(StockItem.id).all()
        if len(self.sl)==0:
            ui.infopopup(["There are no items of %s in stock "
                          "at the moment."%name],title="Error")
            return
        self.updatedl()
        ui.listpopup.__init__(self,self.dl,title=name,w=45,header=[
                "Please choose from the following options:",
                "1. Set prices to match the highest price",
                "2. Set prices to match the guide price",
                "3. Set prices to match the lowest price","",
                "Alternatively, press Cash/Enter to re-price "
                "individual stock items.","",self.header])
    def guideprice(self,item):
        if item.costprice is None: return None
        return tillconfig.priceguess(item.stocktype.dept_id,
                                     item.costprice/item.stockunit.size,
                                     item.stocktype.abv)
    def updatedl(self):
        # For each item of stock, we want:
        # Stock ID
        # Cost price
        # Guide price
        # Current price
        self.minprice=None
        self.maxprice=None
        td.s.add_all(self.sl)
        for i in self.sl:
            self.minprice=(i.saleprice if self.minprice is None
                           else min(self.minprice,i.saleprice))
            self.maxprice=(i.saleprice if self.maxprice is None
                           else max(self.maxprice,i.saleprice))
        log.debug("maxprice=%s minprice=%s",self.maxprice,self.minprice)
        f=ui.tableformatter(' r  r  r  r ')
        self.header=ui.tableline(f,["StockID","Cost","Guide","Sale"])
        self.dl=[ui.tableline(f,[str(x.id),
                                 tillconfig.fc(x.costprice),
                                 tillconfig.fc(self.guideprice(x)),
                                 tillconfig.fc(x.saleprice)],
                              userdata=x)
                 for x in self.sl]
    def update(self):
        self.updatedl()
        self.s.set(self.dl)
        self.s.redraw()
    def setall(self,price):
        for i in self.dl:
            td.s.add(i.userdata)
            i.userdata.saleprice=price
        td.s.flush()
        self.update()
    def setguide(self):
        for i in self.dl:
            td.s.add(i.userdata)
            g=self.guideprice(i.userdata)
            if g: i.userdata.saleprice=Decimal(g).quantize(penny)
        td.s.flush()
        self.update()
    def keypress(self,k):
        if k==keyboard.K_ONE:
            self.setall(self.maxprice)
        elif k==keyboard.K_TWO:
            self.setguide()
        elif k==keyboard.K_THREE:
            self.setall(self.minprice)
        elif k==keyboard.K_CASH:
            reprice_stockitem(self.dl[self.s.cursor].userdata,
                              self.update)
        else:
            ui.listpopup.keypress(self,k)

def inconsistent_prices_menu():
    # Make a list of stocktypes with inconsistent prices
    # The lazyload options are to avoid problems with the "group_by" clause
    stl=td.s.query(StockType).join(StockItem).\
        filter(StockItem.finished==None).\
        options(lazyload("department")).\
        options(lazyload("unit")).\
        group_by(StockType).\
        having(func.count(func.distinct(StockItem.saleprice))>1).\
        all()
    ml=[(x.format(),reprice_stocktype,(x,)) for x in stl]
    ui.menu(ml,blurb="The following stock types have inconsistent pricing.  "
            "Choose a stock type to edit its pricing.",title="Stock types "
            "with inconsistent prices")
