"""Useful routines for dealing with stock.

"""

import ui,td,keyboard,tillconfig,stocklines,department,hashlib,stock

import logging
log=logging.getLogger()

def abvstr(abv):
    if abv is None: return ""
    return " (%0.1f%% ABV)"%abv

def checkdigits(stockid):
    """
    Return three digits derived from a stock ID number.  These digits
    can be printed on stock labels; knowledge of the digits can be
    used to confirm that a member of staff really does have a
    particular item of stock in front of them.

    """
    a=hashlib.sha1("quicktill-%d-quicktill"%stockid)
    return str(int(a.hexdigest(),16))[-3:]

def format_stock(sd,maxw=None):
    """
    maxw can be an integer specifying the maximum number of
    characters, or a function with a single string argument that
    returns True if the string will fit.  Note that if maxw is a
    function, we do not _guarantee_ to return a string that will fit.

    """
    d="%(manufacturer)s %(name)s%(abvstr)s"%sd
    if maxw is None: return d
    if isinstance(maxw,int):
        if len(d)>maxw:
            d="%(manufacturer)s %(name)s"%sd
        if len(d)>maxw:
            d="%(shortname)s%(abvstr)s"%sd
        if len(d)>maxw:
            d=sd['shortname']
        if len(d)>maxw:
            d=d[:maxw]
    else:
        if not maxw(d):
            d="%(manufacturer)s %(name)s"%sd
        if not maxw(d):
            d="%(shortname)s%(abvstr)s"%sd
        if not maxw(d):
            d=sd['shortname']
    return d

def format_stocktype(stn,maxw=None):
    (dept,manufacturer,name,shortname,abv,unit)=td.stocktype_info(stn)
    return format_stock({'manufacturer':manufacturer,'name':name,
                         'shortname':shortname,'abvstr':abvstr(abv)},maxw)

def format_transline(transline):
    (trans,items,amount,dept,deptstr,stockref,
     transcode,text,vatband)=td.trans_getline(transline)
    if text is not None:
        ss=text
    elif stockref is not None:
        (qty,removecode,stockid,manufacturer,name,shortname,abv,
         unitname)=td.stock_fetchline(stockref)
        abvs=stock.abvstr(abv)
        qty=qty/items
        qtys=tillconfig.qtystring(qty,unitname)
        ss="%s %s%s %s"%(manufacturer,name,abvs,qtys)
    else:
        ss=deptstr
    astr=("%d @ %s = %s"%(items,tillconfig.fc(amount),
                            tillconfig.fc(items*amount)) if items!=1
            else "%s"%tillconfig.fc(items*amount))
    if amount==0.0: astr=""
    return (ss,astr)

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
        self.func=func
        self.st=default
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
            raise "Bad mode"
        depts=td.department_list()
        units=td.unittype_list()
        self.deptlist=[x[0] for x in depts]
        self.unitlist=[x[0] for x in units]
        ui.dismisspopup.__init__(self,15,48,title=title,colour=ui.colour_input)
        self.addstr(2,2,blurb1)
        self.addstr(3,2,blurb2)
        self.addstr(5,2,"Manufacturer:")
        self.addstr(6,2,"        Name:")
        self.addstr(7,2,"  Short name:")
        self.addstr(8,2,"  Department:")
        self.addstr(8,38,"ABV:")
        self.addstr(9,2,"        Unit:")
        self.addstr(13,2,"Note: 'Short Name' is printed on receipts.")
        self.manufield=ui.editfield(
            5,16,30,validate=self.validate_manufacturer,
            keymap={keyboard.K_CLEAR: (self.dismiss,None)})
        self.namefield=ui.editfield(
            6,16,30,validate=self.validate_name)
        self.snamefield=ui.editfield(7,16,25)
        self.deptfield=ui.listfield(8,16,20,self.deptlist,
                                    d=dict(depts),readonly=(mode==2))
        self.abvfield=ui.editfield(8,42,4,validate=ui.validate_float)
        self.unitfield=ui.listfield(9,16,30,self.unitlist,
                                    d=dict(units),readonly=(mode==2))
        self.confirmbutton=ui.buttonfield(11,15,20,prompt,keymap={
                keyboard.K_CASH: (self.finish_mode1 if mode==1
                                  else self.finish_mode2, None)})
        ui.map_fieldlist(
            [self.manufield,self.namefield,self.snamefield,self.deptfield,
             self.abvfield,self.unitfield,self.confirmbutton])
        if default is not None:
            self.fill_fields(default)
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
        (dept,manufacturer,name,shortname,abv,unit)=td.stocktype_info(st)
        self.manufield.set(manufacturer)
        self.namefield.set(name)
        self.snamefield.set(shortname)
        self.deptfield.set(self.deptlist.index(dept))
        if abv is None: self.abvfield.set(None)
        else: self.abvfield.set("%0.1f"%abv)
        self.unitfield.set(self.unitlist.index(unit))
    def pack_fields(self):
        if self.deptfield.f is None: return None
        if self.unitfield.f is None: return None
        if len(self.snamefield.f)==0: return None
        if len(self.manufield.f)==0: return None
        if len(self.namefield.f)==0: return None
        # Argh, special handling for the ABV field
        try:
            abv=float(self.abvfield.f)
        except:
            abv=None
        return (
            self.deptlist[self.deptfield.f],self.manufield.f,
            self.namefield.f,self.snamefield.f,
            abv,self.unitlist[self.unitfield.f])
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
        l=td.stocktype_fromnames(self.manufield.f,self.namefield.f)
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
        sn=td.stocktype_new(*self.pack_fields())
        self.func(sn)
    def finish_mode1(self):
        # If there's an exact match then return the existing stock
        # type.  Otherwise pop up a confirmation box asking whether we
        # can create a new one.
        pf=self.pack_fields()
        if pf is None:
            ui.infopopup(["You must fill in all the fields (except ABV, "
                          "which should be left blank for non-alcoholic "
                          "stock types)."],title="Error")
            return
        st=td.stocktype_fromall(*pf)
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
        pf=self.pack_fields()
        if pf is None:
            ui.infopopup(["You are not allowed to leave any field other "
                          "than ABV blank."],title="Error")
        else:
            self.dismiss()
            td.stocktype_update(self.st,*pf)

def stockinfo_linelist(sn,qty=1):
    l=[]
    sd=td.stock_info([sn])[0]
    sd['stockid']=sn
    sx=td.stock_extrainfo(sn)
    sd.update(sx)
    if qty==1:
        sd['saleunit']=sd['unitname']
    elif qty==0.5:
        sd['saleunit']="half %(unitname)s"%sd
    else: sd['saleunit']="%f %s"%(qty,sd['unitname'])
    sd['deliverydate']=ui.formatdate(sd['deliverydate'])
    sd['bestbefore']=ui.formatdate(sd['bestbefore'])
    sd['firstsale']=ui.formattime(sd['firstsale'])
    sd['lastsale']=ui.formattime(sd['lastsale'])
    sd['onsale']=ui.formattime(sd['onsale'])
    sd['finished']=ui.formattime(sd['finished'])
    sd['currency']=tillconfig.currency
    l.append(format_stock(sd)+" - %(stockid)d"%sd)
    l.append("Sells for %(currency)s%(saleprice)0.2f/%(unitname)s.  "
             "%(used)0.1f %(unitname)ss used; "
             "%(remaining)0.1f %(unitname)ss remaining."%sd)
    l.append("")
    l.append("Delivered %(deliverydate)s by %(suppliername)s"%sd)
    if sd['bestbefore']!="":
        l.append("Best Before %(bestbefore)s"%sd)
    if sd['onsale']!="":
        l.append("Put on sale %(onsale)s"%sd)
    if sd['firstsale']!="":
        l.append("First sale: %(firstsale)s  Last sale: %(lastsale)s"%sd)
    if sd['finished']!="":
        l.append("Finished %(finished)s; %(finishdescription)s"%sd)
    l.append("")
    for i in sd['stockout']:
        l.append("%s: %0.1f"%(i[1],i[2]))
    sa=td.stock_annotations(sn)
    if len(sa)>0:
        l.append("Annotations:")
    for desc,time,text in sa:
        l.append("%s: %s: %s"%(time,desc,text))
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
        name,qty,dept,pullthru,menukey,stocklineid,location,capacity=line
        if capacity is None:
            # Look up the stock number, put it in the field, and invoke
            # stock_enter_key
            sl=td.stock_onsale(stocklineid)
            if sl==[]:
                ui.infopopup(["There is nothing on sale on %s."%name],
                             title="Error")
            else:
                self.stockfield.set(str(sl[0][0]))
                self.stock_enter_key()
    def stock_dept_selected(self,dept):
        sl=td.stock_search(exclude_stock_on_sale=False,dept=dept)
        sinfo=td.stock_info(sl)
        lines=ui.table([("%(stockid)d"%x,format_stock(x,maxw=40))
                        for x in sinfo]).format(' r l ')
        sl=[(x,self.stock_item_selected,(y['stockid'],))
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
        sd=td.stock_info([sn])
        if sd==[]:
            ui.infopopup(["Stock number %d does not exist."%sn],
                         title="Error")
            return
        sd=sd[0]
        if sd['deliverychecked'] is False:
            ui.infopopup(["Stock number %d is part of a delivery that has "
                          "not yet been confirmed.  You can't annotate "
                          "it until the whole delivery is confirmed."%(
                sd['stockid'])],
                         title="Error")
            return
        self.sd=sd
        self.addstr(4,21,format_stock(sd,maxw=40))
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
        td.stock_annotate(self.sd['stockid'],anntype,annotation)
        self.dismiss()
        ui.infopopup(["Recorded annotation against stock item %d (%s)."%(
            self.sd['stockid'],format_stock(self.sd))],
                     title="Annotation Recorded",dismiss=keyboard.K_CASH,
                     colour=ui.colour_info)

class annotate_location(ui.dismisspopup):
    """A special, simplified version of the stock annotation popup, that
    only allows the location to be set.  Must be called with a stock ID;
    doesn't permit stock ID entry.

    """
    def __init__(self,stockid):
        sd=td.stock_info([stockid])
        if sd==[]:
            ui.infopopup(["Stock number %d does not exist."%sn],
                         title="Error")
            return
        sd=sd[0]
        if sd['deliverychecked'] is False:
            ui.infopopup(["Stock number %d is part of a delivery that has "
                          "not yet been confirmed.  You can't annotate "
                          "it until the whole delivery is confirmed."%(
                sd['stockid'])],
                         title="Error")
            return
        ui.dismisspopup.__init__(self,7,64,"Stock Location",
                                 colour=ui.colour_input)
        self.stockid=stockid
        self.addstr(2,2,format_stock(sd,maxw=60))
        self.addstr(4,2,"Enter location:")
        self.locfield=ui.editfield(4,18,40,keymap={
            keyboard.K_CASH: (self.finish,None),
            keyboard.K_CLEAR: (self.dismiss,None)})
        self.locfield.focus()
    def finish(self):
        annotation=self.locfield.f
        td.stock_annotate(self.stockid,'location',annotation)
        self.dismiss()

class reprice_stockitem(ui.dismisspopup):
    """Re-price a particular stock item.  Call func when done.

    """
    def __init__(self,stockid,func):
        self.stockid=stockid
        self.func=func
        ui.dismisspopup.__init__(
            self,5,30,title="Re-price stock item %d"%stockid,
            colour=ui.colour_line)
        self.addstr(2,2,"New price:")
        self.field=ui.editfield(
            2,13,5,validate=ui.validate_float,
            keymap={keyboard.K_CASH: (self.finish,None)})
        self.field.focus()
    def finish(self):
        if self.field.f is None or self.field.f=='': return
        number=float(self.field.f)
        self.dismiss()
        td.stock_reprice(self.stockid,number)
        self.func()

class reprice_stocktype(ui.listpopup):
    """Allow all items of stock of a particular type to be re-priced.

    Options include:
    1. Set all items to the highest price
    2. Set all items to the lowest price
    3. Set all items to the guide price

    """
    def __init__(self,stn):
        name=format_stocktype(stn)
        self.sl=td.stock_search(stocktype=stn,exclude_stock_on_sale=False)
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
    def updatedl(self):
        si=td.stock_info(self.sl)
        # For each item of stock, we want:
        # Stock ID
        # Cost price
        # Guide price
        # Current price
        self.minprice=None
        self.maxprice=None
        for i in si:
            i['guideprice']=(None if i['costprice'] is None
                             else tillconfig.priceguess(
                    i['dept'],i['costprice']/i['size'],i['abv']))
            self.minprice=(i['saleprice'] if self.minprice is None
                           else min(self.minprice,i['saleprice']))
            self.maxprice=(i['saleprice'] if self.maxprice is None
                           else max(self.maxprice,i['saleprice']))
        log.debug("maxprice=%s minprice=%s",self.maxprice,self.minprice)
        f=ui.tableformatter(' r  r  r  r ')
        self.header=ui.tableline(f,["StockID","Cost","Guide","Sale"])
        self.dl=[ui.tableline(f,[str(x['stockid']),
                                 tillconfig.fc(x['costprice']),
                                 tillconfig.fc(x['guideprice']),
                                 tillconfig.fc(x['saleprice'])],
                              userdata=x)
                 for x in si]
    def update(self):
        self.updatedl()
        self.s.set(self.dl)
        self.s.redraw()
    def setall(self,price):
        for i in self.dl:
            log.debug("Reprice %d to %s",i.userdata['stockid'],price)
            td.stock_reprice(i.userdata['stockid'],price)
        self.update()
    def setguide(self):
        for i in self.dl:
            if i.userdata['guideprice']:
                td.stock_reprice(i.userdata['stockid'],i.userdata['guideprice'])
        self.update()
    def keypress(self,k):
        if k==keyboard.K_ONE:
            self.setall(self.maxprice)
        elif k==keyboard.K_TWO:
            self.setguide()
        elif k==keyboard.K_THREE:
            self.setall(self.minprice)
        elif k==keyboard.K_CASH:
            reprice_stockitem(self.dl[self.s.cursor].userdata['stockid'],
                              self.update)
        else:
            ui.listpopup.keypress(self,k)

def inconsistent_prices_menu():
    stl=td.stocktype_search_inconsistent_prices()
    ml=[(format_stocktype(x),reprice_stocktype,(x,)) for x in stl]
    ui.menu(ml,blurb="The following stock types have inconsistent pricing.  "
            "Choose a stock type to edit its pricing.",title="Stock types "
            "with inconsistent prices")
