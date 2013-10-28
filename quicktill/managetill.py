"""Till management functions.

"""

import sys,math,curses,os
from . import ui,keyboard,td,printer,btcmerch
from . import register,tillconfig,managekeyboard,stocklines,event
from .version import version
import datetime
from decimal import Decimal
from .models import Session,PayType,SessionTotal,zero,penny
from .td import undefer,func,desc,select

import logging
log=logging.getLogger(__name__)

class ssdialog(ui.dismisspopup):
    def __init__(self):
        ui.dismisspopup.__init__(self,8,63,title="Session date",
                                 colour=ui.colour_input,
                                 dismiss=keyboard.K_CLEAR)
        self.addstr(2,2,"Please check the session date, and correct it "
                   "if necessary.")
        self.addstr(3,2,"Press Cash/Enter to continue and start the session.")
        self.addstr(5,2,"Session date:")
        date=datetime.datetime.now()
        if date.hour>=23:
            date=date+datetime.timedelta(days=1)
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
        sc=Session(date)
        td.s.add(sc)
        td.s.flush()
        td.trans_restore()
        td.foodorder_reset()
        log.info("Started session number %d",sc.id)
        printer.kickout()
        ui.infopopup(["Started session number %d."%sc.id],
                     title="Session started",colour=ui.colour_info,
                     dismiss=keyboard.K_CASH)

def startsession():
    sc=Session.current(td.s)
    if sc:
        log.info("Start session: session %d still in progress"%sc.id)
        ui.infopopup(["There is already a session in progress (number %d, "
                      "started %s)."%
                      (sc.id,sc.starttime.strftime("%H:%M on %A"))],
                     title="Error")
    else:
        ssdialog()

def checkendsession():
    sc=Session.current(td.s)
    if sc is None:
        log.info("End session: no session in progress")
        ui.infopopup(["There is no session in progress."],title="Error")
        return None
    if len(sc.incomplete_transactions)>0:
        log.info("End session: there are incomplete transactions")
        ui.infopopup(
            ["There are incomplete transactions.  After dismissing "
             "this message, use the 'Recall Trans' button to find "
             "them, and either complete them, cancel them "
             "or defer them."],
            title="Error")
        return None
    return sc

def confirmendsession():
    r=checkendsession()
    if r is None: return
    r.endtime=datetime.datetime.now()
    register.registry.announce(None,0)
    log.info("End of session %d confirmed.",r.id)
    ui.infopopup(["Session %d has ended.  "
                  "Please count the cash in the drawer and enter the "
                  "actual amounts using management option 1,3."%(r.id,)],
                 title="Session Ended",colour=ui.colour_info,
                 dismiss=keyboard.K_CASH)
    printer.print_sessioncountup(r)
    printer.kickout()
    td.stock_purge()

def endsession():
    r=checkendsession()
    if r is not None:
        km={keyboard.K_CASH:(confirmendsession,None,True)}
        log.info("End session popup: asking for confirmation")
        ui.infopopup(["Press Cash/Enter to confirm you want to end "
                      "session number %d."%r.id],title="Session End",
                     keymap=km,colour=ui.colour_confirm)

def sessionlist(dbsession,cont,unpaidonly=False,closedonly=False):
    "Return a list of sessions suitable for a menu"
    def ss(s):
        if s.endtime is None:
            total=""
        else:
            total="%s "%tillconfig.fc(s.total)
            total="%s%s"%(' '*(10-len(total)),total)
        return "%6d  %s  %s"%(s.id,ui.formatdate(s.date),total)
    q=td.s.query(Session).\
        order_by(desc(Session.id)).\
        options(undefer('total'))
    if unpaidonly:
        q=q.filter(select([func.count(SessionTotal.sessionid)],
                          whereclause=SessionTotal.sessionid==Session.id).\
                       correlate(Session.__table__).as_scalar()==0)
    if closedonly:
        q=q.filter(Session.endtime!=None)
    return [(ss(x),cont,(x,)) for x in q.all()]

class recordsession(ui.dismisspopup):
    def __init__(self,s):
        td.s.add(s)
        log.info("Record session takings popup: session %d",s.id)
        self.session=s
        paytotals=dict(s.payment_totals)
        paytypes=td.s.query(PayType).all()
        ui.dismisspopup.__init__(self,7+len(paytypes),60,
                                 title="Session %d"%s.id,
                                 colour=ui.colour_input)
        self.addstr(2,2,"Please enter the actual takings for session %d."%
                    s.id)
        self.addstr(4,13,"Till total:     Actual total:")
        # Build a list of fields to be filled in
        self.fl=[]
        y=5
        for i in paytypes:
            self.addstr(y,2,"%s:"%i.description)
            if i in paytotals:
                pt=paytotals[i]
            else:
                pt=Decimal("0.00")
            self.addstr(y,15,tillconfig.fc(pt))
            if i.paytype=='PPINT':
                field=ui.editfield(y,29,10,validate=ui.validate_float,
                                   f="%0.2f"%pt,readonly=True)
            elif i.paytype=='BTC':
                btcval=Decimal("0.00")
                if pt>Decimal("0.00"):
                    try:
                        tl=td.session_bitcoin_translist(s.id)
                        btcval=tillconfig.btcmerch_api.transactions_total(
                            ["tx%d"%t for t in tl])[u"total"]
                    except btcmerch.BTCMerchError:
                        ui.infopopup(
                            ["Could not retrieve Bitcoin total; please try "
                             "again later."],title="Error")
                field=ui.editfield(y,29,10,validate=ui.validate_float,
                                   f="%0.2f"%btcval,readonly=True)
            else:
                field=ui.editfield(y,29,10,validate=ui.validate_float)
            y=y+1
            self.fl.append([i,field,pt])
        ui.map_fieldlist([x[1] for x in self.fl])
        # Override key bindings for first/last fields
        self.fl[0][1].keymap[keyboard.K_CLEAR]=(self.dismiss,None)
        self.fl[-1][1].keymap[keyboard.K_CASH]=(self.field_return,None)
        self.fl[0][1].focus()
    def field_return(self):
        td.s.add(self.session)
        self.amounts={}
        def guessamount(field,expected):
            if field.f.find('.')>=0:
                return Decimal(field.f).quantize(penny)
            try:
                trial=Decimal(field.f)
            except:
                trial=zero
            # It might be an amount 100 times larger
            diff1=math.fabs(trial-expected)
            diff2=math.fabs((trial/Decimal("100.00"))-expected)
            if diff2<diff1: trial=trial/Decimal(100)
            return trial.quantize(penny)
        for paytype,field,expected in self.fl:
            td.s.add(paytype)
            self.amounts[paytype]=guessamount(field,expected)
        km={keyboard.K_CASH:
            (self.confirm_recordsession,None,True)}
        log.info("Record takings: asking for confirmation: session=%d",
                 self.session.id)
        ui.infopopup(["Press Cash/Enter to record the following as the "
                      "amounts taken in session %d."%self.session.id]+
                     ["%s: %s"%(paytype.description,tillconfig.fc(self.amounts[paytype]))
                      for paytype,field,tilltotal in self.fl],
                     title="Confirm Session Total",keymap=km,
                     colour=ui.colour_confirm)
    def confirm_recordsession(self):
        td.s.add(self.session)
        log.info("Record session takings: confirmed session %d",self.session.id)
        for paytype,field,expected in self.fl:
            td.s.add(paytype)
            if self.amounts[paytype]==zero: continue
            td.s.add(SessionTotal(session=self.session,paytype=paytype,
                                  amount=self.amounts[paytype]))
        td.s.flush()
        tl=td.session_bitcoin_translist(self.session.id)
        if len(tl)>0:
            try:
                tillconfig.btcmerch_api.transactions_reconcile(
                    str(self.session),["tx%d"%t for t in tl])
            except:
                pass
        printer.print_sessiontotals(self.session)
        self.dismiss()

def sessiontakings():
    m=sessionlist(td.s,recordsession,unpaidonly=True,closedonly=True)
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

def totalpopup(s):
    """Display popup session totals given a Session object.

    """
    s=td.s.merge(s)
    w=33
    def lr(l,r):
        return "%s%s%s"%(l,' '*(w-len(l)-len(r)),r)
    log.info("Totals popup for session %d"%(s.id,))

    depts=s.dept_totals # Now gives list of (Dept,total) tuples
    paytotals=dict(s.payment_totals)
    payments=dict([(x.paytype,x) for x in s.actual_totals])

    paytypes=set(list(paytotals.keys())+list(payments.keys()))
    l=[]
    l.append("Accounting date %s"%ui.formatdate(s.date))
    l.append("Started %s"%ui.formattime(s.starttime))
    if s.endtime is None:
        l.append("Session is still open.")
    else:
        l.append("Ended %s"%ui.formattime(s.endtime))
    l.append(lr("Till totals:","Actual totals:"))
    ttt=Decimal("0.00")
    att=Decimal("0.00")
    for i in paytypes:
        if i in paytotals:
            tt="%s: %s%0.2f"%(i.description,tillconfig.currency,
                              paytotals[i])
            ttt=ttt+paytotals[i]
        else:
            tt=""
        if i in payments:
            at="%s: %s%0.2f"%(i.description,tillconfig.currency,
                              payments[i].amount)
            att=att+payments[i].amount
        else:
            at=""
        # Format tt and at at left/right
        l.append(lr(tt,at))
    if len(paytypes)>1:
        tt="Total: %s"%(tillconfig.fc(ttt),)
        at="Total: %s"%(tillconfig.fc(att),) if att>Decimal("0.00") else ""
        l.append(lr(tt,at))
    l.append("")
    dt=Decimal("0.00")
    for dept,total in depts:
        l.append(lr("%2d %s"%(dept.id,dept.description),
                    "%s%0.2f"%(tillconfig.currency,total)))
        dt=dt+total
    l.append(lr("Total","%s%0.2f"%(tillconfig.currency,dt)))
    l.append("Press Print for a hard copy")
    keymap={
        keyboard.K_PRINT:(printer.print_sessiontotals,(s,),False),
        }
    ui.listpopup([ui.marginline(ui.line(x),margin=1) for x in l],
                 title="Session number %d"%s.id,
                 colour=ui.colour_info,keymap=keymap,
                 dismiss=keyboard.K_CASH,show_cursor=False)

def transrestore():
    log.info("Restore deferred transactions")
    td.trans_restore()
    ui.infopopup(["All deferred transactions have been restored."],
                 title="Confirmation",colour=ui.colour_confirm,
                 dismiss=keyboard.K_CASH)

def sessionsummary():
    log.info("Session summary popup")
    m=sessionlist(td.s,totalpopup)
    ui.menu(m,title="Session Summary",blurb="Select a session and "
            "press Cash/Enter to view the summary.",
            dismiss_on_select=False)

def currentsessionsummary():
    sc=Session.current(td.s)
    if sc is None:
        ui.infopopup(["There is no session in progress."],title="Error")
    else:
        totalpopup(sc)

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

def bitcoincheck():
    log.info("Bitcoin service check")
    if tillconfig.btcmerch_api is None:
        return ui.infopopup(
            ["Bitcoin service is not configured for this till."],
            title="Bitcoin info",dismiss=keyboard.K_CASH)
    try:
        rv=tillconfig.btcmerch_api.test_connection()
    except btcmerch.BTCMerchError as e:
        return ui.infopopup([str(e)],title="Bitcoin error")
    return ui.infopopup(
        ["Bitcoin service ok; it reports it owes us %s for the current "
         "session."%rv[u'total']],
        title="Bitcoin info",dismiss=keyboard.K_CASH,
        colour=ui.colour_info)

def versioninfo():
    log.info("Version popup")
    ui.infopopup(["Quick till software %s"%version,
                  "(C) Copyright 2004-2013 Stephen Early",
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
        (keyboard.K_SEVEN,"Check Bitcoin service connection",bitcoincheck,None),
        (keyboard.K_EIGHT,"Exit / restart",restartmenu,None),
        (keyboard.K_NINE,"Display till software versions",versioninfo,None),
        ]
    ui.keymenu(menu,"Management options")
