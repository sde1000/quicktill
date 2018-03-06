"""Starting, ending, and recording totals for sessions."""

from . import ui, keyboard, td, printer, tillconfig, user, managestock
from .models import Session, SessionTotal, PayType, Transaction, penny, zero
from .td import undefer, func, desc, select
from .plugins import InstancePluginMount
from decimal import Decimal
import datetime

import logging
log = logging.getLogger(__name__)

def trans_restore():
    """Restore deferred transactions

    Moves deferred transactions to the current session.  Returns a
    list of transactions that were deferred.
    """
    sc = Session.current(td.s)
    if sc is None:
        return []
    deferred = td.s.query(Transaction)\
                   .filter(Transaction.sessionid == None)\
                   .all()
    for i in deferred:
        i.session = sc
    td.s.flush()
    return deferred

class ssdialog(ui.dismisspopup):
    """Session start dialog box."""
    def __init__(self):
        ui.dismisspopup.__init__(self, 8, 63, title="Session date",
                                 colour=ui.colour_input,
                                 dismiss=keyboard.K_CLEAR)
        self.addstr(2, 2, "Please check the session date, and correct it "
                    "if necessary.")
        self.addstr(3, 2, "Press Cash/Enter to continue and start the session.")
        self.addstr(5, 2, "Session date:")
        date = datetime.datetime.now()
        if date.hour >= 23:
            date = date + datetime.timedelta(days=1)
        self.datefield = ui.datefield(5, 16, f=date, keymap={
            keyboard.K_CASH: (self.key_enter, None)})
        self.datefield.focus()

    def key_enter(self):
        date = self.datefield.read()
        if date is None:
            ui.infopopup(["You must enter a valid date.  Every session is "
                          "recorded against a particular date; this is to "
                          "ensure the money taken is all recorded on that "
                          "day even if the session finishes late."],
                         title="Error")
            return
        self.dismiss()
        sc = Session(date)
        td.s.add(sc)
        td.s.flush()
        deferred = trans_restore()
        td.foodorder_reset()
        log.info("Started session number %d", sc.id)
        printer.kickout()
        if deferred:
            deferred = [
                "",
                "The following deferred transactions were restored:",
                ""] + ["{} - {}".format(d.id, d.notes) if d.notes else
                       "{}".format(d.id) for d in deferred]
        ui.infopopup(["Started session number {}.".format(sc.id)] + deferred,
                     title="Session started", colour=ui.colour_info,
                     dismiss=keyboard.K_CASH)

@user.permission_required("start-session", "Start a session")
def start():
    """Start a session if there is not already one in progress.
    """
    sc = Session.current(td.s)
    if sc:
        log.info("Start session: session %d still in progress", sc.id)
        ui.infopopup(["There is already a session in progress (number {}, "
                      "started {:%H:%M on %A}).".format(
                          sc.id, sc.starttime)],
                     title="Error")
    else:
        ssdialog()

def checkendsession():
    sc = Session.current(td.s)
    if sc is None:
        log.info("End session: no session in progress")
        ui.infopopup(["There is no session in progress."], title="Error")
        return
    if sc.incomplete_transactions:
        log.info("End session: there are incomplete transactions")
        ui.infopopup(
            ["There are incomplete transactions.  After dismissing "
             "this message, use the 'Recall Trans' button to find "
             "them, and either complete them, cancel them "
             "or defer them."],
            title="Error")
        return
    return sc

def confirmendsession():
    r = checkendsession()
    if not r:
        return
    # Check that the printer has paper before ending the session
    pp = printer.driver.offline()
    if pp:
        ui.infopopup(["Could not end the session: there is a problem with "
                      "the printer: {}".format(pp)], title="Printer problem")
        return
    r.endtime = datetime.datetime.now()
    log.info("End of session %d confirmed.", r.id)
    ui.infopopup(["Session {} has ended.".format(r.id),
                  "",
                  "Please count the cash in the drawer and enter the "
                  "actual amounts using management option 1, 3."],
                 title="Session Ended", colour=ui.colour_info,
                 dismiss=keyboard.K_CASH)
    ui.toast("Printing the countup sheet.")
    with ui.exception_guard("printing the session countup sheet",
                            title="Printer error"):
        printer.print_sessioncountup(r)
    printer.kickout()
    managestock.stock_purge_internal(source="session end")

@user.permission_required("end-session", "End a session")
def end():
    """End the current session if there is one.
    """
    r = checkendsession()
    if r:
        km = {keyboard.K_CASH: (confirmendsession, None, True)}
        log.info("End session popup: asking for confirmation")
        ui.infopopup(["Press Cash/Enter to confirm you want to end "
                      "session number {}.".format(r.id)], title="Session End",
                     keymap=km, colour=ui.colour_confirm)

def sessionlist(cont, paidonly=False, unpaidonly=False, closedonly=False,
                maxlen=None):
    """Return a list of sessions suitable for a menu.
    """
    q = td.s.query(Session)\
            .order_by(desc(Session.id))\
            .options(undefer('total'))
    if paidonly:
        q = q.filter(select([func.count(SessionTotal.sessionid)],
                            whereclause=SessionTotal.sessionid == Session.id)\
                     .correlate(Session.__table__).as_scalar() != 0)
    if unpaidonly:
        q = q.filter(select([func.count(SessionTotal.sessionid)],
                            whereclause=SessionTotal.sessionid == Session.id)\
                     .correlate(Session.__table__).as_scalar() == 0)
    if closedonly:
        q = q.filter(Session.endtime != None)
    if maxlen:
        q = q[:maxlen]
    f = ui.tableformatter(' r  l  r ')
    return [(f(x.id, x.date, tillconfig.fc(x.total)), cont, (x.id,)) for x in q]

class _PMWrapper(object):
    """Payment method wrapper for record session takings popup.

    Remembers the total and where to put it when it's updated.
    """
    def __init__(self, pm, till_total, popup):
        self.pm = pm
        self.lines = 1 if len(pm.total_fields) <= 1 else len(pm.total_fields) + 1
        self.till_total = till_total
        self.actual_total = pm.total(popup.session, [""] * len(pm.total_fields))
        self.fields = []
        self.popup = popup

    def display_total(self):
        if isinstance(self.actual_total, Decimal):
            self.popup.addstr(
                self.y, self.popup.atx,
                self.popup.ff.format(tillconfig.fc(self.actual_total)))
        else:
            self.popup.addstr(
                self.y, self.popup.atx, self.popup.ff.format("Error"))

    def update_total(self):
        # One of the fields has been changed; redraw the total
        self.actual_total = self.pm.total(self.popup.session,
                                          [f.f for f in self.fields])
        self.display_total()
        self.popup.update_total()

class record(ui.dismisspopup):
    """Record the takings for a session.

    This popup queries all the payment methods to find out which
    fields need to be displayed.

    Pass a Session ID to this class.
    """
    ttx = 30
    atx = 45
    ff = "{:>13}"

    def __init__(self, sessionid):
        s = td.s.query(Session).get(sessionid)
        log.info("Record session takings popup: session %d", s.id)
        self.session = s
        if not self.session_valid():
            return
        for i in SessionHooks.instances:
            if i.preRecordSessionTakings(s.id):
                return
        paytotals = dict([(x.paytype, y) for x, y in s.payment_totals])
        self.pms = [_PMWrapper(pm, paytotals.get(pm.paytype, zero), self)
                    for pm in tillconfig.all_payment_methods]
        # XXX if paytotals includes payment types not included in the
        # configured payment methods, add those here
        self.till_total = s.total
        # How tall does the window need to be?  Each payment type
        # takes a minimum of one line; if len(pt.total_fields())>1
        # then it takes len(pt.total_fields())+1 lines
        h = sum(pm.lines for pm in self.pms)
        # We also need the top border (2), a prompt and header at the
        # top (3) and a total and button at the bottom (4) and the
        # bottom border (2).
        h = h + 11
        ui.dismisspopup.__init__(self, h, 60,title="Session {0.id}".format(s),
                                 colour=ui.colour_input)
        self.addstr(2, 2,
                    "Please enter the actual takings for session {}.".format(
                        s.id))
        self.addstr(4, self.ttx, "  Till total:")
        self.addstr(4, self.atx, "Actual total:")
        y = 5
        self.fl = []
        for pm in self.pms:
            pm.y = y
            self.addstr(y, self.ttx, self.ff.format(
                tillconfig.fc(pm.till_total)))
            pm.display_total()
            self.addstr(y, 2, "{}:".format(pm.pm.description))
            if len(pm.pm.total_fields) == 0:
                # No data entry; just the description
                pm.fields = []
            elif len(pm.pm.total_fields) == 1:
                # Single field using the description with no indent
                field = pm.pm.total_fields[0]
                f = ui.editfield(y, 20, 8, validate=field[1])
                self.fl.append(f)
                pm.fields.append(f)
                f.sethook = pm.update_total
            else:
                # Line with payment method description and totals, then
                # one line per field with indent
                for field in pm.pm.total_fields:
                    y = y + 1
                    self.addstr(y, 4, "{}:".format(field[0]))
                    f = ui.editfield(y, 20, 8, validate=field[1])
                    self.fl.append(f)
                    pm.fields.append(f)
                    f.sethook = pm.update_total
            y = y + 1
        y = y + 1
        self.total_y = y
        self.update_total()
        y = y + 2
        self.fl.append(ui.buttonfield(y, 20, 20, 'Record'))
        ui.map_fieldlist(self.fl)
        # Override key bindings for first/last fields
        self.fl[0].keymap[keyboard.K_CLEAR] = (self.dismiss, None)
        self.fl[-1].keymap[keyboard.K_CASH] = (self.finish, None)
        self.fl[0].focus()

    def update_total(self):
        """A payment method wrapper has changed its total.

        Redraw the total line at the bottom of the window.
        """
        self.win.addstr(self.total_y, 2, ' ' * 28)
        self.win.addstr(self.total_y, self.ttx,
                        self.ff.format(tillconfig.fc(self.till_total)),
                        ui.colour_confirm)
        try:
            total = sum(pm.actual_total for pm in self.pms)
            difference = self.till_total - total
            description = "Total (DOWN by {})"
            if difference == zero:
                description = "Total (correct)"
            elif difference < zero:
                difference = -difference
                description = "Total (UP by {})"
            colour = ui.colour_error if difference > Decimal(20) \
                     else ui.colour_input
            self.win.addstr(
                self.total_y, 2,
                description.format(tillconfig.fc(difference)),
                colour)
            self.win.addstr(
                self.total_y, self.atx,
                self.ff.format(tillconfig.fc(total)),
                ui.colour_confirm)
        except:
            self.win.addstr(self.total_y, 2, "Can't calculate total",
                            ui.colour_error)
            self.win.addstr(self.total_y, self.atx, self.ff.format("Error"),
                            ui.colour_error)

    def session_valid(self):
        """Is the session eligible to have its totals recorded?

        The session object is assumed to be in the current ORM
        session.

        Returns True if the session is still valid, otherwise pops up
        an error dialog and returns False.
        """
        if self.session.endtime is None:
            ui.infopopup(["Session {s.id} is not finished.".format(
                        s=self.session)], title="Error")
            return False
        if self.session.actual_totals:
            ui.infopopup(["Session {s.id} has already had totals "
                          "recorded.".format(s=self.session)], title="Error")
            return False
        return True

    def finish(self):
        td.s.add(self.session)
        if not self.session_valid():
            return
        for pm in self.pms:
            if isinstance(pm.actual_total, Decimal):
                td.s.add(SessionTotal(session=self.session,
                                      paytype=pm.pm.get_paytype(),
                                      amount=pm.actual_total))
            else:
                ui.infopopup(
                    ["The {} payment method can't supply an actual total "
                     "at the moment.".format(pm.pm.description), "",
                     "Its error message is:",
                     str(pm.actual_total), "",
                     "Please try again later."],
                    title="Payment method error")
                td.s.rollback()
                return
        td.s.flush()
        for pm in self.pms:
            r = pm.pm.commit_total(self.session, pm.actual_total)
            if r is not None:
                td.s.rollback()
                ui.infopopup(["Totals not recorded: {} payment method "
                              "says {}".format(pm.pm.description, r)],
                             title="Payment method error")
                return
        self.dismiss()
        for i in SessionHooks.instances:
            i.postRecordSessionTakings(self.session.id)
        ui.toast("Printing the confirmed session totals.")
        with ui.exception_guard("printing the confirmed session totals",
                                title="Printer error"):
            printer.print_sessiontotals(self.session)

@user.permission_required('record-takings', "Record takings for a session")
def recordtakings():
    m = sessionlist(record, unpaidonly=True, closedonly=True)
    if len(m) == 0:
        log.info("Record takings: no sessions available")
        ui.infopopup(["Every session has already had its takings "
                      "recorded.  If you want to record takings for "
                      "the current session, you must close it first."],
                     title="Error")
    else:
        log.info("Record takings: displaying menu")
        ui.menu(m, title="Record Takings",
                blurb="Select the session that you "
                "want to record the takings for, and press Cash/Enter.")

def totalpopup(sessionid):
    """Display popup session totals given a Session ID.
    """
    s = td.s.query(Session).get(sessionid)
    log.info("Totals popup for session %d", s.id)

    depts = s.dept_totals # list of (Dept,total) tuples
    paytotals = dict(s.payment_totals)
    payments = dict([(x.paytype, x) for x in s.actual_totals])
    l = []
    l.append(" Accounting date {} ".format(s.date))
    l.append(" Started {:%Y-%m-%d %H:%M:%S} ".format(s.starttime))
    if s.endtime is None:
        l.append(" Session is still open. ")
    else:
        l.append(" Ended {:%Y-%m-%d %H:%M:%S} ".format(s.endtime))
    l.append("")
    tf = ui.tableformatter(" l pr  r ")
    l.append(tf("", "Till:", "Actual:"))
    ttt = zero
    att = zero
    for pm in tillconfig.all_payment_methods:
        pt = pm.get_paytype()
        till_total = paytotals.get(pt, zero)
        ttt += till_total
        actual_total = payments[pt].amount if pt in payments else zero
        att += actual_total
        if till_total or actual_total:
            l.append(tf(pt.description + ":",
                        tillconfig.fc(till_total) if till_total else "",
                        tillconfig.fc(actual_total) if actual_total else ""))
    l.append(tf("Total:", tillconfig.fc(ttt),
                tillconfig.fc(att) if att else ""))
    if att and att != ttt:
        l.append("    ({} by {})".format(
            "UP" if att > ttt else "DOWN",
            tillconfig.fc(abs(att - ttt))))
    l.append("")
    dt = zero
    df = ui.tableformatter(" r l pr ")
    for dept, total in depts:
        l.append(df(
            dept.id, dept.description, tillconfig.fc(total)))
        dt = dt + total
    l.append(ui.tableformatter(" l pr ")("Total", tillconfig.fc(dt)))
    l.append("")
    l.append(" Press Print for a hard copy ")
    keymap = {
        keyboard.K_PRINT: (printer.print_sessiontotals, (s,), False),
    }
    ui.listpopup(l,
                 title="Session number {}".format(s.id),
                 colour=ui.colour_info, keymap=keymap,
                 dismiss=keyboard.K_CASH, show_cursor=False)

@user.permission_required("session-summary", "Display a summary for any session")
def summary(maxlen=100):
    log.info("Session summary popup")
    m = sessionlist(totalpopup, maxlen=maxlen)
    if len(m) == maxlen:
        m.append(("Show all", summary, (None,)))
    ui.menu(m, title="Session Summary", blurb="Select a session and "
            "press Cash/Enter to view the summary.",
            dismiss_on_select=False)

@user.permission_required('current-session-summary', "Display a takings "
                          "summary for the current session")
def currentsummary():
    s = Session.current(td.s)
    if s is None:
        msg = ["There is no session in progress.", ""]
        # Show details of deferred transactions instead.
        deferred_total = td.s.query(func.sum(Transaction.total))\
                   .filter(Transaction.session == None)\
                   .scalar()
        if deferred_total:
            msg.append("There are deferred transactions totalling {}.".format(
                tillconfig.fc(deferred_total)))
        else:
            msg.append("There are no deferred transactions.")
        ui.infopopup(msg,
                     title="No current session",
                     colour=ui.colour_info,
                     dismiss=keyboard.K_CASH)
        return
    log.info("Totals popup for session %d (current)", s.id)

    # list of (Dept, total, closed_total, pending_total) tuples
    depts = s.dept_totals_closed
    paytotals = dict(s.payment_totals)
    l = []
    l.append(" Accounting date {} ".format(s.date))
    l.append(" Started {:%Y-%m-%d %H:%M:%S} ".format(s.starttime))
    l.append("")
    tf = ui.tableformatter(" l rp")
    for pm in tillconfig.payment_methods:
        pt = pm.get_paytype()
        if pt in paytotals:
            l.append(tf(pt.description + ":", tillconfig.fc(paytotals[pt])))
    l.append("")
    paid_total = zero
    pending_total = zero
    total_total = zero
    df = ui.tableformatter(" r l p r  r  r ")
    l.append(df(
        "", "Department", "Paid", "Pending", "Total"))
    for dept, total, paid, pending in depts:
        if paid or pending:
            l.append(df(
                dept.id, dept.description,
                tillconfig.fc(paid) if paid else "",
                tillconfig.fc(pending) if pending else "",
                tillconfig.fc(total or zero)))
            paid_total += paid or zero
            pending_total += pending or zero
            total_total += total or zero
    l.append(df(
        "", "Total:", tillconfig.fc(paid_total), tillconfig.fc(pending_total),
        tillconfig.fc(total_total)))
    l.append("")
    ui.listpopup(l,
                 title="Session number {}".format(s.id),
                 colour=ui.colour_info,
                 dismiss=keyboard.K_CASH, show_cursor=False)

@user.permission_required(
    'restore-deferred','Restore deferred transactions to the current session')
def restore_deferred():
    log.info("Restore deferred transactions")
    deferred = trans_restore()
    if deferred:
        ui.infopopup(["The following deferred transactions were restored "
                      "to this session:", ""] + [
                "{} - {}".format(d.id, d.notes) if d.notes else
                "{}".format(d.id) for d in deferred],
                     title="Deferred transactions restored",
                     colour=ui.colour_confirm, dismiss=keyboard.K_CASH)
    else:
        ui.infopopup(["There were no deferred transactions to be restored."],
                     title="No transactions restored", colour=ui.colour_confirm,
                     dismiss=keyboard.K_CASH)

class SessionHooks(metaclass=InstancePluginMount):
    """Hooks for sessions

    Accounting integration plugins should subclass this.  Subclass
    instances will be called in order of creation.  Calls will stop if
    an instance indicates that the action should not be taken.
    """
    def preRecordSessionTakings(self, sessionid):
        """Called before the Record Session Takings popup appears

        To prevent the popup from appearing, return True.  You may pop
        up your own information box in this case.
        """
        pass

    def postRecordSessionTakings(self, sessionid):
        """Called after the Record Session Takings popup is completed.

        The session takings will have been flushed to the database,
        but the transaction will not yet have been committed.  Some
        payment methods may have confirmed the session takings with
        external services.
        """
        pass

    def preUpdateSessionTakings(self, sessionid):
        """Called before the Update Session Takings popup appears

        To prevent the popup from appearing, return True.  You may pop
        up your own information box in this case.
        """
        pass

    def fetchReconciledSessionTakings(self, sessionid):
        """Called during setup of the Update Session Takings popup

        The accounting system can provide a list of payment types that
        are already reconciled for this session and which must not be
        changed.
        """
        return []

    def postUpdateSessionTakings(self, sessionid):
        """Called after the Update Session Takings popup is finished

        The session takings will have been flushed to the database,
        but the transaction will not yet have been committed.  Some
        payment methods may have confirmed the session takings with
        external services.
        """
        pass

def menu():
    """Session management menu."""
    log.info("Session management menu")
    menu = [
        ("1", "Start a session", start, None),
        ("2", "End the current session", end, None),
        ("3", "Record session takings", recordtakings, None),
        ("4", "Display session summary", summary, None),
        ("5", "Restore deferred transactions", restore_deferred, None),
    ]
    ui.keymenu(menu, title="Session management options")
