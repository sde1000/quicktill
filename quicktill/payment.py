from . import ui, tillconfig, td
from .models import PayType, Payment, zero
import datetime

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
        self.amount=payment.amount
        if method is None: method=methods[payment.paytype_id]
        self.method=method
        ui.line.__init__(self,colour=ui.colour_cashline if self.amount>=zero
                         else ui.colour_changeline)
        self.update()
    def update(self):
        payment=td.s.query(Payment).get(self.payment_id)
        self.amount=payment.amount
        self.transtime=payment.time
        self.text="%s %s"%(self.method.describe_payment(payment),
                           tillconfig.fc(payment.amount))
        self.cursor=(0,0)
    def display(self,width):
        return [' '*(width-len(self.text))+self.text]
    def age(self):
        return datetime.datetime.now() - self.transtime
    def description(self):
        payment=td.s.query(Payment).get(self.payment_id)
        return self.method.describe_payment(payment)
    def is_pending(self):
        return self.method.payment_is_pending(self)
    def resume(self,register):
        return self.method.resume_payment(register,self)

class PaymentMethod(object):
    change_given=False
    refund_supported=False
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
    def payment_is_pending(self,pline_instance):
        return False
    def resume_payment(self,register,pline_instance):
        # The default payment method doesn't support pending payments
        ui.infopopup(["{} payments can't be resumed.".format(self.description)],
                     title="Pending payments not supported")
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
        """Total to record for session

        Given a Session and the contents of the fields defined in the
        total_fields property, return the total that should be
        recorded for this payment method.

        If we return anything other than a Decimal then no total will
        be displayed and it will not be possible for the user to
        record session totals; this should be done if the payment
        method is temporarily unable to calculate the total.

        If we return a string, this will be displayed to the user as
        the reason they can't record session totals.
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
