from . import ui,tillconfig
from models import PayType,Payment,zero

class DuplicatePayType(Exception):
    pass

class PaymentMethodRegistry(dict):
    def __getitem__(self,key):
        if key in self: return dict.__getitem__(self,key)
        # Unknown payment method: create a default one and return it
        return PaymentMethod(key,key)
    def __setitem__(self,key,val):
        if key in self: raise DuplicatePayType()
        dict.__setitem__(self,key,val)

methods=PaymentMethodRegistry()

class pline(ui.emptyline):
    """
    A payment in a transaction, suitable for inclusion in the display
    list of a register.

    """
    def __init__(self,payment,method=None):
        self.payment=payment
        amount=payment.amount
        if method is None: method=methods[payment.paytype]
        self.method=method
        ui.emptyline.__init__(self,colour=ui.colour_cashline if amount>=zero
                              else ui.colour_changeline)
        self.update()
    def update(self):
        self.text=u"%s %s"%(self.method.describe_payment(payment),
                            tillconfig.fc(amount))
        self.cursor=(0,0)
    def display(self,width):
        return ' '*(width-len(self.text))+self.text

class PaymentMethod(object):
    change_given=False
    def __init__(self,paytype,description):
        self.paytype=paytype
        self.description=description
        methods[paytype]=self
    def new_payment(self,register,transaction,amount=None):
        # We don't permit new payments of the default type
        pass
    def describe_payment(self,payment):
        return payment.paytype.description
    def get_paytype(self):
        pt=PayType(paytype=self.paytype,description=self.description)
        return td.s.merge(pt)
