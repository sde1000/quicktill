"""Till management functions.

"""

import sys,math,curses,os
from . import ui,keyboard,td,printer
from . import register,tillconfig,managekeyboard,stocklines,event
from .version import version
from mx.DateTime import DateTimeDelta

import logging
log=logging.getLogger()

class ssdialog(ui.dismisspopup):
    def __init__(self):
        ui.dismisspopup.__init__(self,8,63,title="Session date",
                                 colour=ui.colour_input,
                                 dismiss=keyboard.K_CLEAR)
        self.addstr(2,2,"Please check the session date, and correct it "
                   "if necessary.")
        self.addstr(3,2,"Press Cash/Enter to continue and start the session.")
        self.addstr(5,2,"Session date:")
        date=ui.now()
        if date.hour>=23:
            date=date+DateTimeDelta(1)
        self.datefield=ui.datefield(5,16,f=date,keymap={
                keyboard.K_CASH: (self.key_enter,None)})
        self.datefield.focus()
    def key_enter(self):
        date=self.datefield.read()
        if date is None:
            ui.infopopup(["You must enter a valid date.  Every session is "
                          "recorded against a particular date; this is to "
                          "ensure the money taken is all recorded on that "
                          "day even if the session finishes late."],
                         title="Error")
            return
        self.dismiss()
        sc=td.session_start(date)
        td.trans_restore()
        td.foodorder_reset()
        log.info("Started session number %d"%sc[0])
        printer.kickout()
        ui.infopopup(["Started session number %d."%sc[0]],
                     title="Session started",colour=ui.colour_info,
                     dismiss=keyboard.K_CASH)

def startsession():
    sc=td.session_current()
    if sc:
        sn,starttime,sessiondate=sc
        log.info("Start session: session %d still in progress"%sn)
        ui.infopopup(["There is already a session in progress (number %d, "
                      "started %s)."%
                      (sc[0],starttime.strftime("%H:%M on %A"))],
                     title="Error")
    else:
        ssdialog()

def checkendsession(endfunc):
    sc=td.session_current()
    if sc is None:
        log.info("End session: no session in progress")
        ui.infopopup(["There is no session in progress."],title="Error")
        return None
    tl=endfunc()
    if tl is not None and len(tl)>0:
        log.info("End session: there are incomplete transactions")
        ui.infopopup(["There are incomplete transactions.  After dismissing "
                      "this message, use the 'Recall Trans' button to find "
                      "them, and either complete them, cancel them "
                      "or defer them."],
                     title="Error")
        return None
    return sc

def confirmendsession():
    r=checkendsession(td.session_end)
    if r is not None:
        # Print out session count-up receipt and pop up a confirmation box
        tots=td.session_paytotals(r[0])
        register.registry.announce(None,0)
        log.info("End of session %d confirmed. Amounts taken: %s"%(r[0],tots))
        ui.infopopup(["Session %d has ended.  "
                      "Please count the cash in the drawer and enter the "
                      "actual amounts using management option 3."%r[0]],
                     title="Session Ended",colour=ui.colour_info,
                     dismiss=keyboard.K_CASH)
        printer.print_sessioncountup(r[0])
        printer.kickout()
        stocklines.purge()

def endsession():
    r=checkendsession(td.trans_incompletes)
    if r is not None:
        km={keyboard.K_CASH:(confirmendsession,None,True)}
        log.info("End session popup: asking for confirmation")
        ui.infopopup(["Press Cash/Enter to confirm you want to end "
                      "session number %d."%r[0]],title="Session End",
                     keymap=km,colour=ui.colour_confirm)

def sessionlist(func,unpaidonly=False,closedonly=False):
    "Return a list of sessions suitable for a menu"
    def ss(sd):
        if unpaidonly and sd[4] is not None: return None
        if closedonly and sd[2]==None: return None
        if sd[4] is None:
            total=""
        else:
            total="%s "%tillconfig.fc(sd[4])
            total="%s%s"%(' '*(10-len(total)),total)
        return "%6d  %s  %s"%(sd[0],ui.formatdate(sd[3]),total)
    sl=td.session_list()
    return [(ss(x),func,(x[0],)) for x in sl if ss(x) is not None]

class recordsession(ui.dismisspopup):
    def __init__(self,session):
        log.info("Record session takings popup: session %d"%session)
        self.session=session
        paytotals=td.session_paytotals(session)
        paytypes=td.paytypes_list()
        ui.dismisspopup.__init__(self,7+len(paytypes),60,
                                 title="Session %d"%session,
                                 colour=ui.colour_input)
        self.addstr(2,2,"Please enter the actual takings for session %d."%
                    session)
        self.addstr(4,13,"Till total:     Actual total:")
        # Build a list of fields to be filled in
        self.fl=[]
        y=5
        for i in paytypes:
            self.addstr(y,2,"%s:"%paytypes[i])
            if i in paytotals:
                self.addstr(y,15,tillconfig.fc(paytotals[i][1]))
                pt=paytotals[i][1]
            else:
                pt=0.0
            if i=='PPINT':
                field=ui.editfield(y,29,10,validate=ui.validate_float,
                                   f="%0.2f"%pt,readonly=True)
            else:
                field=ui.editfield(y,29,10,validate=ui.validate_float)
            y=y+1
            self.fl.append([i,paytypes[i],field,pt])
        ui.map_fieldlist([x[2] for x in self.fl])
        # Override key bindings for first/last fields
        self.fl[0][2].keymap[keyboard.K_CLEAR]=(self.dismiss,None)
        self.fl[-1][2].keymap[keyboard.K_CASH]=(self.field_return,None)
        self.fl[0][2].focus()
    def field_return(self):
        self.amounts={}
        def guessamount(field,expected):
            if field.f.find('.')>=0:
                return float(field.f)
            try:
                trial=float(field.f)
            except:
                trial=0.0
            # It might be an amount 100 times larger
            diff1=math.fabs(trial-expected)
            diff2=math.fabs((trial/100.0)-expected)
            if diff2<diff1: return trial/100.0
            return trial
        for i in self.fl:
            self.amounts[i[0]]=guessamount(i[2],i[3])
        km={keyboard.K_CASH:
            (self.confirm_recordsession,None,True)}
        log.info("Record takings: asking for confirmation: session=%d"%
                 self.session)
        ui.infopopup(["Press Cash/Enter to record the following as the "
                      "amounts taken in session %d."%self.session]+
                     ["%s: %s"%(x[1],tillconfig.fc(self.amounts[x[0]]))
                      for x in self.fl],
                     title="Confirm Session Total",keymap=km,
                     colour=ui.colour_confirm)
    def confirm_recordsession(self):
        log.info("Record session takings: confirmed session %d"%self.session)
        st=[(x[0],self.amounts[x[0]]) for x in self.fl
            if self.amounts[x[0]]!=0.0]
        td.session_recordtotals(self.session,st)
        printer.print_sessiontotals(self.session)
        self.dismiss()

def sessiontakings():
    m=sessionlist(recordsession,unpaidonly=True,closedonly=True)
    if len(m)==0:
        log.info("Record takings: no sessions available")
        ui.infopopup(["Every session has already had its takings "
                      "recorded.  If you want to record takings for "
                      "the current session, you must close it first."],
                     title="Error")
    else:
        log.info("Record takings: displaying menu")
        ui.menu(m,title="Record Takings",
                blurb="Select the session that you "
                "want to record the takings for, and press Cash/Enter.")

def totalpopup(session):
    w=33
    def lr(l,r):
        return "%s%s%s"%(l,' '*(w-len(l)-len(r)),r)
    log.info("Totals popup for session %d"%session)
    (start,end,accdate)=td.session_dates(session)
    depts=td.session_depttotals(session)
    paytotals=td.session_paytotals(session)
    payments=td.session_actualtotals(session)
    paytypes=set(list(paytotals.keys())+list(payments.keys()))
    l=[]
    l.append("Accounting date %s"%ui.formatdate(accdate))
    l.append("Started %s"%ui.formattime(start))
    if end is None:
        l.append("Session is still open.")
    else:
        l.append("Ended %s"%ui.formattime(end))
    l.append(lr("Till totals:","Actual totals:"))
    for i in paytypes:
        if i in paytotals:
            tt="%s: %s%0.2f"%(paytotals[i][0],tillconfig.currency,
                              paytotals[i][1])
        else:
            tt=""
        if i in payments:
            at="%s: %s%0.2f"%(payments[i][0],tillconfig.currency,
                              payments[i][1])
        else:
            at=""
        # Format tt and at at left/right
        l.append(lr(tt,at))
    l.append("")
    dt=0.0
    for i in depts:
        l.append(lr("%2d %s"%(i[0],i[1]),"%s%0.2f"%(tillconfig.currency,i[2])))
        dt=dt+i[2]
    l.append(lr("Total","%s%0.2f"%(tillconfig.currency,dt)))
    l.append("Press Print for a hard copy")
    keymap={
        keyboard.K_PRINT:(printer.print_sessiontotals,(session,),False),
        }
    ui.linepopup(l,title="Session number %d"%session,
                 colour=ui.colour_info,keymap=keymap,
                 dismiss=keyboard.K_CASH)

def transrestore():
    log.info("Restore deferred transactions")
    td.trans_restore()
    ui.infopopup(["All deferred transactions have been restored."],
                 title="Confirmation",colour=ui.colour_confirm,
                 dismiss=keyboard.K_CASH)

def sessionsummary():
    log.info("Session summary popup")
    m=sessionlist(totalpopup)
    ui.menu(m,title="Session Summary",blurb="Select a session and "
            "press Cash/Enter to view the summary.",
            dismiss_on_select=False)

def currentsessionsummary():
    sc=td.session_current()
    if sc is None:
        ui.infopopup(["There is no session in progress."],title="Error")
    else:
        sn,starttime,sessiondate=sc
        totalpopup(sn)

class receiptprint(ui.dismisspopup):
    def __init__(self):
        ui.dismisspopup.__init__(self,5,30,title="Receipt print",
                                 dismiss=keyboard.K_CLEAR,
                                 colour=ui.colour_input)
        self.addstr(2,2,"Receipt number:")
        self.rnfield=ui.editfield(
            2,18,10,validate=ui.validate_int,keymap={
                keyboard.K_CASH: (self.enter,None,True)})
        self.rnfield.focus()
    def enter(self):
        try:
            rn=int(self.rnfield.f)
        except:
            rn=None
        if rn is None: return
        printer.print_receipt(rn)
        self.dismiss()

def versioninfo():
    log.info("Version popup")
    ui.infopopup(["Quick till software %s"%version,
                  "(C) Copyright 2004-2010 Stephen Early",
                  "Configuration: %s"%tillconfig.configversion,
                  "Operating system: %s %s %s"%(os.uname()[0],
                                                os.uname()[2],
                                                os.uname()[3]),
                  "Python version: %s %s"%tuple(sys.version.split('\n')),
                  td.db_version()],
                 title="Software Version Information",
                 colour=ui.colour_info,dismiss=keyboard.K_CASH)

def exitoption(code):
    event.shutdowncode=code

def restartmenu():
    log.info("Restart menu")
    menu=[
        (keyboard.K_ONE,"Exit / restart till software",exitoption,(0,)),
        (keyboard.K_TWO,"Turn off till",exitoption,(2,)),
        (keyboard.K_THREE,"Reboot till",exitoption,(3,)),
        ]
    ui.keymenu(menu,"Exit / restart options")

def sessionmenu():
    log.info("Session management menu")
    menu=[
        (keyboard.K_ONE,"Start a session",startsession,None),
        (keyboard.K_TWO,"End the current session",endsession,None),
        (keyboard.K_THREE,"Record session takings",sessiontakings,None),
        (keyboard.K_FOUR,"Display session summary",sessionsummary,None),
        ]
    ui.keymenu(menu,"Session management options")

def popup():
    log.info("Till management menu")
    menu=[
        (keyboard.K_ONE,"Sessions",sessionmenu,None),
        (keyboard.K_TWO,"Current session summary",currentsessionsummary,None),
        (keyboard.K_THREE,"Restore deferred transactions",transrestore,None),
        (keyboard.K_FOUR,"Stock lines",stocklines.popup,None),
        (keyboard.K_FIVE,"Keyboard",managekeyboard.popup,None),
        (keyboard.K_SIX,"Print a receipt",receiptprint,None),
        (keyboard.K_EIGHT,"Exit / restart",restartmenu,None),
        (keyboard.K_NINE,"Display till software versions",versioninfo,None),
        ]
    ui.keymenu(menu,"Management options")
