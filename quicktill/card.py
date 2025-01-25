import logging
from . import payment, ui, td, tillconfig, keyboard, printer
from .models import PayType, Session, Payment, Transaction, zero, penny
from decimal import Decimal
import decimal
import datetime
import json

log = logging.getLogger(__name__)


class _cardpopup(ui.dismisspopup):
    """Ask for card payment details

    A window that pops up whenever a card payment is accepted.  It
    prompts for the card receipt number (provided by the credit card
    terminal) and whether there is any cashback on this transaction.
    """
    def __init__(self, paytype_id, reg, transid, amount, refund=False):
        self.paytype_id = paytype_id
        pt = td.s.get(PayType, paytype_id)
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
            y, 2, 40, pt.driver._ref_prompt)
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
        pt = td.s.get(PayType, self.paytype_id)
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

        trans = td.s.get(Transaction, self.transid)
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
            r.append(pt.driver._cashback_method.driver.add_payment(
                trans, f"{pt.description} cashback",
                zero - cashback))
        if (cashback > zero or pt.driver._kickout) and tillconfig.cash_drawer:
            printer.kickout(tillconfig.cash_drawer)
        td.s.flush()
        self.reg.add_payments(self.transid, r)


class Card(payment.PaymentDriver):
    """Accept payments using a manual PDQ machine.

    This payment method records the receipt number ("reference") from
    the PDQ machine as confirmation, and optionally supports cashback.

    Configuration parameters:

    - cashback_method (optional string) is the code of the payment
      method to use for cashback. This payment method must exist, not
      be disabled, support refunds, and support noninteractive
      payments.

    - max_cashback (string, default "0.00"; Decimal) is the maximum
      amount of cashback that is allowed per transaction. If set to
      zero, the cashback feature is disabled.

    - machines (integer, default 1) is the number of terminals in use.

    - ask_for_machine_id (boolean, default False) sets whether the
      card payment dialog will ask for a card machine id, which will
      be added to the reference field. This only makes sense if you
      have more than one machine; this setting is ignored if the
      "machines" setting is 1.

    - ask_for_totals (boolean, default True) controls whether the user
      is requested to enter the totals from each card terminal, or
      whether the total of all the transactions in the session is
      assumed to be correct.

    - kickout (boolean, default False) sets whether the cash drawer
      will be opened on a card transaction that does not include
      cashback.

    - rollover_guard_time (optional string; time of day in ISO format)
      is the time at which the card terminals roll over from recording
      one day's totals to recording the next.  For example, if
      rollover_guard_time is 3am then transactions at 2am on 2nd
      February will be recorded against the card machine totals for
      1st February, and transactions at 4am on 2nd February will be
      recorded against the card machine totals for 2nd February.  This
      time is determined by the bank; it can't be configured directly
      on the card machines. If rollover_guard_time is set then the
      card machine totals date will be checked against the current
      session's date, and the payment will be prevented if it would be
      recorded against the wrong day.

    - ref_prompt (string, default "Please enter the receipt number
      from the merchant receipt") will be displayed above the Receipt
      number field in the card payment popup.

    - ref_required (boolean, default False) determines whether blank
      entries for machine ID (if present) and reference will be
      permitted.

    - refund_guard (boolean, default False) determines whether refunds
      can be created when there is no payment of this type in the
      transaction's history. It is intended to prevent refunds being
      recorded with the wrong payment type by accident; it's possible
      to circumvent if you are determined (by recording a payment of
      this type, and then a larger refund).

    Payment service providers that send payouts net of fees are
    supported by the following parameters:

    - fee_pct (float, default 0.0) is the percentage fee charged; for
      example 1.69 means "1.69%"

    - fee_calculation_method (string, default "per-session") is either
      "per-session" or "per-payment" (only available if
      "ask_for_totals" is set to False). If set to "per-payment" then
      the fee will be calculated by summing the fee calculated for
      each individual payment in the session.

    - fee_rounding_mode (string, default "ROUND_HALF_EVEN") is the
      rounding mode to be used when calculating fees. See the python
      Decimal library for descriptions of all the available rounding
      modes. "ROUND_HALF_EVEN" is "Banker's Rounding".

    """
    refund_supported = True

    rounding_modes = {
        'ROUND_CEILING': decimal.ROUND_CEILING,
        'ROUND_DOWN': decimal.ROUND_DOWN,
        'ROUND_FLOOR': decimal.ROUND_FLOOR,
        'ROUND_HALF_DOWN': decimal.ROUND_HALF_DOWN,
        'ROUND_HALF_EVEN': decimal.ROUND_HALF_EVEN,
        'ROUND_HALF_UP': decimal.ROUND_HALF_UP,
        'ROUND_UP': decimal.ROUND_UP,
        'ROUND_05UP': decimal.ROUND_05UP,
    }

    def read_config(self):
        try:
            c = json.loads(self.paytype.config)
        except Exception:
            return "Config is not valid json"

        problem = ""

        self._machines = c.get('machines', 1)
        self._ask_for_machine_id = c.get('ask_for_machine_id', False) \
            if self._machines > 1 else False

        self._ref_prompt = c.get(
            'ref_prompt',
            "Please enter the receipt number from the merchant receipt.")
        self._ref_required = c.get('ref_required', False)

        self._refund_guard = c.get('refund_guard', False)

        self._cashback_method = None
        cashback_paytype_id = c.get('cashback_method', None)
        if cashback_paytype_id:
            cashback_pt = td.s.get(PayType, cashback_paytype_id)
            if not cashback_pt:
                problem = "Cashback method does not exist"
            elif not cashback_pt.active:
                problem = "Cashback method is not active"
            elif not cashback_pt.driver.refund_supported:
                problem = "Cashback method does not support refunds"
            elif not cashback_pt.driver.add_payment_supported:
                problem = "Cashback method does not support noninteractive "\
                    "payments"
            else:
                self._cashback_method = cashback_pt

        self._max_cashback = Decimal(c.get('max_cashback', zero))
        self._kickout = c.get('kickout', False)

        self._ask_for_totals = c.get('ask_for_totals', True)
        if self._ask_for_totals:
            self._total_fields = [(f"Terminal {t + 1}",
                                   ui.validate_float, None)
                                  for t in range(self._machines)]
        else:
            self._total_fields = []

        self._rollover_guard_time = c.get('rollover_guard_time', None)
        if self._rollover_guard_time:
            self._rollover_guard_time = datetime.time.fromisoformat(
                self._rollover_guard_time)

        self._fee = Decimal(c.get('fee_pct', "0.0")) / Decimal("100")
        fee_calculation_method = c.get('fee_calculation_method', 'per-session')
        if fee_calculation_method not in ("per-session", "per-payment"):
            problem = f"Bad fee calculation method '{fee_calculation_method}'"
        self._fee_per_transaction = False
        if not self._ask_for_totals:
            if fee_calculation_method == 'per-payment':
                self._fee_per_transaction = True
        fee_rounding_mode = c.get('fee_rounding_mode', 'ROUND_HALF_EVEN')
        if fee_rounding_mode in self.rounding_modes:
            self._fee_rounding_mode = self.rounding_modes[fee_rounding_mode]
        else:
            self._fee_rounding_mode = decimal.ROUND_UP
            problem = f"Unknown rounding mode '{fee_rounding_mode}'"

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
        if self._kickout and not tillconfig.cash_drawer:
            ui.infopopup(["This till doesn't have a cash drawer for you "
                          "to put the card receipt in. Use a different till "
                          "to take the card payment."], title="Error")
            return
        if amount < zero:
            if amount < outstanding:
                ui.infopopup(
                    ["You can't refund more than the amount due back."],
                    title="Refund too large")
                return
            if self._refund_guard:
                # Check whether there are any payments of this type in
                # the transaction history
                trans = td.s.get(Transaction, transid)
                if not trans:
                    ui.infopopup(
                        ["Transaction does not exist; cannot refund."],
                        title="Error")
                    return
                related_transids = trans.related_transaction_ids()
                payments = td.s.query(Payment)\
                               .filter(Payment.paytype == self.paytype)\
                               .filter(Payment.transid.in_(related_transids))\
                               .filter(Payment.amount > zero)\
                               .all()
                if len(payments) == 0:
                    ui.infopopup(
                        [f"There are no {self.paytype.description} payments "
                         f"related to this transaction, so you cannot refund "
                         f"via {self.paytype.description}.",
                         "",
                         "Have you chosen the correct payment type for this "
                         "refund?"], title="Error")
                    return
            _cardpopup(self.paytype.paytype, reg, transid, amount, refund=True)
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
        if self._ask_for_totals:
            try:
                total = sum(Decimal(x) if len(x) > 0 else zero for x in fields)
            except Exception:
                raise payment.PaymentTotalError(
                    "One or more of the total fields has something "
                    "other than a number in it.")
        else:
            session = td.s.get(Session, sessionid)
            total = zero
            for paytype, amount in session.payment_totals:
                if paytype == self.paytype:
                    total = amount
                    break
        if self._fee_per_transaction:
            payments = td.s.query(Payment)\
                           .join(Transaction)\
                           .filter(Transaction.sessionid == sessionid)\
                           .filter(Payment.paytype == self.paytype)\
                           .all()
            fee = sum(((p.amount * self._fee)
                       .quantize(penny, rounding=self._fee_rounding_mode)
                       for p in payments), start=zero)
        else:
            fee = (total * self._fee).quantize(
                penny, rounding=self._fee_rounding_mode)
        return (total, fee)
