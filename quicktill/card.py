from . import payment
from .models import zero

class BadCashbackMethod(Exception):
    pass

class CardPayment(payment.PaymentMethod):
    def __init__(self,paytype,description,machines=1,cashback_method=None,
                 max_cashback=zero):
        payment.PaymentMethod.__init__(self,paytype,description)
        self._machines=machines
        self._cashback_method=cashback_method
        if cashback_method and not cashback_method.change_given:
            raise BadCashbackMethod()
    def describe_payment(self,payment):
        # Card payments use the 'ref' field for the card receipt number
        return u"%s %s"%(self.description,payment.ref)
