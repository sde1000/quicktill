"""Starting, ending, and recording totals for sessions."""

from . import ui, keyboard, td, printer, tillconfig, user, managestock
from . import payment
from . import config
from .models import PayType, Session, SessionTotal, Transaction, zero
from sqlalchemy.orm import undefer
from sqlalchemy.sql import select, func, desc
from .plugins import InstancePluginMount
from decimal import Decimal
import datetime

import logging
log = logging.getLogger(__name__)

# Arguably these two config items should be "session:xxx" rather than
# "core:xxx" — but there's no good way to rename them at the moment
sessiontotal_print = config.BooleanConfigItem(
    'core:sessiontotal_print', True, display_name="Print session totals?",
    description="Should session totals be printed after they have been "
    "confirmed?")

sessioncountup_print = config.BooleanConfigItem(
    'core:sessioncountup_print', True, display_name="Print countup sheets?",
    description="Should a counting-up sheet be printed when a session "
    "is closed?")

session_date_rollover_time = config.TimeConfigItem(
    'session:date_rollover_time', datetime.time(23, 0),
    display_name="Session date rollover time",
    description="When a new session is started after this time of day, "
    "the date defaults to the next day instead of today.")

session_max_unconfirmed = config.PositiveIntConfigItem(
    'session:max_unconfirmed_sessions', None,
    display_name="Maximum number of unconfirmed sessions",
    description="If there are more than this number of sessions that "
    "do not yet have their totals confirmed, prevent a new session "
    "from being started. Leave blank to disable this feature.",
    allow_none=True)


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
        super().__init__(9, 63, title="Session date",
                         colour=ui.colour_input,
                         dismiss=keyboard.K_CLEAR)
        self.win.drawstr(
            2, 2, 59, "Please check the session date, and correct it "
            "if necessary.")
        self.win.drawstr(
            4, 2, 59, "Press Cash/Enter to continue and start the session.")
        self.win.drawstr(6, 2, 14, "Session date: ", align=">")
        now = datetime.datetime.now()
        if session_date_rollover_time():
            if now.time() >= session_date_rollover_time():
                now = now + datetime.timedelta(days=1)
        self.datefield = ui.datefield(6, 16, f=now.date(), keymap={
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
        user.log(f"Started session {sc.logref}")
        payment.notify_session_start(sc)
        if tillconfig.cash_drawer:
            printer.kickout(tillconfig.cash_drawer)
        if deferred:
            deferred = [
                "",
                "The following deferred transactions were restored:",
                ""] + [f"{d.id} — {d.notes}" if d.notes else
                       f"{d.id}" for d in deferred]
        ui.infopopup([f"Started session number {sc.id}."] + deferred,
                     title="Session started", colour=ui.colour_info,
                     dismiss=keyboard.K_CASH)


@user.permission_required("start-session", "Start a session")
def start():
    """Start a session if there is not already one in progress.
    """
    sc = Session.current(td.s)
    if sc:
        log.info("Start session: session %d still in progress", sc.id)
        ui.infopopup(
            [f"There is already a session in progress (number {sc.id}, "
             f"started {sc.starttime:%H:%M on %A})."],
            title="Error")
        return
    if session_max_unconfirmed() is not None:
        unconfirmed_count = len(
            sessionlist(None, unpaidonly=True, closedonly=True))
        log.debug("unconfirmed sessions count %d", unconfirmed_count)
        if unconfirmed_count > session_max_unconfirmed():
            ui.infopopup(
                ["You cannot start a new session yet, because there "
                 "are sessions that have not yet had their totals confirmed.",
                 "",
                 'You can confirm session totals using Manage Till option 1 '
                 'then option 3 ("Record session takings").'],
                title="Session totals missing")
            return
    ssdialog()


def checkendsession():
    if sessioncountup_print() and not tillconfig.receipt_printer:
        log.info("End session: no receipt printer")
        ui.infopopup(["This till does not have a receipt printer. Use "
                      "a different till to close the session and print "
                      "the counting-up sheet."],
                     title="Error")
        return
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
    if sessioncountup_print():
        # Check that the printer has paper before ending the session
        pp = tillconfig.receipt_printer.offline()
        if pp:
            ui.infopopup(["Could not end the session: there is a problem with "
                          f"the printer: {pp}"], title="Printer problem")
            return
    r.endtime = datetime.datetime.now()
    log.info("End of session %d confirmed.", r.id)
    user.log(f"Ended session {r.logref}")
    ui.infopopup([f"Session {r.id} has ended.",
                  "",
                  "Please count the cash in the drawer and enter the "
                  "actual amounts using management option 1, 3."],
                 title="Session Ended", colour=ui.colour_info,
                 dismiss=keyboard.K_CASH)
    if sessioncountup_print():
        ui.toast("Printing the countup sheet.")
        with ui.exception_guard("printing the session countup sheet",
                                title="Printer error"):
            printer.print_sessioncountup(tillconfig.receipt_printer, r.id)
        if tillconfig.cash_drawer:
            printer.kickout(tillconfig.cash_drawer)
    managestock.stock_purge_internal(source="session end")
    payment.notify_session_end(r)


@user.permission_required("end-session", "End a session")
def end():
    """End the current session if there is one.
    """
    r = checkendsession()
    if r:
        km = {keyboard.K_CASH: (confirmendsession, None, True)}
        log.info("End session popup: asking for confirmation")
        ui.infopopup(["Press Cash/Enter to confirm you want to end "
                      f"session number {r.id}."], title="Session End",
                     keymap=km, colour=ui.colour_confirm)


def sessionlist(cont, paidonly=False, unpaidonly=False, closedonly=False,
                maxlen=None):
    """Return a list of sessions suitable for a menu.
    """
    q = td.s.query(Session)\
            .order_by(desc(Session.id))\
            .options(undefer(Session.total))
    if paidonly:
        q = q.filter(select(func.count(SessionTotal.sessionid))
                     .where(SessionTotal.sessionid == Session.id)
                     .correlate(Session.__table__).scalar_subquery() != 0)
    if unpaidonly:
        q = q.filter(select(func.count(SessionTotal.sessionid))
                     .where(SessionTotal.sessionid == Session.id)
                     .correlate(Session.__table__).scalar_subquery() == 0)
    if closedonly:
        q = q.filter(Session.endtime != None)
    if maxlen:
        q = q[:maxlen]
    f = ui.tableformatter(' r  l  r ')
    return [(f(x.id, x.date, tillconfig.fc(x.total)), cont, (x.id,))
            for x in q]


class _PMWrapper:
    """Payment method wrapper for record session takings popup.

    Remembers the total and where to put it when it's updated.
    """
    def __init__(self, paytype_id, till_total, popup):
        self.paytype_id = paytype_id
        pt = td.s.get(PayType, paytype_id)
        self.description = pt.description
        self.total_fields = pt.driver.total_fields
        self.lines = 1 if len(self.total_fields) <= 1 \
            else len(self.total_fields) + 1
        self.till_total = till_total
        self.actual_total = zero
        self.fees = zero
        self.total_valid = False
        self.total_problem = ""
        self.fields = []
        self.popup = popup

    def create_total_labels(self, y):
        self.total_label = ui.label(
            y, self.popup.atx, self.popup.ffw, align=">")
        self.fees_label = ui.label(
            y, self.popup.ftx, self.popup.ffw, align=">")

    def display_total(self):
        if self.total_valid:
            self.total_label.set(tillconfig.fc(self.actual_total))
            self.fees_label.set(tillconfig.fc(self.fees))
        else:
            self.total_label.set("Error", colour=ui.colour_error)
            self.fees_label.set("Error", colour=ui.colour_error)

    def update_total(self):
        pt = td.s.get(PayType, self.paytype_id)
        try:
            self.actual_total, self.fees = pt.driver.total(
                self.popup.sessionid, [f.f for f in self.fields])
            self.total_valid = True
            self.total_problem = ""
        except Exception as e:
            self.actual_total = zero
            self.total_valid = False
            self.total_problem = str(e)
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
    ftx = 60
    ff = "{:>13}"
    ffw = 13

    def __init__(self, sessionid):
        if sessiontotal_print() and not tillconfig.receipt_printer:
            ui.infopopup(["This till does not have a receipt printer "
                          "to print the session totals after they have "
                          "been recorded. Use a till that has a printer."],
                         title="Error")
            return
        log.info("Record session takings popup: session %d", sessionid)
        self.sessionid = sessionid
        s = td.s.get(Session, sessionid)
        if not self.session_valid(s):
            return
        for i in SessionHooks.instances:
            if i.preRecordSessionTakings(s.id):
                return
        paytotals = dict(s.payment_totals)
        payment_methods = td.s.query(PayType)\
            .filter(PayType.mode != "disabled")\
            .order_by(PayType.order, PayType.paytype)\
            .all()
        # Check that all payment methods are correctly configured
        for pm in payment_methods:
            if not pm.driver.config_valid:
                ui.infopopup(
                    [f"The {pm.description} payment method is not configured "
                     f"correctly.",
                     "",
                     f"The problem is: {pm.driver.config_problem}"],
                    title="Error")
                return
        self.pms = [
            _PMWrapper(pt.paytype, paytotals.get(pt, zero), self)
            for pt in payment_methods]
        self.till_total = s.total
        # How tall does the window need to be?  Each payment type
        # takes a minimum of one line; if len(pt.total_fields()) > 1
        # then it takes len(pt.total_fields()) + 1 lines
        h = sum(pm.lines for pm in self.pms)
        # We also need the top border (2), a prompt and header at the
        # top (3) and a total and button at the bottom (4) and the
        # bottom border (2).
        h = h + 11
        super().__init__(h, 75, title=f"Session {s.id}",
                         colour=ui.colour_input)
        self.win.drawstr(
            2, 2, 56, f"Please enter the actual takings for session {s.id}.")
        self.win.drawstr(4, self.ttx, self.ffw, "Till total:", align=">")
        self.win.drawstr(4, self.atx, self.ffw, "Actual total:", align=">")
        self.win.drawstr(4, self.ftx, self.ffw, "Fees:", align=">")
        y = 5
        self.fl = []
        for pm in self.pms:
            pm.create_total_labels(y)
            self.win.drawstr(
                y, self.ttx, self.ffw, tillconfig.fc(pm.till_total),
                align=">")
            self.win.drawstr(y, 2, 18, f"{pm.description}:")
            if len(pm.total_fields) == 0:
                # No data entry; just the description
                pm.fields = []
            elif len(pm.total_fields) == 1:
                # Single field using the description with no indent
                field = pm.total_fields[0]
                f = ui.editfield(y, 20, 8, validate=field[1])
                self.fl.append(f)
                pm.fields.append(f)
                f.sethook = pm.update_total
            else:
                # Line with payment method description and totals, then
                # one line per field with indent
                for field in pm.total_fields:
                    y = y + 1
                    self.win.drawstr(y, 4, 16, f"{field[0]}:")
                    f = ui.editfield(y, 20, 8, validate=field[1])
                    self.fl.append(f)
                    pm.fields.append(f)
                    f.sethook = pm.update_total
            y = y + 1
        y = y + 1
        self.total_y = y
        self.total_label = ui.label(self.total_y, 2, self.ttx - 4)
        # Draw the till total now, because it doesn't change
        self.win.clear(self.total_y, self.ttx, 1, self.ffw,
                       colour=ui.colour_confirm)
        self.win.drawstr(
            self.total_y, self.ttx, self.ffw,
            tillconfig.fc(self.till_total), colour=ui.colour_confirm,
            align=">")
        self.total_amount = ui.label(
            self.total_y, self.atx, self.ffw, align=">")
        self.fees_amount = ui.label(
            self.total_y, self.ftx, self.ffw, align=">")
        y = y + 2
        self.fl.append(ui.buttonfield(y, 27, 21, 'Record'))
        ui.map_fieldlist(self.fl)
        # Override key bindings for first/last fields
        self.fl[0].keymap[keyboard.K_CLEAR] = (self.dismiss, None)
        self.fl[-1].keymap[keyboard.K_CASH] = (self.finish, None)
        self.fl[0].focus()
        for pm in self.pms:
            pm.update_total()

    def update_total(self):
        """A payment method wrapper has changed its total.

        Redraw the total line at the bottom of the window.
        """
        if False in (pm.total_valid for pm in self.pms):
            self.total_label.set("Can't calculate total",
                                 colour=ui.colour_error)
            self.total_amount.set("Error", colour=ui.colour_error)
            self.fees_amount.set("Error", colour=ui.colour_error)
            return
        total = sum(pm.actual_total for pm in self.pms)
        fees = sum(pm.fees for pm in self.pms)
        difference = self.till_total - total
        description = "Total (DOWN by {})"
        if difference == zero:
            description = "Total (correct)"
        elif difference < zero:
            difference = -difference
            description = "Total (UP by {})"
        colour = ui.colour_error if difference > Decimal(20) \
            else ui.colour_input
        self.total_label.set(
            description.format(tillconfig.fc(difference)),
            colour=colour)
        self.total_amount.set(
            tillconfig.fc(total),
            colour=ui.colour_confirm)
        self.fees_amount.set(
            tillconfig.fc(fees),
            colour=ui.colour_confirm)

    @staticmethod
    def session_valid(session):
        """Is the session eligible to have its totals recorded?

        The session object is assumed to be in the current ORM
        session.

        Returns True if the session is still valid, otherwise pops up
        an error dialog and returns False.
        """
        if session.endtime is None:
            ui.infopopup([f"Session {session.id} is not finished."],
                         title="Error")
            return False
        if session.actual_totals:
            ui.infopopup([f"Session {session.id} has already had totals "
                          "recorded."], title="Error")
            return False
        return True

    def finish(self):
        session = td.s.get(Session, self.sessionid)
        if not self.session_valid(session):
            return
        for pm in self.pms:
            if not pm.total_valid:
                ui.infopopup(
                    [f"The {pm.description} payment method can't "
                     f"supply an actual total at the moment.", "",
                     f"Its error message is: {pm.total_problem}", "",
                     "Please try again later."],
                    title="Payment method error")
                return
        for pm in self.pms:
            pt = td.s.get(PayType, pm.paytype_id)
            td.s.add(SessionTotal(
                session=session, paytype=pt, amount=pm.actual_total,
                fees=pm.fees))
        td.s.flush()
        user.log(f"Recorded totals for session {session.logref}")
        for pm in self.pms:
            pt = td.s.get(PayType, pm.paytype_id)
            r = pt.driver.commit_total(self.sessionid, pm.actual_total, pm.fees)
            if r is not None:
                td.s.rollback()
                ui.infopopup(
                    [f"Totals not recorded: {pm.description} payment "
                     f"method says {r}"],
                    title="Payment method error")
                return
        self.dismiss()
        for i in SessionHooks.instances:
            i.postRecordSessionTakings(session.id)
        if sessiontotal_print() and tillconfig.receipt_printer:
            ui.toast("Printing the confirmed session totals.")
            with ui.exception_guard("printing the confirmed session totals",
                                    title="Printer error"):
                printer.print_sessiontotals(
                    tillconfig.receipt_printer, session.id)
        else:
            ui.toast(f"Totals for session {session.id} confirmed.")


@user.permission_required('record-takings', "Record takings for a session")
def recordtakings():
    if sessiontotal_print() and not tillconfig.receipt_printer:
        ui.infopopup(["This till does not have a receipt printer "
                      "to print the session totals after they have "
                      "been recorded. Use a till that has a printer."],
                     title="Error")
        return
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
    s = td.s.get(Session, sessionid)
    log.info("Totals popup for session %d", s.id)

    # All PayTypes
    all_pts = td.s.query(PayType)\
                  .order_by(PayType.order, PayType.paytype)\
                  .all()
    # list of (Dept, total) tuples
    depts = s.dept_totals
    # dict of {PayType: total} for transactions
    paytotals = dict(s.payment_totals)
    # dict of {PayType: SessionTotal} for actual amounts paid
    payments = {x.paytype: x for x in s.actual_totals}
    l = []
    l.append(f" Accounting date {s.date} ")
    l.append(f" Started {s.starttime:%Y-%m-%d %H:%M:%S} ")
    if s.endtime is None:
        l.append(" Session is still open. ")
    else:
        l.append(f" Ended {s.endtime:%Y-%m-%d %H:%M:%S} ")
    l.append("")
    tf = ui.tableformatter(" l pr  r ")
    l.append(tf("", "Till:", "Actual:"))
    ttt = zero
    att = zero
    for pt in all_pts:
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
    keymap = {}
    if tillconfig.receipt_printer:
        l.append("")
        l.append(" Press Print for a hard copy ")
        keymap[keyboard.K_PRINT] = (printer.print_sessiontotals, (
            tillconfig.receipt_printer, s.id), False)
    ui.listpopup(l,
                 title=f"Session number {s.id}",
                 colour=ui.colour_info, keymap=keymap,
                 dismiss=keyboard.K_CASH, show_cursor=False)


@user.permission_required(
    "session-summary", "Display a summary for any session")
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

    # list of (Dept, total, paid, pending) keyed tuples
    depts = s.dept_totals_closed
    paytotals = dict(s.payment_totals)
    l = []
    l.append(f" Accounting date {s.date} ")
    l.append(f" Started {s.starttime:%Y-%m-%d %H:%M:%S} ")
    l.append("")
    tf = ui.tableformatter(" l rp")
    for pt in td.s.query(PayType)\
                  .order_by(PayType.order, PayType.paytype)\
                  .all():
        if pt in paytotals:
            l.append(tf(pt.description + ":", tillconfig.fc(paytotals[pt])))
    l.append("")
    paid_total = zero
    pending_total = zero
    total_total = zero
    df = ui.tableformatter(" r l p r  r  r ")
    l.append(df(
        "", "Department", "Paid", "Pending", "Total"))
    for x in depts:
        if x.paid or x.pending:
            l.append(df(
                x.Department.id, x.Department.description,
                tillconfig.fc(x.paid) if x.paid else "",
                tillconfig.fc(x.pending) if x.pending else "",
                tillconfig.fc(x.total or zero)))
            paid_total += x.paid or zero
            pending_total += x.pending or zero
            total_total += x.total or zero
    l.append(df(
        "", "Total:", tillconfig.fc(paid_total), tillconfig.fc(pending_total),
        tillconfig.fc(total_total)))
    l.append("")
    ui.listpopup(l,
                 title=f"Session number {s.id}",
                 colour=ui.colour_info,
                 dismiss=keyboard.K_CASH, show_cursor=False)


@user.permission_required(
    'restore-deferred', 'Restore deferred transactions to the current session')
def restore_deferred():
    log.info("Restore deferred transactions")
    user.log("Restored deferred transactions")
    deferred = trans_restore()
    if deferred:
        ui.infopopup(["The following deferred transactions were restored "
                      "to this session:", ""] + [
                          f"{d.id} — {d.notes}" if d.notes else
                          f"{d.id}" for d in deferred],
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
