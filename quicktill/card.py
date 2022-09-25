import logging
from . import payment, ui, td, tillconfig, keyboard, printer
from .models import PayType, Session, Payment, Transaction, zero, penny
from decimal import Decimal
import datetime
import json

log = logging.getLogger(__name__)


class CardPayment(payment.PaymentConfig):
    def __init__(self, paytype, description, machines=1, cashback_method=None,
                 max_cashback=zero, kickout=False,
                 rollover_guard_time=None,
                 account_code="", account_date_policy=None,
                 ask_for_machine_id=False,
                 ref_required=True):
        super().__init__(paytype, description)
        self.machines = machines
        self.ask_for_machine_id = ask_for_machine_id if machines > 1 else False
        self.ref_required = ref_required
        self.cashback_method = cashback_method.paytype if cashback_method \
            else None
        self.max_cashback = max_cashback
        self.kickout = kickout
        self.rollover_guard_time = rollover_guard_time
        self.account_code = account_code
        # We can't make use of account_date_policy, unfortunately

    def configure(self, pt):
        pt.driver_name = Card.__name__
        pt.payments_account = self.account_code
        pt.config = json.dumps({
            'machines': self.machines,
            'ask_for_machine_id': self.ask_for_machine_id,
            'ref_required': self.ref_required,
            'cashback_method': self.cashback_method,
            'max_cashback': str(self.max_cashback),
            'kickout': self.kickout,
            'rollover_guard_time': str(self.rollover_guard_time),
        })


class _cardpopup(ui.dismisspopup):
    """Ask for card payment details

    A window that pops up whenever a card payment is accepted.  It
    prompts for the card receipt number (provided by the credit card
    terminal) and whether there is any cashback on this transaction.
    """
    def __init__(self, paytype_id, reg, transid, amount, refund=False):
        self.paytype_id = paytype_id
        pt = td.s.query(PayType).get(paytype_id)
        self.reg = reg
        self.transid = transid
        self.amount = amount
        if pt.driver._cashback_method:
            self.max_cashback = pt.driver._max_cashback
        else:
            self.max_cashback = zero
        self.ask_for_machine_id = pt.driver._ask_for_machine_id
        self.cashback_in_use = self.max_cashback > zero and not refund
        h = 18 if self.cashback_in_use else 10
        if self.ask_for_machine_id:
            h += 1
        desc = "refund" if refund else "payment"
        super().__init__(
            h, 44, title=f"{pt} {desc} transaction {transid}",
            colour=ui.colour_input)
        self.win.wrapstr(
            2, 2, 40, f"{pt} {desc} of {tillconfig.fc(amount)}")
        y = 4
        fields = []
        if self.cashback_in_use:
            y += self.win.wrapstr(
                y, 2, 40,
                "Is there any cashback?  Enter the amount and "
                "press Cash/Enter.  Leave blank and press "
                "Cash/Enter if there is none.")
            y += 1
            self.win.drawstr(y, 2, 17, "Cashback amount: ", align=">")
            self.win.addstr(y, 19, tillconfig.currency())
            self.cbfield = ui.moneyfield(y, 19 + len(tillconfig.currency()), 6)
            fields.append(self.cbfield)
            y += 2
            self.total_label = ui.label(y, 2, 40)
            y += 2
            self.cbfield.sethook = self.update_total_amount
            self.update_total_amount()
        y += self.win.wrapstr(
            y, 2, 40,
            "Please enter the receipt number from the merchant receipt.")
        y += 1

        if self.ask_for_machine_id:
            self.win.drawstr(y, 2, 17, "Terminal number: ", align=">")
            self.mnfield = ui.editfield(y, 19, 3)
            fields.append(self.mnfield)
            y += 1

        self.win.drawstr(y, 2, 17, "Receipt number: ", align=">")
        self.rnfield = ui.editfield(y, 19, 16)
        fields.append(self.rnfield)
        ui.map_fieldlist(fields)
        fields[0].keymap[keyboard.K_CLEAR] = (self.dismiss, None)
        fields[-1].keymap[keyboard.K_CASH] = (self.enter, None)
        fields[0].focus()

    def update_total_amount(self):
        try:
            cashback = Decimal(self.cbfield.f).quantize(penny)
        except Exception:
            cashback = zero
        if cashback > self.max_cashback:
            self.total_label.set(
                f"Maximum cashback is {tillconfig.fc(self.max_cashback)}",
                colour=ui.colour_error)
        else:
            self.total_label.set(
                f"Total card payment: {tillconfig.fc(self.amount + cashback)}")

    def enter(self):
        pt = td.s.query(PayType).get(self.paytype_id)
        if self.cashback_in_use:
            try:
                cashback = Decimal(self.cbfield.f).quantize(penny)
            except Exception:
                cashback = zero
            if cashback > self.max_cashback:
                self.cbfield.set("")
                self.cbfield.focus()
                return ui.infopopup(
                    [f"Cashback is limited to a maximum of "
                     f"{tillconfig.fc(self.max_cashback)} per transaction."],
                    title="Error")
        else:
            cashback = zero
        tl = [pt.description]
        if self.ask_for_machine_id:
            machineno = self.mnfield.f
            if machineno == "" and pt.driver._ref_required:
                self.mnfield.focus()
                return ui.infopopup(["You must enter a card machine id."],
                                    title="Error")
            if machineno:
                tl.append(machineno)

        receiptno = self.rnfield.f
        if receiptno == "" and pt.driver._ref_required:
            self.rnfield.focus()
            return ui.infopopup(["You must enter a receipt number."],
                                title="Error")
        if receiptno:
            tl.append(receiptno)

        self.dismiss()

        trans = td.s.query(Transaction).get(self.transid)
        user = ui.current_user().dbuser
        td.s.add(user)
        if not trans or trans.closed:
            ui.infopopup(["The transaction was closed before the payment "
                          "could be recorded.  The payment has been "
                          "ignored."], title="Transaction closed")
            return
        total = self.amount + cashback
        if total < zero:
            tl.append("refund")
        p = Payment(transaction=trans, paytype=pt,
                    text=' '.join(tl), amount=total, user=user,
                    source=tillconfig.terminal_name)
        td.s.add(p)
        td.s.flush()
        r = [payment.pline(p)]
        if cashback > zero:
            r.append(pt.driver._cashback_method.driver.add_change(
                trans, f"{pt.description} cashback",
                zero - cashback))
        if cashback > zero or pt.driver._kickout:
            printer.kickout()
        td.s.flush()
        self.reg.add_payments(self.transid, r)


class Card(payment.PaymentDriver):
    """Accept payments using a manual PDQ machine.

    This payment method records the receipt number ("reference") from
    the PDQ machine as confirmation, and optionally supports cashback.

    The kickout parameter sets whether the cash drawer will be opened
    on a card transaction that does not include cashback.

    rollover_guard_time is the time at which the card terminals roll
    over from recording one day's totals to recording the next.  For
    example, if rollover_guard_time is 3am then transactions at 2am on
    2nd February will be recorded against the card machine totals for
    1st February, and transactions at 4am on 2nd February will be
    recorded against the card machine totals for 2nd February.  This
    time is determined by the bank; it can't be configured directly on
    the card machines.

    If rollover_guard_time is set then the card machine totals date
    will be checked against the current session's date, and the
    payment will be prevented if it would be recorded against the
    wrong day.

    The ask_for_machine_id parameter sets whether the card payment
    dialog will ask for a card machine id, which will be added to the
    reference field. This only makes sense if you have more than one
    machine.

    If ref_required is set to False then blank entries for machine ID
    (if present) and reference will be permitted.
    """
    refund_supported = True

    def read_config(self):
        try:
            c = json.loads(self.paytype.config)
        except Exception:
            return "Config is not valid json"

        problem = ""

        self._machines = c.get('machines', 1)
        self._ask_for_machine_id = c.get('ask_for_machine_id', False) \
            if self._machines > 1 else False
        self._ref_required = c.get('ref_required', False)

        self._cashback_method = None
        cashback_paytype_id = c.get('cashback_method', None)
        if cashback_paytype_id:
            cashback_pt = td.s.query(PayType).get(cashback_paytype_id)
            if not cashback_pt:
                problem = "Cashback method does not exist"
            elif not cashback_pt.active:
                problem = "Cashback method is not active"
            elif not cashback_pt.driver.change_given:
                problem = "Cashback method does not support change"
            else:
                self._cashback_method = cashback_pt

        self._max_cashback = Decimal(c.get('max_cashback', zero))
        self._kickout = c.get('kickout', False)
        self._total_fields = [(f"Terminal {t + 1}",
                               ui.validate_float, None)
                              for t in range(self._machines)]

        self._rollover_guard_time = c.get('rollover_guard_time', None)
        if self._rollover_guard_time:
            self._rollover_guard_time = datetime.time.fromisoformat(
                self._rollover_guard_time)

        return problem

    def start_payment(self, reg, transid, amount, outstanding):
        if not self.config_valid:
            ui.infopopup([f"Config problem: {self.config_problem=}"],
                         title="Error")
            return
        if self._rollover_guard_time:
            session = Session.current(td.s)
            # session should not be None; this should have been
            # checked in register code before we are called.
            if not session:
                return
            now = datetime.datetime.now()
            date = now.date()
            if now.time() < self._rollover_guard_time:
                date = date - datetime.timedelta(days=1)
            if date != session.date:
                ui.infopopup(
                    [f"The card machines 'roll over' from one day to the next "
                     f"at around {self._rollover_guard_time}, so a card "
                     f"transaction performed now would be recorded against "
                     f"the card totals for {date}.",
                     "",
                     f"The current session is for {session.date}.",
                     "",
                     f"Please don't perform a card transaction now.  If you "
                     f"have already done one, you must call your manager "
                     f"and let them know that the card totals for {date} "
                     f"and {session.date} will be incorrect.  Set aside the "
                     f"card merchant receipt so that it can be entered into "
                     f"the till later."],
                    title=f"{self.paytype} transactions not allowed")
                return
        if amount < zero:
            if amount < outstanding:
                ui.infopopup(
                    ["You can't refund more than the amount due back."],
                    title="Refund too large")
                return
            _cardpopup(self, reg, transid, amount, refund=True)
            return
        if amount > outstanding:
            if self._cashback_method:
                ui.infopopup(
                    ["You can't take an overpayment on cards.  If the card "
                     "being used allows cashback, the card terminal "
                     "will prompt you and you can give up to %s back." % (
                         tillconfig.fc(self._max_cashback))],
                    title="Overpayment not accepted")
            else:
                ui.infopopup(
                    ["You can't take an overpayment on cards."],
                    title="Overpayment not accepted")
            return
        _cardpopup(self.paytype.paytype, reg, transid, amount)

    @property
    def total_fields(self):
        return self._total_fields

    def total(self, sessionid, fields):
        try:
            return (sum(Decimal(x) if len(x) > 0 else zero for x in fields),
                    zero)
        except Exception:
            raise payment.PaymentTotalError(
                "One or more of the total fields has something "
                "other than a number in it.")
