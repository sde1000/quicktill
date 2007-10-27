import ui,td,keyboard

class popup(ui.basicpopup):
    def __init__(self):
        ui.basicpopup.__init__(self,10,70,title="Record Waste",
                               cleartext="Press Clear to go back",
                               colour=ui.colour_input)
        win=self.pan.window()
        win.addstr(2,2,"Press stock line key or enter stock number.")
        win.addstr(3,2,"       Stock item:")
        win.addstr(5,2,"Waste description:")
        win.addstr(6,2,"    Amount wasted:")
        wastelist=['pullthru','cellar','taste','damaged','ood']
        wastedict={'pullthru':'Pulled through',
                   'cellar':'Cellar work',
                   'taste':'Bad taste',
                   'damaged':'Damaged',
                   'ood':'Out of date'}
        stockfield_km={keyboard.K_CLEAR: (self.dismiss,None,False),
                       keyboard.K_CASH: (self.stock_enter_key,None,False)}
        for i in keyboard.lines:
            stockfield_km[i]=(ui.linemenu,(keyboard.lines[i],self.stock_line),False)
        self.stockfield=ui.editfield(win,3,21,10,validate=ui.validate_int,
                                     keymap=stockfield_km)
        self.stockdescfield=ui.editfield(win,4,21,40)
        wastefield_km={keyboard.K_CLEAR: (self.focus_stockfield,None,True)}
        self.wastedescfield=ui.listfield(win,5,21,30,wastelist,wastedict,
                                         keymap=wastefield_km)
        amountfield_km={keyboard.K_CLEAR: (self.wastedescfield.focus,None,True),
                        keyboard.K_CASH: (self.finish,None,False)}
        self.amountfield=ui.editfield(win,6,21,4,validate=ui.validate_float,
                                      keymap=amountfield_km)
        self.wastedescfield.nextfield=self.amountfield
        self.unitfield=ui.editfield(win,6,26,20)
        self.focus_stockfield()
    def focus_stockfield(self):
        self.stockfield.set("")
        self.stockdescfield.set("")
        self.amountfield.set("")
        self.unitfield.set("")
        self.stockfield.focus()
    def stock_line(self,line):
        sn=td.stock_onsale(line[0])
        if sn is None:
            ui.infopopup(["There is nothing on sale on %s."%line[0]],
                         title="Error")
        else:
            self.stockfield.set(str(sn))
            self.stock_enter_key()
    def stock_enter_key(self):
        sn=int(self.stockfield.f)
        sd=td.stock_info(sn)
        if sd is None:
            ui.infopopup(["Stock number %d does not exist."%sn],
                         title="Error")
            self.focus_stockfield()
        else:
            self.stockdescfield.set("%(manufacturer)s %(name)s"%sd)
            self.unitfield.set(sd['unitname']+'s')
            self.wastedescfield.set(0)
            self.wastedescfield.focus()
    def finish(self):
        sn=int(self.stockfield.f)
        waste=self.wastedescfield.read()
        if self.amountfield.f=="":
            ui.infopopup(["You must enter an amount!"],title=Error)
            return
        amount=float(self.amountfield.f)
        if amount>0.0:
            td.stock_recordwaste(sn,waste,amount)
            self.dismiss()
            ui.infopopup(["Recorded %0.1f %s against stock item %d (%s)."%
                          (amount,self.unitfield.f,sn,self.stockdescfield.f)],
                         title="Waste Recorded",dismiss=keyboard.K_CASH,
                         colour=ui.colour_info)
        else:
            ui.infopopup(["You must enter an amount greater than zero!"],
                         title=Error)
            self.amountfield.set("")

