from . import payment,td,printer,ui
from .models import Payment,PayType,zero
from decimal import Decimal

class CashPayment(payment.PaymentMethod):
    change_given=True
    def __init__(self,paytype,description,change_description,drawers=1,
                 countup=["50","20","10","5","2","1",
                          "0.50","0.20","0.10",
                          "0.05","0.02","0.01",
                          "Bags","Misc","-Float"]):
        payment.PaymentMethod.__init__(self,paytype,description)
        self._change_description=change_description
        self._drawers=drawers
        self._total_fields=[(u"Tray {t}".format(t=t+1),
                             ui.validate_float,countup)
                            for t in range(self._drawers)]
    def describe_payment(self,payment):
        # Cash payments use the 'ref' field to store a description,
        # because they can be for many purposes: cash, change,
        # cashback, etc.
        return payment.ref
    def add_change(self,transaction,description,amount):
        p=Payment(transaction=transaction,paytype=self.get_paytype(),
                  ref=description,amount=amount)
        td.s.add(p)
        td.s.flush()
        return payment.pline(p,method=self)
    def start_payment(self,reg,trans,amount,outstanding):
        p=Payment(transaction=trans,paytype=self.get_paytype(),
                  ref=self.description,amount=amount)
        td.s.add(p)
        r=[payment.pline(p,method=self)]
        change=outstanding-amount
        if change<zero:
            c=Payment(transaction=trans,paytype=self.get_paytype(),
                      ref=self._change_description,amount=change)
            td.s.add(c)
            r.append(payment.pline(c,method=self))
        td.s.flush()
        printer.kickout()
        reg.add_payments(trans,r)
    @property
    def total_fields(self):
        return self._total_fields
    def total(self,session,fields):
        try:
            return sum(Decimal(x) if len(x)>0 else zero for x in fields)
        except:
            return zero
