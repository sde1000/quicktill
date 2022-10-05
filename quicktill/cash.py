from . import payment, td, printer, ui
from . import tillconfig
from . import keyboard
from . import user
from .models import Payment, Transaction, zero
from decimal import Decimal
import json

_default_countup = [
    "50", "20", "10", "5", "2", "1",
    "0.50", "0.20", "0.10",
    "0.05", "0.02", "0.01",
    "Bags", "Misc", "-Float",
]


class CashPayment(payment.PaymentConfig):
    def __init__(self, paytype, description, change_description, drawers=1,
                 countup=_default_countup,
                 account_code=""):
        super().__init__(paytype, description)
        self.change_description = change_description
        self.drawers = drawers
        self.countup = countup
        self.account_code = account_code

    def configure(self, pt):
        pt.driver_name = Cash.__name__
        pt.payments_account = self.account_code
        pt.config = json.dumps({
            'change_description': self.change_description,
            'drawers': self.drawers,
            'countup': self.countup,
        })


class Cash(payment.PaymentDriver):
    add_payment_supported = True
    change_given = True
    refund_supported = True
    cancel_supported = True
    mergeable = True

    def read_config(self):
        try:
            c = json.loads(self.paytype.config)
        except Exception:
            return "Config is not valid json"

        self._change_description = c.get('change_description', 'Change')
        self._drawers = c.get('drawers', 1)
        self._countup = c.get('countup', _default_countup)
        self._total_fields = [
            (f"Tray {t + 1}", ui.validate_float, self._countup)
            for t in range(self._drawers)]

    def add_payment(self, transaction, description, amount):
        # Typically used by other payment drivers for cashback, or by
        # the register when deferring part-paid transactions
        user = ui.current_user().dbuser
        td.s.add(user)
        p = Payment(transaction=transaction, paytype=self.paytype,
                    text=description, amount=amount, user=user,
                    source=tillconfig.terminal_name)
        td.s.add(p)
        td.s.flush()
        return payment.pline(p)

    def start_payment(self, reg, transid, amount, outstanding):
        trans = td.s.query(Transaction).get(transid)
        description = self.paytype.description
        if amount < zero:
            if amount < outstanding:
                ui.infopopup(["You can't refund more than the amount we owe."],
                             title="Refund too large")
                return
            description = description + " refund"
        user = ui.current_user().dbuser
        td.s.add(user)
        p = Payment(transaction=trans, paytype=self.paytype,
                    text=description, amount=amount, user=user,
                    source=tillconfig.terminal_name)
        td.s.add(p)
        c = None
        if amount > zero:
            change = outstanding - amount
            if change < zero:
                c = Payment(transaction=trans, paytype=self.paytype,
                            text=self._change_description, amount=change,
                            user=user, source=tillconfig.terminal_name)
                td.s.add(c)
        td.s.flush()
        r = [payment.pline(p)]
        if c:
            r.append(payment.pline(c))
        printer.kickout()
        reg.add_payments(transid, r)

    @user.permission_required("cancel-cash-payment", "Cancel a cash payment")
    def cancel_payment(self, register, pline_instance):
        p = td.s.query(Payment).get(pline_instance.payment_id)
        if p.amount >= zero:
            title = "Cancel payment"
            message = [f"Press Cash/Enter to cancel this {p.text} "
                       f"payment of {tillconfig.fc(p.amount)}.", "",
                       "If you have already put the payment in the drawer, "
                       "you should remove it when the drawer opens."]
        else:
            title = "Cancel refund"
            message = [f"Press Cash/Enter to cancel this {p.text} "
                       f"payment of {tillconfig.fc(zero-p.amount)}.", "",
                       "If you have already removed the payment from "
                       "the drawer, you should put it back when the "
                       "drawer opens."]
        ui.infopopup(message, title=title, keymap={
            keyboard.K_CASH: (register.cancelpayment,
                              (pline_instance, ), True)})

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
