from . import payment, td, printer, ui
from . import tillconfig
from . import keyboard
from . import user
from .models import Payment, Transaction, zero
from decimal import Decimal


class CashPayment(payment.PaymentMethod):
    change_given = True
    refund_supported = True
    cancel_supported = True
    mergeable = True

    def __init__(self, paytype, description, change_description, drawers=1,
                 countup=["50", "20", "10", "5", "2", "1",
                          "0.50", "0.20", "0.10",
                          "0.05", "0.02", "0.01",
                          "Bags", "Misc", "-Float"],
                 account_code=None):
        super().__init__(paytype, description)
        self._change_description = change_description
        self._drawers = drawers
        self._total_fields = [(f"Tray {t+1}", ui.validate_float, countup)
                              for t in range(self._drawers)]
        self.account_code = account_code

    def describe_payment(self, payment):
        # Cash payments use the 'ref' field to store a description,
        # because they can be for many purposes: cash, change,
        # cashback, etc.
        return payment.ref

    def add_change(self, transaction, description, amount):
        user = ui.current_user().dbuser
        td.s.add(user)
        p = Payment(transaction=transaction, paytype=self.get_paytype(),
                    ref=description, amount=amount, user=user,
                    source=tillconfig.terminal_name)
        td.s.add(p)
        td.s.flush()
        return payment.pline(p, method=self)

    def start_payment(self, reg, transid, amount, outstanding):
        trans = td.s.query(Transaction).get(transid)
        description = self.description
        if amount < zero:
            if amount < outstanding:
                ui.infopopup(["You can't refund more than the amount we owe."],
                             title="Refund too large")
                return
            description = description + " refund"
        user = ui.current_user().dbuser
        td.s.add(user)
        p = Payment(transaction=trans, paytype=self.get_paytype(),
                    ref=description, amount=amount, user=user,
                    source=tillconfig.terminal_name)
        td.s.add(p)
        c = None
        if amount > zero:
            change = outstanding - amount
            if change < zero:
                c = Payment(transaction=trans, paytype=self.get_paytype(),
                            ref=self._change_description, amount=change,
                            user=user, source=tillconfig.terminal_name)
                td.s.add(c)
        td.s.flush()
        r = [payment.pline(p, method=self)]
        if c:
            r.append(payment.pline(c, method=self))
        printer.kickout()
        reg.add_payments(transid, r)

    @user.permission_required("cancel-cash-payment", "Cancel a cash payment")
    def cancel_payment(self, register, pline_instance):
        p = td.s.query(Payment).get(pline_instance.payment_id)
        if p.amount >= zero:
            title = "Cancel payment"
            message = [f"Press Cash/Enter to cancel this {p.ref} "
                       f"payment of {tillconfig.fc(p.amount)}.", "",
                       "If you have already put the payment in the drawer, "
                       "you should remove it when the drawer opens."]
        else:
            title = "Cancel refund"
            message = [f"Press Cash/Enter to cancel this {p.ref} "
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

    def total(self, session, fields):
        try:
            return sum(Decimal(x) if len(x) > 0 else zero for x in fields)
        except Exception:
            return "One or more of the total fields has something " \
                "other than a number in it."

    def accounting_info(self, sessiontotal):
        return self.account_code, sessiontotal.session.date, \
            f"{self.description} takings"
