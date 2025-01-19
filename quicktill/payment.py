from . import ui, tillconfig, td, user, keyboard
from .models import PayType, Payment, Transaction, Session, zero
from .cmdline import command
import datetime
from decimal import Decimal


# PayType.payment_date_policy -> payment date policy function
# Payment date policy function takes a datetime.date()
# and returns a datetime.date()
date_policy = dict()


date_policy["same-day"] = lambda x: x


# PayType.driver_name -> payment driver class
drivers = dict()


class PaymentTotalError(Exception):
    "A payment driver could not retrieve payment totals"
    pass


class _PaymentDriverMeta(type):
    def __init__(cls, name, bases, attrs):
        drivers[name] = cls


def _driver_factory(paytype):
    """Return the driver for a PaymentType object.

    If no driver is present, returns an instance of the base
    PaymentDriver class
    """
    return drivers.get(paytype.driver_name, PaymentDriver)(paytype)


PayType.driver_factory = _driver_factory


class pline(ui.line):
    """Payment line

    A payment in a transaction, suitable for inclusion in the display
    list of a register.
    """
    def __init__(self, payment):
        super().__init__()
        self.payment_id = payment.id
        self.update()

    def update(self):
        super().update()
        payment = td.s.get(Payment, self.payment_id)
        self.amount = payment.amount
        self.transtime = payment.time
        self.pending = payment.pending
        if payment.pending:
            self.text = f"{payment.text} pending"
        else:
            self.text = f"{payment.text} {tillconfig.fc(payment.amount)}"
        self.colour = ui.colour_cashline if self.amount >= zero \
            else ui.colour_changeline
        self.cursor_colour = self.colour.reversed

    def display(self, width):
        self.cursor = (0, 0)
        return [self.text.rjust(width)]

    def age(self):
        return datetime.datetime.now() - self.transtime


class PaymentDriver(metaclass=_PaymentDriverMeta):
    add_payment_supported = False  # Noninteractive payment supported
    change_given = False      # Overpayment is supported
    refund_supported = False  # Negative payment is supported
    cancel_supported = False  # Payment can be cancelled instead of refunded
    deferrable = False        # Payment can stay with a deferred transaction
    mergeable = False         # Payment can stay with a merged transaction

    def __init__(self, paytype):
        """paytype must be a models.PayType instance attached to the current
        database session
        """
        self.paytype = paytype
        self.configure()

    def configure(self):
        """Read the configuration from the PayType
        """
        self.config_exception = None
        self.config_problem = ""
        try:
            self.config_problem = self.read_config()
            self.config_valid = not self.config_problem
        except Exception as e:
            self.config_valid = False
            self.config_exception = e
            self.config_problem = str(e)

    def read_config(self):
        """Read and validate the configuration from the PayType instance

        If there is a problem, return a string describing the problem
        """
        return f"Driver '{self.paytype.driver_name}' not found"

    def add_payment(self, transaction, description, amount):
        """Add a payment to the transaction with no user interaction

        Returns a pline if successful, otherwise None.
        """
        pass

    def start_payment(self, register, transid, amount, outstanding):
        # We don't permit new payments with no drivers
        ui.infopopup(
            [f"New {self.paytype.description} payments are not supported."],
            title="Payment type not supported")

    def resume_payment(self, register, payment_instance):
        # The default payment method doesn't support pending payments
        ui.infopopup(
            [f"{self.paytype.description} payments can't be resumed."],
            title="Pending payments not supported")

    def cancel_payment(self, register, pline_instance):
        ui.infopopup(
            [f"{self.paytype.description} payments can't be cancelled."],
            title="Cancelling payment not supported")

    def receipt_details(self, d, payment_instance):
        # Add information about a payment to a receipt.
        # "d" is a pdriver.ReceiptCanvas instance.
        pass

    @property
    def total_fields(self):
        """Fetch a list of input fields for end of day session totals

        Returns a list of input fields for end of day session totals.
        The list consists of tuples of (name, validator, print_fields)
        and may be empty if the payment method does not require manual
        entry of session totals.

        If the list has a length greater than 1, name does not need to
        be unique across all payment methods because it will always be
        used in the context of the payment method's description.  If
        the list has length 1 then name will be ignored and the
        description will be used instead.

        validator may be None or a field validator from the ui module

        print_fields may be None or a list of strings to print on the
        counting-up slip above the input field
        (eg. "50", "20", "10", ... for a cash drawer).
        """
        return []

    def total(self, sessionid, fields):
        """Total to record for session

        Given a Session id and the contents of the fields defined in
        the total_fields property, return the total and fees that
        should be recorded for this payment method as a (Decimal,
        Decimal).

        If we raise a PaymentTotalError exception, this will be
        displayed to the user as the reason they can't record session
        totals at the moment.
        """
        return (zero, zero)

    def commit_total(self, sessionid, amount, fees):
        """Commit a total for this payment method

        Called when the total for a session is about to be committed
        to the database.  If we return anything other than None then
        the commit will be aborted and whatever we return will be
        displayed.
        """
        return

    def manage(self):
        """Display UI for managing this payment method

        Most configuration should be done through the web
        interface. Some payment methods may require some configuration
        to be done directly on the till, for example if they need to
        make API calls to external providers and can only access the
        necessary credentials from the till.
        """
        ui.infopopup(
            [f"There are no management functions for the "
             f"{self.paytype.description} payment method "
             f"on the till."],
            title=f"Manage {self.paytype.description} payments",
            colour=ui.colour_info)

    def search(self, func):
        """Display UI for searching for a payment

        When a payment is found, func() should be called with the
        transaction ID of the payment as its argument.
        """
        payment_search_popup(func, self.paytype)

    def notify_session_start(self, session):
        """Perform any operations needed at the start of a session

        This may include contacting external services or setting up
        payment hardware.

        Not interactive. Cannot veto the start of a session.
        """
        pass

    def notify_session_end(self, session):
        """Perform any operations needed at the end of a session

        This may include contacting external services or closing down
        payment hardware.

        Not interactive. Cannot veto the end of a session.
        """
        pass

    def configure_cmd(self):
        """Interactive configuration from the command line

        Use for configuration that can't be performed from the web
        interface, for example if API calls need to be made using a
        secret from the configuration file.
        """
        print("This payment method has no interactive configuration options.")


class payment_search_popup(ui.dismisspopup):
    """Popup to allow a payment to be searched for

    Calls func with the payment's transaction ID as the argument.

    This is a generic, default implementation. Some payment drivers
    will want to supply their own implementation.
    """
    def __init__(self, func, paytype):
        self._func = func
        self._paytype_id = paytype.paytype
        super().__init__(
            11, 70, title=f"Search for a {paytype.description} payment",
            colour=ui.colour_input)
        self.win.drawstr(2, 2, 13, "Description: ", align=">")
        self.win.drawstr(3, 2, 13, "Amount: ", align=">")
        self.win.drawstr(3, 35, 30, "(leave blank for 'any')")
        self.win.drawstr(5, 2, 26, "Number of days to search: ",
                         align=">")
        self.win.drawstr(6, 15, 40, "(leave blank for current day only)")
        self.textfield = ui.editfield(
            2, 15, 53,
            keymap={
                keyboard.K_CLEAR: (self.dismiss, None)})
        self.amountfield = ui.editfield(
            3, 15, 10, validate=ui.validate_float)
        self.daysfield = ui.editfield(5, 28, 3, validate=ui.validate_int)
        self.searchbutton = ui.buttonfield(
            8, 30, 10, "Search", keymap={
                keyboard.K_CASH: (self.enter, None, False)})
        ui.map_fieldlist([self.textfield, self.amountfield, self.daysfield,
                          self.searchbutton])
        self.textfield.focus()

    def enter(self):
        self.dismiss()
        paytype = td.s.get(PayType, self._paytype_id)
        try:
            days = int(self.daysfield.f)
        except Exception:
            days = 0
        after = datetime.date.today() - datetime.timedelta(days=days)

        q = td.s.query(Payment)\
                .join(Transaction)\
                .join(Session)\
                .filter(Payment.paytype == paytype)\
                .filter(Session.date >= after)\
                .order_by(Payment.id.desc())

        if self.textfield.f:
            q = q.filter(Payment.text.ilike(f'%{self.textfield.f}%'))
        if self.amountfield.f:
            try:
                amount = Decimal(self.amountfield.f)
                q = q.filter(Payment.amount == amount)
            except Exception:
                pass
        f = ui.tableformatter(" l l r ")
        header = f("Time", "Description", "Amount")
        menu = [(f(ui.formattime(x.time), x.text, tillconfig.fc(x.amount)),
                 self._func, (x.transid,)) for x in q.limit(1000).all()]
        ui.menu(menu, blurb=header, title="Search results")


@user.permission_required(
    "manage-payment-methods", "Manage payment methods on the till")
def manage():
    ui.automenu([(x.description,
                  lambda p: td.s.get(PayType, p).driver.manage(),
                  (x.paytype,))
                 for x in td.s.query(PayType)
                 .order_by(PayType.order, PayType.paytype)
                 .filter(PayType.mode == "active").all()],
                title="Manage payment methods",
                blurb="To add new payment methods or change the configuration "
                "of existing ones, use the web interface.")


def notify_session_start(session):
    """Notify payment methods that a session is starting

    Some payment methods may need to contact external services or set
    up payment hardware for a new session.
    """
    for pm in td.s.query(PayType)\
                  .order_by(PayType.order, PayType.paytype)\
                  .filter(PayType.mode != "disabled")\
                  .all():
        pm.driver.notify_session_start(session)


def notify_session_end(session):
    """Notify payment methods that a session is ending

    Some payment methods may need to contact external services or
    close down payment hardware at the end of a session.
    """
    for pm in td.s.query(PayType)\
                  .order_by(PayType.order, PayType.paytype)\
                  .filter(PayType.mode != "disabled")\
                  .all():
        pm.driver.notify_session_end(session)


# This permission is used in the web interface to control creation and
# editing of payment methods
user.action_descriptions['edit-payment-methods'] = \
    "Create or alter payment methods"


class PaymentConfigCommand(command):
    command = "payment-config"
    help = "configure a payment method interactively"

    @staticmethod
    def add_arguments(parser):
        parser.add_argument(
            "code", action="store", nargs=1,
            help="Code of payment method to configure")

    @staticmethod
    def run(args):
        code = args.code[0]
        with td.orm_session():
            pm = td.s.get(PayType, code)
            if not pm:
                print(f"Payment method '{code}' not found. Valid payment "
                      f"methods are:")
                pms = td.s.query(PayType)\
                          .order_by(PayType.order, PayType.paytype)\
                          .all()
                for pm in pms:
                    print(f"{pm.paytype} ({pm.mode})")
                return 1
            return pm.driver.configure_cmd()
