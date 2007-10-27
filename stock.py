# -*- coding: iso-8859-1 -*-

"""Useful routines for dealing with stock"""

import ui,td,keyboard,tillconfig,stocklines,department

import logging
log=logging.getLogger()

def abvstr(abv):
    if abv is None: return ""
    return " (%0.1f%% ABV)"%abv

def format_stock(sd,maxw=None):
    d="%(manufacturer)s %(name)s%(abvstr)s"%sd
    if maxw is not None:
        if len(d)>maxw:
            d="%(manufacturer)s %(name)s"%sd
        if len(d)>maxw:
            d="%(shortname)s%(abvstr)s"%sd
        if len(d)>maxw:
            d=sd['shortname']
        if len(d)>maxw:
            d=d[:maxw]
    return d

def format_stocktype(stn,maxw=None):
    (dept,manufacturer,name,shortname,abv,unit)=td.stocktype_info(stn)
    return format_stock({'manufacturer':manufacturer,'name':name,
                         'shortname':shortname,'abvstr':abvstr(abv)},maxw)

# Select/modify a stock type.  Has two modes:
# 1) Select a stock type. Auto-completes fields as they are typed at,
# hopefully to find a match with an existing stock type.  (After
# selecting manufacturer/name, other fields are filled in if possible,
# but can still be edited.)  If, when form is completed, there is no
# match with an existing stock type, a new stock type is created.
# (This is the only way to create stock types.)
# 2) Modify a stock type.  Allows all details of an existing stock
# type to be changed.
# Has major warnings - should only be used for correcting minor typos!
class stocktype(ui.basicpopup):
    def __init__(self,func,default=None,mode=1):
        self.func=func
        self.st=default
        self.mode=mode
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
        ui.basicpopup.__init__(self,15,48,title=title,
                               colour=ui.colour_input,
                               cleartext="Press Clear to go back")
        win=self.pan.window()
        win.addstr(2,2,blurb1)
        win.addstr(3,2,blurb2)
        win.addstr(5,2,"Manufacturer:")
        win.addstr(6,2,"        Name:")
        win.addstr(7,2,"  Short name:")
        win.addstr(8,2,"  Department:")
        win.addstr(8,38,"ABV:")
        win.addstr(9,2,"        Unit:")
        win.addstr(13,2,"Note: 'Short Name' is printed on receipts.")
        km={keyboard.K_CLEAR: (self.dismiss,None,False)}
        self.manufield=ui.editfield(win,5,16,30,
                                    validate=self.validate_manufacturer,
                                    keymap=km)
        self.namefield=ui.editfield(win,6,16,30,validate=self.validate_name,
                                    keymap=km)
        self.snamefield=ui.editfield(win,7,16,25,keymap=km)
        self.deptfield=ui.listfield(win,8,16,20,self.deptlist,d=dict(depts),
                                    keymap=km,readonly=(mode==2))
        self.abvfield=ui.editfield(win,8,42,4,validate=ui.validate_float,
                                   keymap=km)
        self.unitfield=ui.listfield(win,9,16,30,self.unitlist,d=dict(units),
                                    keymap=km,readonly=(mode==2))
        self.confirmbutton=ui.buttonfield(win,11,15,20,prompt,keymap=km)
        # set not to dismiss so that if the input is not valid we
        # can go back to editing
        if mode==1:
            self.confirmbutton.keymap[keyboard.K_CASH]=(
                self.finish_mode1,None,False)
        else:
            self.confirmbutton.keymap[keyboard.K_CASH]=(
                self.finish_mode2,None,False)
        fl=[self.manufield,self.namefield,self.snamefield,self.deptfield,
            self.abvfield,self.unitfield,self.confirmbutton]
        ui.map_fieldlist(fl)
        if default is not None:
            self.fill_fields(default)
        if mode==1:
            # Some overrides; we want to be called when Enter is
            # pressed on the manufacturer field so we can pre-fill the
            # name field if possible, and on the name field so we can
            # pre-fill the other fields if possible.  Only in mode 1;
            # in mode 2 we're just editing
            self.manufield.keymap[keyboard.K_CASH]=(self.defaultname,None,True)
            self.namefield.keymap[keyboard.K_CASH]=(self.lookupname,None,True)
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
            ui.infopopup(["There's no existing stock type that matches the "
                          "details you've entered.  Press Cash/Enter to "
                          "create a new stock type, or Clear to go back."],
                         title="New Stock Type?",keymap={
                keyboard.K_CASH: (self.finish_save,None,True)})
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

# What do we want to show about a stock item?
# Number
# Manufacturer, name, abv
# Short name
# How much it cost
# How much it sells for
# Delivery information (supplier, date, docid)
# Date first sold
# Date most recently sold
# Date taken off
# Quantity remaining/unaccounted
# Waste, by type
# Finish reason

class stockinfo(ui.basicwin):
    """This is a widget that displays information on a stock item.  It
    is 15 lines by 70 characters.
    """
    def __init__(self,win,y,x,sn=None):
        self.y=y
        self.x=x
        ui.basicwin.__init__(self,takefocus=False)
        self.win=win
        self.set(sn)
    def set(self,sn,qty=1):
        # Erase the display first...
        y=self.y
        x=self.x
        for i in range(y,y+15):
            self.win.addstr(i,self.x,' '*70)
        if sn is None: return
        l=stockinfo_linelist(sn)
        for i in l:
            self.win.addstr(y,x,i)
            y=y+1

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

def stockinfo_popup(sn):
    keymap={ord('l'):(annotate_location,(sn,),False)}
    ui.linepopup(stockinfo_linelist(sn),
                 title="Stock Item %d"%sn,
                 dismiss=keyboard.K_CASH,
                 colour=ui.colour_info,keymap=keymap)

class annotate(ui.basicpopup):
    """This class permits annotations to be made to stock items.  If
    it is called with a stockid then the stockid field is pre-filled;
    otherwise a numeric entry may be made, or a pop-up list may be
    used to select the stockid.

    """
    def __init__(self,stockid=None):
        ui.basicpopup.__init__(self,11,64,"Annotate Stock",
                               "Press Clear to go back",ui.colour_input)
        self.win=self.pan.window()
        self.win.addstr(2,2,"Press stock line key or enter stock number.")
        self.win.addstr(3,2,"       Stock item:")
        stockfield_km={keyboard.K_CLEAR: (self.dismiss,None,False),
                       keyboard.K_CASH: (self.stock_enter_key,None,False)}
        for i in keyboard.lines:
            stockfield_km[i]=(stocklines.linemenu,(i,self.stock_line),False)
        self.stockfield=ui.editfield(self.win,3,21,30,
                                     validate=ui.validate_int,
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
        self.win.addstr(4,21,format_stock(sd,maxw=40))
        self.create_extra_fields()
    def create_extra_fields(self):
        self.win.addstr(5,2,"Annotation type:")
        self.win.addstr(7,2,"Annotation:")
        annlist=['location','memo','vent']
        anndict={'location':'Location',
                 'memo':'Memo',
                 'vent':'Vented'}
        anntypefield_km={keyboard.K_CLEAR:(self.dismiss,None,True)}
        self.anntypefield=ui.listfield(self.win,5,21,30,annlist,anndict,
                                       keymap=anntypefield_km)
        annfield_km={keyboard.K_CLEAR:(self.anntypefield.focus,None,True),
                     keyboard.K_UP:(self.anntypefield.focus,None,True),
                     keyboard.K_CASH: (self.finish,None,False)}
        self.annfield=ui.editfield(self.win,8,2,60,keymap=annfield_km)
        self.anntypefield.nextfield=self.annfield
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

class annotate_location(ui.basicpopup):
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
                          "not yet been confirmed.  You can't record waste "
                          "against it until the whole delivery is confirmed."%(
                sd['stockid'])],
                         title="Error")
            return
        ui.basicpopup.__init__(self,7,64,"Stock Location",
                               "Press Clear to go back",ui.colour_input)
        self.win=self.pan.window()
        self.stockid=stockid
        self.win.addstr(2,2,format_stock(sd,maxw=60))
        self.win.addstr(4,2,"Enter location:")
        self.locfield=ui.editfield(self.win,4,18,40,keymap={
            keyboard.K_CASH: (self.finish,None,False)})
        self.locfield.focus()
    def finish(self):
        annotation=self.locfield.f
        td.stock_annotate(self.stockid,'location',annotation)
        self.dismiss()
