from . import ui,tillconfig,td
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

class pline(ui.line):
    """
    A payment in a transaction, suitable for inclusion in the display
    list of a register.

    """
    def __init__(self,payment,method=None):
        self.payment_id=payment.id
        amount=payment.amount
        if method is None: method=methods[payment.paytype_id]
        self.method=method
        ui.line.__init__(self,colour=ui.colour_cashline if amount>=zero
                         else ui.colour_changeline)
        self.update()
    def update(self):
        payment=td.s.query(Payment).get(self.payment_id)
        self.text=u"%s %s"%(self.method.describe_payment(payment),
                            tillconfig.fc(payment.amount))
        self.cursor=(0,0)
    def display(self,width):
        return [' '*(width-len(self.text))+self.text]

class PaymentMethod(object):
    change_given=False
    def __init__(self,paytype,description):
        self.paytype=paytype
        self.description=description
        methods[paytype]=self
    def start_payment(self,register,transaction,amount,outstanding):
        # We don't permit new payments of the default type
        ui.infopopup(["New {} payments are not supported.".format(
                    self.description)],title="Payment type not supported")
    def describe_payment(self,payment):
        return payment.paytype.description
    def get_paytype(self):
        pt=PayType(paytype=self.paytype,description=self.description)
        return td.s.merge(pt)
    @property
    def total_fields(self):
        """
        A list of input fields for end of day session totals.  The
        list consists of tuples of (name,validator,print_fields) and
        may be empty if the payment method does not require manual
        entry of session totals.

        If the list has a length greater than 1, name does not need to
        be unique across all payment methods because it will always be
        used in the context of the payment method's description.  If
        the list has length 1 then name will be ignored and the
        description will be used instead.

        validator may be None or a field validator from the ui module

        print_fields may be None or a list of strings to print on the
        counting-up slip above the input field
        (eg. "50","20","10",... for a cash drawer).

        """
        return []
    def total(self,session,fields):
        """
        Given a Session and the contents of the fields defined in the
        total_fields property, return the total that should be
        recorded for this payment method.

        """
        return zero
    def commit_total(self,session,amount):
        """
        Called when the total for a session is about to be committed
        to the database.  If we return anything other than None then
        the commit will be aborted and whatever we return will be
        displayed.

        """
        return
