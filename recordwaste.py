import ui,td,keyboard,stock,stocklines,department

class popup(ui.basicpopup):
    """This popup talks the user through the process of recording
    waste against a stock item or a stock line.  If a stock item is
    chosen then waste is recorded against the amount still in stock in
    that particular item; if a stock line is chosen then waste is
    recorded against the stock on display for that line.  A series of
    prompts are issued; the Clear key will kill the whole window and
    will not allow backtracking.

    """
    def __init__(self):
        ui.basicpopup.__init__(self,10,70,title="Record Waste",
                               cleartext="Press Clear to go back",
                               colour=ui.colour_input)
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
            return
        self.isline=True
        self.stocklineid=stocklineid
        self.name=name
        # Find out how much is available to sell by trying to sell 0 items
        sell,unallocated,snd,remain=stocklines.calculate_sale(stocklineid,0)
        self.ondisplay=remain[0]
        if self.ondisplay<1:
            self.dismiss()
            ui.infopopup(
                ["There is no stock on display for '%s'.  If you want to "
                 "record waste against items still in storage, you have "
                 "to enter the stock number instead of pressing the line "
                 "key."%name],title="No stock on display")
            return
        self.stockfield.set(name)
        self.win.addstr(4,21,"%d items on display"%self.ondisplay)
        self.create_extra_fields()
    def stock_dept_selected(self,dept):
        sl=td.stock_search(exclude_stock_on_sale=False,dept=dept)
        sinfo=td.stock_info(sl)
        lines=ui.table([("%(stockid)d"%x,stock.format_stock(x,maxw=40))
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
                          "not yet been confirmed.  You can't record waste "
                          "against it until the whole delivery is confirmed."%(
                sd['stockid'])],
                         title="Error")
            return
        self.isline=False
        self.sd=sd
        self.win.addstr(4,21,stock.format_stock(sd,maxw=40))
        self.create_extra_fields()
    def create_extra_fields(self):
        self.win.addstr(5,2,"Waste description:")
        self.win.addstr(6,2,"    Amount wasted:")
        if self.isline:
            wastelist=['missing','taste','damaged','ood','freebie']
        else:
            wastelist=['cellar','pullthru','taster','taste','damaged',
                       'ood','freebie','missing','driptray']
        wastedict={'pullthru':'Pulled through',
                   'cellar':'Cellar work',
                   'taster':'Free taster',
                   'taste':'Bad taste',
                   'damaged':'Damaged',
                   'ood':'Out of date',
                   'freebie':'Free drink',
                   'missing':'Gone missing',
                   'driptray':'Drip tray'}
        wastedescfield_km={keyboard.K_CLEAR:(self.dismiss,None,True)}
        self.wastedescfield=ui.listfield(self.win,5,21,30,wastelist,wastedict,
                                         keymap=wastedescfield_km)
        amountfield_km={keyboard.K_CLEAR:(self.wastedescfield.focus,None,True),
                        keyboard.K_UP:(self.wastedescfield.focus,None,True),
                        keyboard.K_CASH: (self.finish,None,False)}
        self.amountfield=ui.editfield(self.win,6,21,4,
                                      validate=ui.validate_float,
                                      keymap=amountfield_km)
        self.wastedescfield.nextfield=self.amountfield
        if self.isline:
            self.win.addstr(6,26,'items')
        else:
            self.win.addstr(6,26,self.sd['unitname']+'s')
        self.wastedescfield.set(0)
        self.wastedescfield.focus()
    def finish(self):
        waste=self.wastedescfield.read()
        if waste is None or waste=="":
            ui.infopopup(["You must enter a waste description!"],title="Error")
            return
        if self.amountfield.f=="":
            ui.infopopup(["You must enter an amount!"],title="Error")
            return
        amount=float(self.amountfield.f)
        if amount<=0.0:
            ui.infopopup(["You must enter an amount greater than zero!"],
                         title=Error)
            self.amountfield.set("")
            return
        if self.isline:
            amount=int(amount)
            if amount>self.ondisplay:
                ui.infopopup(["You asked to record waste of %d items, but "
                              "there are only %d on display."%(
                    amount,self.ondisplay)],
                             title="Error")
                return
            sell,unallocated,snd,remaining=stocklines.calculate_sale(
                self.stocklineid,amount)
            for stockid,qty in sell:
                # Call to td.stock_recordwaste WITH NO UPDATE OF displayqty
                # in stockonsale
                td.stock_recordwaste(stockid,waste,qty,False)
            self.dismiss()
            ui.infopopup(["Recorded %d items against stock line %s."%(
                amount,self.name)],title="Waste Recorded",
                         dismiss=keyboard.K_CASH,colour=ui.colour_info)
        else:
            td.stock_recordwaste(self.sd['stockid'],waste,amount,True)
            self.dismiss()
            ui.infopopup(["Recorded %0.1f %ss against stock item %d (%s)."%(
                amount,self.sd['unit'],self.sd['stockid'],
                stock.format_stock(self.sd))],
                         title="Waste Recorded",dismiss=keyboard.K_CASH,
                         colour=ui.colour_info)
