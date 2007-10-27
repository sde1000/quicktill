# -*- coding: iso-8859-1 -*-

import ui,keyboard,td,time,printer,math,sys,curses,os
import register
from version import version

import logging
log=logging.getLogger()

def startsession():
    sc=td.session_current()
    if sc:
        log.info("Start session: session %s still in progress"%sc[0])
        ui.infopopup(["There is already a session in progress (number %d, "
                      "started %s)."%
                      (sc[0],time.strftime("%H:%M on %A",sc[1]))],
                     title="Error")
    else:
        sc=td.session_start()
        log.info("Started session number %d"%sc[0])
        ui.infopopup(["Started session number %d."%sc[0]],
                     title="Session started",colour=ui.colour_info,
                     dismiss=keyboard.K_CASH)

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
                      "them, and either complete them or cancel them."],
                     title="Error")
        return None
    return sc

def confirmendsession():
    r=checkendsession(td.session_end)
    if r is not None:
        # Print out session count-up receipt and pop up a confirmation box
        tot=td.session_transtotal(r[0])
        if tot is None: tot=0.0
        register.registry.announce(None,0)
        log.info("End of session %d confirmed. Amount taken %f"%(r[0],tot))
        ui.infopopup(["Session %d has ended.  Amount taken was £%0.2f.  "
                      "Please count the cash in the drawer and enter the "
                      "actual amount using management option 3."%(r[0],tot)],
                     title="Session Ended",colour=ui.colour_info,
                     dismiss=keyboard.K_CASH)
        printer.print_sessioncountup(r[0])
        printer.kickout()

def endsession():
    r=checkendsession(td.trans_incompletes)
    if r is not None:
        km={keyboard.K_CASH:(confirmendsession,None,True)}
        log.info("End session popup: asking for confirmation")
        ui.infopopup(["Press Cash/Enter to confirm you want to end "
                      "session number %d."%r[0]],title="Session End",
                     keymap=km,colour=ui.colour_input)

def sessionlist(sl,func,unpaidonly=False,closedonly=False):
    "Return a list of sessions suitable for a menu"
    def ss(sd):
        if unpaidonly and sd[3] is not None: return None
        if closedonly and sd[2]==None: return None
        if sd[2] is None:
            end="[ current session ]"
        else:
            end=ui.formattime(sd[2])
        if sd[3] is None:
            total=""
        else:
            total="£%0.2f "%sd[3]
            total="%s%s"%(' '*(10-len(total)),total)
        return "%6d (%s-%s) %s"%(sd[0],ui.formattime(sd[1]),end,total)
    return [(ss(x),func,(x[0],)) for x in sl if ss(x) is not None]

def confirm_recordsession(session,total):
    log.info("Record session takings: confirmed session %d"%session)
    td.session_recordtotals(session,[('CASH',total)])
    printer.print_sessiontotals(session)

class recordsession(ui.basicpopup):
    def __init__(self,session):
        log.info("Record session takings popup: session %d"%session)
        self.session=session
        self.expected=td.session_transtotal(session)
        if self.expected is None: self.expected=0.0
        # We don't supply a keymap because the focus always belongs to
        # our child windows
        ui.basicpopup.__init__(self,7,60,title="Session %d"%session,
                               cleartext="Press Clear to go back",
                               colour=ui.colour_input)
        self.win=self.pan.window()
        self.win.addstr(2,2,"Please enter the actual takings for session %d."%
                        session)
        self.win.addstr(3,2,"The total recorded by the till was £%0.2f"%
                        self.expected)
        self.win.addstr(5,2,"Cash: £")
        km={keyboard.K_CASH: (self.cashfield_return,None,True),
            keyboard.K_CLEAR: (self.dismiss,None,True)}
        self.cashfield=ui.editfield(self.win,5,9,10,keymap=km)
        self.cashfield.focus()
    def cashfield_return(self):
        try:
            amount=float(self.cashfield.f)
        except:
            amount=None
        if amount is None:
            self.cashfield.f=""
            self.cashfield.focus()
            log.info("Record takings popup: no number entered")
            ui.infopopup(["You must enter a number!"],title="Error")
        else:
            self.dismiss()
            if self.cashfield.f.find('.')>=0:
                log.info("Record takings popup: number with point entered")
                realamount=amount
            else:
                # It might be an amount 100 times larger
                diff1=math.fabs(amount-self.expected)
                diff2=math.fabs((amount/100.0)-self.expected)
                if diff2<diff1: realamount=amount/100.0
                else: realamount=amount
            km={keyboard.K_CASH:
                (confirm_recordsession,(self.session,realamount),True)}
            log.info("Record takings: asking for confirmation: session=%d amount=%f"%
                     (self.session,realamount))
            ui.infopopup(["Press Cash/Enter to record £%0.2f as the amount "
                          "taken in session %d."%(realamount,self.session)],
                         title="Confirm Session Total",keymap=km,
                         colour=ui.colour_input)

def sessiontakings():
    sl=td.session_list()
    m=sessionlist(sl,recordsession,unpaidonly=True,closedonly=True)
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
    log.info("Totals popup for session %d"%session)
    depts=td.session_depttotals(session)
    paytotal=td.session_transtotal(session)
    if paytotal is None: paytotal=0.0
    (start,end)=td.session_startend(session)
    payments=td.session_actualtotals(session)
    l=[]
    l.append("Started %s"%ui.formattime(start))
    if end is None:
        l.append("Session is still open")
        l.append("Total payments: £%0.2f"%paytotal)
    else:
        l.append("Ended %s"%ui.formattime(end))
        if len(payments)==0:
            l.append("No actual amount taken recorded yet")
        else:
            for i in payments:
                l.append("%s: £%0.2f"%(i[0],i[1]))
    dt=0.0
    def lr(l,r,w):
        return "%s%s%s"%(l,' '*(w-len(l)-len(r)),r)
    for i in depts:
        l.append(lr("%2d %s"%(i[0],i[1]),"£%0.2f"%i[2],30))
        dt=dt+i[2]
    l.append(lr("Total","£%0.2f"%dt,30))
    l.append("Press Print for a hard copy")
    keymap={
        keyboard.K_PRINT:(printer.print_sessiontotals,(session,),False),
        }
    ui.linepopup(l,title="Session number %d"%session,
                 colour=ui.colour_info,keymap=keymap,
                 dismiss=keyboard.K_CASH)

def sessionsummary():
    log.info("Session summary popup")
    sl=td.session_list()
    m=sessionlist(sl,totalpopup)
    ui.menu(m,title="Session Summary",blurb="Select a session and "
            "press Cash/Enter to view the summary.")

def versioninfo():
    log.info("Version popup")
    ui.infopopup(["Quick till software %s"%version,
                  "(C) Copyright 2004 Stephen Early",
                  "Operating system: %s %s %s"%(os.uname()[0],
                                                os.uname()[2],
                                                os.uname()[3]),
                  "Python version: %s %s"%tuple(sys.version.split('\n')),
                  td.db_version()],
                 title="Software Version Information")

def popup():
    log.info("Till management popup")
    menu=[
        (keyboard.K_ONE,"Start a session",startsession,None),
        (keyboard.K_TWO,"End the current session",endsession,None),
        (keyboard.K_THREE,"Record session takings",sessiontakings,None),
        (keyboard.K_FOUR,"Display session summary",sessionsummary,None),
        (keyboard.K_NINE,"Display till software version",versioninfo,None),
        ]
    ui.keymenu(menu,"Management options")
