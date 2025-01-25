# Add quicktill.xero to /etc/quicktill/default-imports to enable Xero
# setup command-line options

from requests_oauthlib import OAuth2Session
from oauthlib.oauth2 import WebApplicationClient
from oauthlib.oauth2.rfc6749.errors import InvalidGrantError, AccessDeniedError
from xml.etree.ElementTree import Element, SubElement, tostring, fromstring
import datetime
import secrets
import hashlib
import base64
import json
import logging
from . import session
from . import payment
from . import ui
from . import td
from . import user
from . import delivery
from . import keyboard
from . import cmdline
from . import config
from . import secretstore
from .models import Session, zero
from .models import Delivery, Supplier
log = logging.getLogger(__name__)

# Zap the very unhelpful behaviour from oauthlib when Xero returns
# more scopes than requested
import os
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = "true"

XERO_ENDPOINT_URL = "https://api.xero.com/api.xro/2.0/"
XERO_AUTHORIZE_URL = "https://login.xero.com/identity/connect/authorize"
XERO_CONNECT_URL = "https://identity.xero.com/connect/token"
XERO_REVOKE_URL = "https://identity.xero.com/connect/revocation"
XERO_CONNECTIONS_URL = "https://api.xero.com/connections"


class PKCE(WebApplicationClient):
    """Proof Key for Code Exchange by OAuth Public Clients - RFC7636
    """
    @staticmethod
    def _b64encode_without_padding(b):
        return base64.urlsafe_b64encode(b).split(b'=')[0]

    def prepare_request_uri(self, *args, **kwargs):
        self.code_verifier = self._b64encode_without_padding(
            secrets.token_bytes(32))
        code_challenge = self._b64encode_without_padding(
            hashlib.sha256(self.code_verifier).digest())
        return super().prepare_request_uri(
            *args, code_challenge=code_challenge,
            code_challenge_method="S256", **kwargs)

    def prepare_request_body(self, *args, **kwargs):
        return super().prepare_request_body(
            *args, code_verifier=self.code_verifier, **kwargs)


class XeroError(Exception):
    pass


def xero_not_connected():
    ui.infopopup(
        ["The till is not connected to Xero. If it was previously connected, "
         "the connection may have expired if it was not used for more "
         "than sixty days.",
         "",
         'To connect to Xero, use "runtill xero-connect" at the command line.',
         "",
         "You will need to be able to copy-and-paste between the terminal "
         "and a web browser to authenticate with Xero."],
        title="Xero not available")


class XeroSessionHooks(session.SessionHooks):
    def __init__(self, xero):
        self.xero = xero

    def preRecordSessionTakings(self, sessionid):
        if not self.xero.connection_ok():
            xero_not_connected()
            return True

    def postRecordSessionTakings(self, sessionid):
        session = td.s.get(Session, sessionid)
        if self.xero.start_date() and self.xero.start_date() > session.date:
            return
        # Commit at this point to ensure the totals are recorded in
        # the till database.
        td.s.commit()
        ui.toast("Sending session details to accounting system...")
        try:
            with ui.exception_guard("creating the Xero invoice",
                                    suppress_exception=False):
                invid, negative_totals = self.xero._create_invoice_for_session(
                    sessionid, approve=self.xero.auto_approve_invoice())
        except XeroError:
            return
        # Record the Xero invoice ID
        session.accinfo = invid
        # We want to commit the invoice ID to the database even if adding
        # payments fails, so we can try again later
        td.s.commit()
        if self.xero.auto_approve_invoice() and not negative_totals:
            try:
                with ui.exception_guard("adding payments to the Xero invoice",
                                        suppress_exception=False):
                    self.xero._add_payments_for_session(sessionid, invid)
            except XeroError:
                return
        ui.toast("Session details uploaded to Xero.")


class XeroDeliveryHooks(delivery.DeliveryHooks):
    def __init__(self, xero):
        self.xero = xero

    def preConfirm(self, deliveryid):
        d = td.s.get(Delivery, deliveryid)
        if self.xero.start_date() and self.xero.start_date() > d.date:
            return
        if not d.supplier.accinfo:
            return
        if not self.xero.connection_ok():
            xero_not_connected()
            return True

    def confirmed(self, deliveryid):
        d = td.s.get(Delivery, deliveryid)
        if self.xero.start_date() and self.xero.start_date() > d.date:
            ui.toast("Not sending this delivery to Xero - delivery is dated "
                     "before the Xero start date")
            return
        if not d.supplier.accinfo:
            ui.toast("Not sending this delivery to Xero - the supplier "
                     "is not linked to a Xero contact")
            return
        self.xero._send_delivery(deliveryid)


class XeroIntegration:
    """Xero accounting system integration

    To integrate with Xero, create an instance of this class in the
    till configuration file.  You should add an "Apps" menu entry that
    calls the instance's app_menu() method to enable users to access
    the integration utilities menu.
    """
    _integrations = []

    def __init__(self,
                 config_prefix="xero",
                 secrets=None,
                 **obsolete_kwargs):
        self._integrations.append(self)

        self.secrets = secrets

        # Configuration items: now to be stored in the database
        self.client_id = config.ConfigItem(
            f"{config_prefix}:client_id", '',
            display_name="Xero OAuth2 client ID",
            description="Client ID of the Xero integration app; if you "
            "need one, create a new 'Auth code with PKCE' app at "
            "https://developer.xero.com/myapps — feel free to use "
            "https://quicktill.assorted.org.uk/xero.html as the redirect URI.")
        self.redirect_uri = config.ConfigItem(
            f"{config_prefix}:redirect_uri",
            "https://quicktill.assorted.org.uk/xero.html",
            display_name="Xero OAuth2 redirect URI",
            description="URI of a web page to receive the code generated by "
            "Xero during OAuth2 PKCE authorisation. Any page that simply "
            "displays the 'code' and 'state' parameters from the URL "
            "will work.")
        self.tenant_id = config.ConfigItem(
            f"{config_prefix}:tenant_id", '',
            display_name="Xero tenant ID",
            description="Tenant ID of the Xero organisation to use. A list of "
            "available tenant IDs and their corresponding organisation names "
            "will be printed after authorisation; copy the one you want to use "
            "here. Tenant IDs are stable and will not change upon "
            "reauthorisation.")
        self.sales_contact_id = config.ConfigItem(
            f"{config_prefix}:sales_contact_id", '',
            display_name="Xero sales contact ID",
            description="ID of the contact to use for the invoices generated "
            "for each session")
        self.tracking_category_name = config.ConfigItem(
            f"{config_prefix}:tracking_category_name", '',
            display_name="Xero tracking category name",
            description="Name of a tracking category to use for all invoice "
            "and bill lines")
        self.tracking_category_value = config.ConfigItem(
            f"{config_prefix}:tracking_category_value", '',
            display_name="Xero tracking category value",
            description="Value to use for tracking category for all invoice "
            "and bill lines")
        self.department_tracking_category_name = config.ConfigItem(
            f"{config_prefix}:department_tracking_category_name", '',
            display_name="Xero department tracking category name",
            description="Name of a tracking category to use for invoice and "
            "bill lines relating to departments.  The value will be read from "
            "the department sales_account and purchases_account fields; "
            "it is separated from the account number by a '/' character.")
        self.reference_template = config.ConfigItem(
            f"{config_prefix}:reference_template", "Session {session.id}",
            display_name="Xero invoice reference template",
            description="Template for the reference that will be added to "
            "each invoice generated. You can refer to aspects of the relevant "
            "session using, for example, {session.id} or {session.date}.")
        self.due_days = config.IntConfigItem(
            f"{config_prefix}:due_days", 7,
            display_name="Xero invoice due days",
            description="Invoices created for sessions will be listed as "
            "'due' this number of days after the session date.")
        self.tillweb_base_url = config.ConfigItem(
            f"{config_prefix}:tillweb_base_url", '',
            display_name="Xero tillweb base URL",
            description="URL for the Main Menu page of the till web "
            "interface; this will be used to create 'Go to Till integration' "
            "links to sessions and deliveries from invoices and bills in Xero")
        self.branding_theme_id = config.ConfigItem(
            f"{config_prefix}:branding_theme_id", '',
            display_name="Xero branding theme ID",
            description="ID of the branding theme to use for invoices created "
            "in Xero; leave blank for the default")
        # Ignore shortcode; it's only used in the web interface
        self.discrepancy_account = config.ConfigItem(
            f"{config_prefix}:discrepancy_account", '',
            display_name="Xero discrepancy account",
            description="Account code to be used for discrepancies between "
            "till total and actual total when creating invoices")
        self.suspense_account = config.ConfigItem(
            f"{config_prefix}:suspense_account", '',
            display_name="Xero suspense account",
            description="Account code to be used when a payment method has "
            "a negative total for a session, since Xero does not support "
            "negative payments on invoices. Once the invoice is approved, "
            "you can create a 'Spend money' transaction from the bank account "
            "for the payment method to the suspense account to balance.")
        self.auto_approve_invoice = config.BooleanConfigItem(
            f"{config_prefix}:auto_approve_invoice", True,
            display_name="Xero auto approve invoice?",
            description="Should the invoice generated for a session be "
            "approved automatically, if possible? If it can be approved, "
            "payments will also be added. If not, it will be left as a draft.")
        self.start_date = config.DateConfigItem(
            f"{config_prefix}:start_date", None,
            display_name="Xero start date",
            description="If set, sessions and deliveries will only be sent "
            "to Xero if they are on or after this date.")

        XeroSessionHooks(self)
        XeroDeliveryHooks(self)

        if obsolete_kwargs:
            log.warning(
                "Obsolete XeroIntegration keyword arguments present in "
                "configuration file: %s", ', '.join(obsolete_kwargs.keys()))

    def connection_ok(self):
        try:
            self.secrets.fetch('token')
        except secretstore.SecretException:
            return False
        session = self.xero_session(omit_tenant=True)
        try:
            r = session.get(XERO_CONNECTIONS_URL)
        except InvalidGrantError:
            return False
        if r.status_code != 200:
            return False
        connections = r.json()
        for tenant in connections:
            if tenant['tenantId'] == self.tenant_id():
                return True
        return False

    def xero_session(self, state=None, omit_tenant=False):
        kwargs = {}
        try:
            token = self.secrets.fetch('token', lock_for_update=True)
            kwargs['token'] = json.loads(token)
        except secretstore.SecretException:
            pass

        def token_updater(token):
            nonlocal self
            self.secrets.store('token', json.dumps(token),
                               create=True)

        kwargs['token_updater'] = token_updater
        kwargs['auto_refresh_kwargs'] = {
            'client_id': self.client_id(),
        }
        kwargs['auto_refresh_url'] = XERO_CONNECT_URL
        if state:
            kwargs['state'] = state

        session = OAuth2Session(
            self.client_id(),
            client=PKCE(self.client_id()),
            redirect_uri=self.redirect_uri(),
            scope=["offline_access", "accounting.transactions",
                   "accounting.contacts", "accounting.settings"],
            **kwargs)

        if not omit_tenant:
            session.headers = {
                'xero-tenant-id': self.tenant_id(),
                'accept': 'application/xml',
            }

        return session

    def _get_sales_contact(self, session):
        contact = None
        if self.sales_contact_id():
            contact = Element("Contact")
            contact.append(_textelem("ContactID", self.sales_contact_id()))
        return contact

    @staticmethod
    def _tracking_list_to_xml(tracking):
        if tracking:
            t = Element("Tracking")
            for name, option in tracking:
                tc = SubElement(t, "TrackingCategory")
                tc.append(_textelem("Name", name))
                tc.append(_textelem("Option", option))
            return t

    def _get_general_tracking(self):
        tracking = []
        if self.tracking_category_name() and self.tracking_category_value():
            tracking.append((self.tracking_category_name(),
                             self.tracking_category_value()))
        return tracking

    def _get_sales_tracking(self, department):
        tracking = self._get_general_tracking()
        if department and self.department_tracking_category_name():
            v = self._sales_tracking_for_department(department)
            if v:
                tracking.append((self.department_tracking_category_name(), v))
        return self._tracking_list_to_xml(tracking)

    def _get_purchases_tracking(self, department):
        tracking = self._get_general_tracking()
        if department and self.department_tracking_category_name():
            v = self._purchases_tracking_for_department(department)
            if v:
                tracking.append((self.department_tracking_category_name(), v))
        return self._tracking_list_to_xml(tracking)

    def _get_fees_tracking(self):
        return self._tracking_list_to_xml(self._get_general_tracking())

    @user.permission_required("xero-admin", "Xero integration admin")
    def app_menu(self):
        if not self.connection_ok():
            xero_not_connected()
            return
        ui.automenu(
            [("Link a supplier with a Xero contact",
              choose_supplier,
              (self._link_supplier_with_contact, False)),
             ("Unlink a supplier from its Xero contact",
              choose_supplier,
              (self._unlink_supplier, True)),
             ("Send a delivery to Xero as a bill",
              choose_delivery,
              (self._send_delivery, self.start_date(), False)),
             ("Re-send a delivery to Xero as a bill",
              choose_delivery,
              (self._send_delivery, self.start_date(), True)),
             ("Test the connection to Xero",
              self.check_connection, ()),
             ("Xero debug menu",
              self._debug_menu, ())],
            title="Xero options")

    @user.permission_required("xero-debug", "Low-level access to the "
                              "Xero integration")
    def _debug_menu(self):
        ui.automenu(
            [("Send invoice and payments for a session",
              self._debug_choose_session,
              (self._debug_send_invoice_and_payments,)),
             ("Send invoice only for a session",
              self._debug_choose_session,
              (self._debug_send_invoice,)),
             ("Send payments for an existing invoice",
              self._debug_choose_session,
              (self._debug_send_payments,)),
             ("Send bill for a delivery",
              self._debug_choose_delivery,
              (self._debug_send_bill,))
             ],
            title="Xero debug")

    def _debug_choose_session(self, cont):
        ui.menu(
            session.sessionlist(
                cont, paidonly=True, closedonly=True, maxlen=100),
            title="Choose session")

    def _debug_choose_delivery(self, cont):
        dl = td.s.query(Delivery)\
                 .order_by(Delivery.checked)\
                 .order_by(Delivery.date.desc())\
                 .order_by(Delivery.id.desc())\
                 .all()
        f = ui.tableformatter(' r l l l l ')
        lines = [(f(x.id, x.supplier.name, x.date, x.docnumber or "",
                    "" if x.checked else "not confirmed"),
                  cont, (x.id,)) for x in dl]
        ui.menu(lines, title="Delivery List",
                blurb="Select a delivery and press Cash/Enter.")

    def _debug_send_invoice_and_payments(self, sessionid):
        log.info("Sending invoice and payments for %d", sessionid)
        iid, negative_totals = self._create_invoice_for_session(
            sessionid, approve=self.auto_approve_invoice())
        session = td.s.get(Session, sessionid)
        session.accinfo = iid
        td.s.commit()
        if self.auto_approve_invoice() and not negative_totals:
            self._add_payments_for_session(sessionid, iid)
        log.info("...new invoice ID is %s", iid)
        ui.infopopup([f"Invoice ID is {iid}"])

    def _debug_send_invoice(self, sessionid):
        log.info("Sending invoice only for %d", sessionid)
        iid, negative_totals = self._create_invoice_for_session(
            sessionid, approve=True)
        log.info("...new invoice ID is %s", iid)
        ui.infopopup([f"Invoice ID is {iid}"])

    def _debug_send_payments(self, sessionid):
        session = td.s.get(Session, sessionid)
        if session.accinfo:
            ui.toast(f"Sending payments for session {sessionid}")
            self._add_payments_for_session(sessionid, session.accinfo)
        else:
            ui.toast("Session has no invoice - doing nothing")

    def _debug_send_bill(self, deliveryid):
        log.info("Sending bill for delivery %d", deliveryid)
        iid = self._create_bill_for_delivery(deliveryid)
        log.info("...new invoice ID is %s", iid)
        ui.infopopup([f"Invoice ID is {iid}"])

    def _sales_account_for_department(self, department):
        codes = department.sales_account.split("/")
        return codes[0]

    def _sales_tracking_for_department(self, department):
        codes = department.sales_account.split("/", maxsplit=1)
        if len(codes) > 1:
            return codes[1]

    def _purchases_account_for_department(self, department):
        codes = department.purchases_account.split("/")
        return codes[0]

    def _purchases_tracking_for_department(self, department):
        codes = department.purchases_account.split("/", maxsplit=1)
        if len(codes) > 1:
            return codes[1]

    def _create_invoice_for_session(self, sessionid, approve=False):
        """Create an invoice for a session

        Returns the invoice's GUID, and whether any negative payment
        method totals were added to the invoice.  Does not check
        whether the invoice has already been created, or record the
        GUID against the session.
        """
        session = td.s.get(Session, sessionid)
        if not session:
            raise XeroError(f"Session {sessionid} does not exist")
        if not session.endtime:
            raise XeroError(f"Session {sessionid} is still open")
        if not session.actual_totals:
            raise XeroError(f"Session {sessionid} has no totals recorded")

        negative_totals = False

        invoices = Element("Invoices")
        inv = SubElement(invoices, "Invoice")
        inv.append(_textelem("Type", "ACCREC"))
        inv.append(self._get_sales_contact(session))
        inv.append(_textelem("LineAmountTypes", "Inclusive"))
        inv.append(_textelem("Date", session.date.isoformat()))
        inv.append(_textelem(
            "DueDate",
            (session.date
             + datetime.timedelta(days=self.due_days())).isoformat()))
        if self.tillweb_base_url():
            inv.append(_textelem(
                "Url", self.tillweb_base_url() + f"session/{session.id}/"))
        inv.append(_textelem(
            "Reference", self.reference_template().format(session=session)))
        if self.branding_theme_id():
            inv.append(_textelem(
                "BrandingThemeID", self.branding_theme_id()))
        litems = SubElement(inv, "LineItems")
        for dept, amount in session.dept_totals:
            li = SubElement(litems, "LineItem")
            li.append(_textelem("Description", dept.description))
            li.append(_textelem("AccountCode",
                                self._sales_account_for_department(dept)))
            li.append(_textelem("LineAmount", str(amount)))
            tracking = self._get_sales_tracking(dept)
            if tracking:
                li.append(tracking)
        # If there is a discrepancy between the till totals and the
        # actual totals, this must be recorded in a separate account
        if session.error != zero:
            if not self.discrepancy_account():
                raise XeroError(
                    f"Session {session.id} has a discrepancy between till "
                    "total and actual total, but no account is configured "
                    "to record this.")
            li = SubElement(litems, "LineItem")
            li.append(_textelem("Description", "Till discrepancy"))
            li.append(_textelem("AccountCode", self.discrepancy_account()))
            li.append(_textelem("LineAmount", str(session.error)))
            li.append(_textelem("TaxType", "NONE"))
            tracking = self._get_sales_tracking(None)
            if tracking:
                li.append(tracking)
        # Negative payment method totals are added as positive line items
        # against the suspense account
        for total in session.actual_totals:
            if total.payment_amount < zero:
                if not self.suspense_account():
                    raise XeroError(
                        f"Session {session.id} has a negative till total, "
                        "but no suspense account is configured to "
                        "receive it.")
                li = SubElement(litems, "LineItem")
                li.append(_textelem(
                    "Description",
                    f"Negative {total.paytype.description} total"))
                li.append(_textelem("AccountCode", self.suspense_account()))
                li.append(_textelem("LineAmount", str(
                    zero - total.payment_amount)))
                li.append(_textelem("TaxType", "NONE"))
                # No tracking category
                negative_totals = True
        # Fees are added as negative line items against the
        # appropriate fees account for the payment method
        for total in session.actual_totals:
            if total.fees != zero:
                if not total.paytype.fees_account:
                    raise XeroError(
                        f"Session {session.id} has fees recorded for "
                        f"{total.paytype} payments, but there is no account "
                        f"configured for these fees to be paid to.")
                li = SubElement(litems, "LineItem")
                li.append(_textelem(
                    "Description",
                    f"{total.paytype} fees"))
                li.append(_textelem("AccountCode", total.paytype.fees_account))
                li.append(_textelem("LineAmount", str(zero - total.fees)))
                tracking = self._get_fees_tracking()
                if tracking:
                    li.append(tracking)

        if approve and not negative_totals:
            inv.append(_textelem("Status", "AUTHORISED"))
        xml = tostring(invoices)
        r = self.xero_session().put(
            XERO_ENDPOINT_URL + "Invoices/", data={'xml': xml})
        if r.status_code == 400:
            root = fromstring(r.text)
            messages = [e.text for e in root.findall(".//Message")]
            raise XeroError("Xero rejected invoice: {}".format(
                ", ".join(messages)))
        if r.status_code != 200:
            raise XeroError(f"Received {r.status_code} response")
        root = fromstring(r.text)
        if root.tag != "Response":
            raise XeroError(
                f"Response root tag '{root.tag}' was not 'Response'")
        i = root.find("./Invoices/Invoice")
        if not i:
            raise XeroError("Response did not contain invoice details")
        invid = _fieldtext(i, "InvoiceID")
        if not invid:
            raise XeroError("No invoice ID was returned")
        # warnings = [w.text for w in i.findall("./Warnings/Warning/Message")]
        return invid, negative_totals

    def _add_payments_for_session(self, sessionid, invoice):
        """Add payments for a session to an existing invoice

        The invoice is specified by its Xero InvoiceID.  It must be
        Approved, otherwise adding payments will fail.  This call does
        not check the invoice state, or whether payments have already
        been added.
        """
        session = td.s.get(Session, sessionid)
        if not session:
            raise XeroError(f"Session {sessionid} does not exist")
        if not session.endtime:
            raise XeroError(f"Session {sessionid} is still open")
        if not session.actual_totals:
            raise XeroError(f"Session {sessionid} has no totals recorded")

        payments = Element("Payments")
        for total in session.actual_totals:
            if total.payment_amount == zero:
                continue
            if not total.paytype.payments_account:
                raise XeroError(
                    f"{total.paytype} has no payments account configured")
            dp = payment.date_policy.get(total.paytype.payment_date_policy)
            if not dp:
                raise XeroError(
                    f"{total.paytype} payment date policy is not defined")
            account = total.paytype.payments_account
            date = dp(session.date)
            ref = f"{total.paytype} takings"
            p = SubElement(payments, "Payment")
            SubElement(p, "Invoice").append(_textelem("InvoiceID", invoice))
            SubElement(p, "Account").append(_textelem("Code", account))
            p.append(_textelem("Date", date.isoformat()))
            p.append(_textelem("Amount", str(total.payment_amount)))
            p.append(_textelem("Reference", ref))

        xml = tostring(payments)
        r = self.xero_session().put(
            XERO_ENDPOINT_URL + "Payments/", data={'xml': xml})
        if r.status_code == 400:
            root = fromstring(r.text)
            messages = [e.text for e in root.findall(".//Message")]
            raise XeroError("Xero rejected payments: {}".format(
                ", ".join(messages)))
        if r.status_code != 200:
            raise XeroError(f"Received {r.status_code} response")
        root = fromstring(r.text)
        if root.tag != "Response":
            raise XeroError(
                f"Response root tag '{root.tag}' was not 'Response'")

    def _create_bill_for_delivery(self, deliveryid):
        d = td.s.get(Delivery, deliveryid)
        if not d:
            raise XeroError(f"Delivery {deliveryid} does not exist")
        if not d.supplier.accinfo:
            raise XeroError(f"Supplier {d.supplier.name} is not linked to "
                            "a Xero contact")

        invoices = Element("Invoices")
        inv = SubElement(invoices, "Invoice")
        inv.append(_textelem("Type", "ACCPAY"))
        contact = SubElement(inv, "Contact")
        contact.append(_textelem("ContactID", d.supplier.accinfo))
        inv.append(_textelem("LineAmountTypes", "Exclusive"))
        inv.append(_textelem("Date", d.date.isoformat()))
        inv.append(_textelem("InvoiceNumber", d.docnumber))
        if self.tillweb_base_url():
            inv.append(_textelem(
                "Url", self.tillweb_base_url() + f"delivery/{d.id}/"))
        litems = SubElement(inv, "LineItems")
        previtem = None
        prevqty = None
        for item in d.items:
            # prevqty is never true even if not-None.  Compare against
            # None explicitly.  Silly etree API!
            if previtem and prevqty != None \
               and item.stocktype.id == previtem.stocktype.id \
               and item.description == previtem.description \
               and item.size == previtem.size \
               and item.costprice == previtem.costprice:
                # We can bump up the quantity on the previous invoice line
                # rather than add a new one
                prevqty.text = str(int(prevqty.text) + 1)
                continue
            li = SubElement(litems, "LineItem")
            li.append(_textelem(
                "Description",
                f"{item.stocktype} {item.description}"))
            li.append(_textelem(
                "AccountCode",
                self._purchases_account_for_department(
                    item.stocktype.department)))
            if item.costprice is not None:
                li.append(_textelem("UnitAmount", str(item.costprice)))
            prevqty = _textelem("Quantity", "1")
            li.append(prevqty)
            tracking = self._get_purchases_tracking(item.stocktype.department)
            if tracking:
                li.append(tracking)
            previtem = item

        xml = tostring(invoices)
        r = self.xero_session().put(
            XERO_ENDPOINT_URL + "Invoices/", data={'xml': xml})
        if r.status_code == 400:
            root = fromstring(r.text)
            messages = [e.text for e in root.findall(".//Message")]
            raise XeroError("Xero rejected invoice: {}".format(
                ", ".join(messages)))
        if r.status_code != 200:
            raise XeroError(f"Received {r.status_code} response")
        root = fromstring(r.text)
        if root.tag != "Response":
            raise XeroError(
                f"Response root tag '{root.tag}' was not 'Response'")
        i = root.find("./Invoices/Invoice")
        if not i:
            raise XeroError("Response did not contain invoice details")
        invid = _fieldtext(i, "InvoiceID")
        if not invid:
            raise XeroError("No invoice ID was returned")
        # warnings = [w.text for w in i.findall("./Warnings/Warning/Message")]
        return invid

    def _send_delivery(self, deliveryid):
        d = td.s.get(Delivery, deliveryid)
        if not d.supplier.accinfo:
            ui.infopopup(
                [f"Couldn't send delivery {deliveryid} to Xero; supplier "
                 f"{d.supplier.name} is not linked to a Xero contact."],
                title="Error")
            return
        with ui.exception_guard("sending bill for delivery to Xero"):
            iid = self._create_bill_for_delivery(deliveryid)
            d.accinfo = iid
            td.s.flush()
            ui.toast("Delivery sent to Xero as draft bill")

    def _link_supplier_with_contact(self, supplierid):
        s = td.s.get(Supplier, supplierid)
        # Fetch possible contacts
        w = f"Name.ToLower().Contains(\"{s.name.lower()}\")"
        r = self.xero_session().get(
            XERO_ENDPOINT_URL + "Contacts/", params={
                "where": w, "order": "Name"})
        if r.status_code != 200:
            ui.infopopup([f"Failed to retrieve contacts from Xero: "
                          f"error code {r.status_code}"],
                         title="Xero Error")
            return
        root = fromstring(r.text)
        if root.tag != "Response":
            ui.infopopup([f"Failed to retrieve contacts from Xero: "
                          f"root element of response was '{root.tag}' "
                          f"instead of 'Response'"],
                         title="Xero Error")
            return
        contacts = root.find("Contacts")
        if contacts:
            cl = contacts.findall("Contact")
        else:
            cl = []
        if len(cl) == 0:
            ui.infopopup(
                [f"There are no Xero contacts matching '{s.name}'.  You "
                 f"could try renaming the contact in Xero to match "
                 f"the till, or renaming the supplier in the till "
                 f"to match Xero."],
                title="No Matching Contacts")
            return
        ml = [(c.find("Name").text, self._finish_link_supplier_with_contact,
               (supplierid, c.find("Name").text, c.find("ContactID").text))
              for c in cl]
        ui.menu(
            ml, title="Choose matching contact",
            blurb=f"Choose the Xero contact to link to the supplier "
            f"'{s.name}'")

    def _finish_link_supplier_with_contact(self, supplierid, name, contactid):
        s = td.s.get(Supplier, supplierid)
        if not s:
            ui.infopopup([f"Supplier {supplierid} not found."],
                         title="Error")
            return
        if s.accinfo == contactid:
            ui.infopopup(
                [f"Supplier '{s.name}' was already linked to Xero "
                 f"contact '{name}'."],
                title="Supplier already linked")
            return
        s.accinfo = contactid
        ui.infopopup([f"Supplier '{s.name}' now linked to Xero "
                      f"contact '{name}'."],
                     title="Supplier linked", colour=ui.colour_info,
                     dismiss=keyboard.K_CASH)

    def _unlink_supplier(self, supplierid):
        s = td.s.get(Supplier, supplierid)
        s.accinfo = None
        ui.infopopup([f"{s.name} unlinked from Xero"],
                     title="Unlink supplier from Xero contact",
                     colour=ui.colour_info,
                     dismiss=keyboard.K_CASH)

    def check_connection(self):
        if not self.connection_ok():
            xero_not_connected()
            return True
        r = self.xero_session().get(XERO_ENDPOINT_URL + "Organisation/")
        if r.status_code != 200:
            ui.infopopup([f"Failed to retrieve organisation details from Xero: "
                          f"error code {r.status_code}"],
                         title="Xero Error")
            return
        root = fromstring(r.text)
        if root.tag != "Response":
            ui.infopopup(
                [f"Failed to retrieve organisation details from Xero: "
                 f"root element of response was '{root.tag}' instead of "
                 f"'Response'"],
                title="Xero Error")
            return
        org = None
        orgs = root.find("Organisations")
        if orgs is not None:
            org = orgs.find("Organisation")
        if org is None:
            ui.infopoup(["There were no organisation details in the response "
                         "from Xero."],
                        title="Xero Error")
            return

        ui.infopopup(["Successfully connected to Xero.", "",
                      f"Organisation name: {_fieldtext(org, 'Name')}",
                      f"Short code: {_fieldtext(org, 'ShortCode')}"],
                     title="Connected to Xero", colour=ui.colour_info,
                     dismiss=keyboard.K_CASH)


class XeroWebInfo:
    """Class to be used as sqlalchemy session info member "accounts"

    This class enables the web interface to construct links to Xero
    invoices and bills.
    """
    def __init__(self, shortcode=None):
        self.shortcode = shortcode

    def _wrap(self, url):
        if self.shortcode:
            url = f"/organisationlogin/default.aspx?shortcode={self.shortcode}"\
                  f"&redirecturl={url}"
        return "https://go.xero.com" + url

    def _url_for_id(self, id, doctype):
        url = f"/{doctype}/View.aspx?InvoiceID={id}"
        return self._wrap(url)

    def url_for_invoice(self, id):
        return self._url_for_id(id, "AccountsReceivable")

    def url_for_bill(self, id):
        return self._url_for_id(id, "AccountsPayable")

    def url_for_contact(self, id):
        return self._wrap("/Contacts/View/" + id)


def _textelem(name, text):
    e = Element(name)
    e.text = text
    return e


def _fieldtext(c, field):
    f = c.find(field)
    if f is None:
        return
    return f.text


def choose_supplier(cont, link_only):
    q = td.s.query(Supplier).order_by(Supplier.name)
    if link_only:
        q = q.filter(Supplier.accinfo != None)
    f = ui.tableformatter(' l L ')
    lines = [(f(x.name, f"Linked to {x.accinfo}" if x.accinfo else ""),
              cont, (x.id,)) for x in q.all()]
    ui.menu(lines, title="Supplier List",
            blurb="Choose a supplier and press Cash/Enter.")


def choose_delivery(cont, start_date, allow_sent):
    q = td.s.query(Delivery)\
            .join(Supplier)\
            .filter(Delivery.checked)\
            .order_by(Delivery.date.desc(), Delivery.id.desc())
    if start_date:
        q = q.filter(Delivery.date >= start_date)
    if not allow_sent:
        q = q.filter(Delivery.accinfo == None)
    f = ui.tableformatter(' r L l L ')
    lines = [(f(x.id, x.supplier.name if x.supplier.accinfo
                else f"{x.supplier.name} (not linked)",
                x.date, x.docnumber or ""),
              cont, (x.id,)) for x in q.all()]
    ui.menu(lines, title="Delivery List",
            blurb="Select a delivery and press Cash/Enter.")


class connect(cmdline.command):
    command = "xero-connect"
    help = "connect to a Xero organisation"

    @staticmethod
    def run(args):
        with td.orm_session():
            connect.interactive()

    @staticmethod
    def interactive():
        if len(XeroIntegration._integrations) != 1:
            print("The Xero integration is not configured. Add it to the "
                  "configuration file before trying again.")
            return 1
        i = XeroIntegration._integrations[0]
        if not i.client_id():
            print("The Xero integration client_id has not been set. Set it "
                  f"using the {i.client_id.key} configuration key.")
            return 1
        if not i.redirect_uri():
            print("The Xero integration redirect_uri has not been set. Set it "
                  f"using the {i.redirect_uri.key} configuration key.")
            return 1
        if not i.secrets:
            print("The Xero integration does not have a secret store "
                  "configured.")
            return 1
        session = i.xero_session(omit_tenant=True)
        auth_url, state = session.authorization_url(XERO_AUTHORIZE_URL)
        print(f"Visit this page in your browser:\n{auth_url}\n")
        auth_response = input("After authorising, paste the URL provided "
                              "here: ")
        print()

        try:
            token = session.fetch_token(XERO_CONNECT_URL,
                                        client_id=i.client_id(),
                                        authorization_response=auth_response)
        except AccessDeniedError:
            print("Access was denied.")
            print()
            print("Hint: if you are trying to connect to the Demo Company, ")
            print("and it isn't appearing in the list of organisations, ")
            print("view the Demo Company in Xero before trying again.")
            return 1

        # Fetch the list of tenants
        r = session.get(XERO_CONNECTIONS_URL)
        if r.status_code != 200:
            print("Failed to get the list of Xero tenants")
            r.raise_for_status()
            return 1
        connections = r.json()
        for tenant in connections:
            print(f"{tenant['tenantId']} {tenant['tenantName']}")
        print()
        if i.tenant_id():
            print(f"The currently configured tenant is {i.tenant_id}")
        print(f"Set the appropriate tenant ID using the {i.tenant_id.key} "
              "configuration key")
        i.secrets.store('token', json.dumps(token), create=True)
