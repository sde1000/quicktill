from . import payment
from .models import Payment,PayType

class CashPayment(payment.PaymentMethod):
    change_given=True
    def __init__(self,paytype,description,drawers=1):
        payment.PaymentMethod.__init__(self,paytype,description)
        self._drawers=drawers
    def describe_payment(self,payment):
        # Cash payments use the 'ref' field to store a description,
        # because they can be for many purposes: cash, change,
        # cashback, etc.
        return payment.ref
    def add_change(self,transaction,description,amount):
        p=Payment(transaction=transaction,paytype=self.get_paytype(),
                  ref=description,amount=amount)
        td.s.add(p)
        return payment.pline(p,method=self)
