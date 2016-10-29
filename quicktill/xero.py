import requests
from oauthlib.oauth1 import SIGNATURE_RSA, SIGNATURE_TYPE_AUTH_HEADER, SIGNATURE_HMAC
from requests_oauthlib import OAuth1
from xml.etree.ElementTree import Element, SubElement, tostring, fromstring
import datetime
import logging
from . import session
from . import payment
from . import ui
from . import td
from . import user
from .models import Session, SessionNoteType, SessionNote, zero
log = logging.getLogger(__name__)

XERO_ENDPOINT_URL = "https://api.xero.com/api.xro/2.0/"

class XeroError(Exception):
    pass

class XeroSessionHooks(session.SessionHooks):
    def __init__(self, xero):
        self.xero = xero

    def preRecordSessionTakings(self, sessionid):
        if not self.xero.oauth:
            ui.infopopup(
                ["This terminal does not have access to the accounting "
                 "system.  Please record the session takings on another "
                 "terminal."], title="Accounts not available")
            return True

    def postRecordSessionTakings(self, sessionid):
        session = td.s.query(Session).get(sessionid)
        if self.xero.start_date and self.xero.start_date > session.date:
            return
        try:
            with ui.exception_guard("creating the Xero invoice",
                                    suppress_exception=False):
                invid = self.xero._create_invoice_for_session(
                    sessionid, approve=True)
        except XeroError:
            return
        # Record the Xero invoice ID as a note against the session
        id_note_type = td.s.merge(
            SessionNoteType(id="xeroinv", description="Xero InvoiceID"))
        id_note = SessionNote(session=session, type=id_note_type,
                              text=invid, user=user.current_dbuser())
        td.s.add(id_note)
        # We want to commit the invoice ID to the database even if adding
        # payments fails, so we can try again later
        td.s.commit()
        try:
            with ui.exception_guard("adding payments to the Xero invoice",
                                    suppress_exception=False):
                self.xero._add_payments_for_session(sessionid, invid)
        except XeroError:
            return
        ui.toast("Session details uploaded to Xero.")

class XeroIntegration:
    """Xero accounting system integration

    To integrate with Xero, create an instance of this class in the
    till configuration file.  You should add an "Apps" menu entry that
    calls the instance's app_menu() method to enable users to access
    the integration utilities menu.
    """

    def __init__(self,
                 # oauth parameters - if absent, integration will prevent
                 # till users from performing any actions that would
                 # require Xero callouts
                 consumer_key=None, private_key=None,
                 # Invoices will be created to the following contact ID:
                 contact_id=None,
                 # Invoices will be created with a reference using the
                 # following template:
                 reference_template="Session {session.id}",
                 # Use this tracking category on all relevant entries
                 tracking_category_name=None,
                 tracking_category_value=None,
                 # Mark the invoice as Due in the following number of days:
                 due_days=7,
                 # Add tillweb link when an invoice is created
                 tillweb_base_url=None,
                 # Set the branding theme
                 branding_theme_id=None,
                 # Specify the Xero organisation's ShortCode
                 shortcode=None,
                 # Use this account for till discrepancies
                 discrepancy_account=None,
                 # Only start sending totals to Xero on or after this date
                 start_date=None):
        XeroSessionHooks(self)
        if consumer_key and private_key:
            self.oauth = OAuth1(
                consumer_key,
                resource_owner_key=consumer_key,
                rsa_key=private_key,
                signature_method=SIGNATURE_RSA,
                signature_type=SIGNATURE_TYPE_AUTH_HEADER)
        else:
            self.oauth = None
        if contact_id:
            self.contact = Element("Contact")
            self.contact.append(_textelem("ContactID", contact_id))
        else:
            self.contact = None
        if tracking_category_name and tracking_category_value:
            self.tracking = Element("Tracking")
            tc = SubElement(self.tracking, "TrackingCategory")
            tc.append(_textelem("Name", tracking_category_name))
            tc.append(_textelem("Option", tracking_category_value))
        else:
            self.tracking = None
        self.reference_template = reference_template
        self.due_days = datetime.timedelta(days=due_days)
        self.tillweb_base_url = tillweb_base_url
        self.branding_theme_id = branding_theme_id
        self.shortcode = shortcode
        self.discrepancy_account = discrepancy_account
        self.start_date = start_date

    @user.permission_required("xero-debug", "Low-level access to the "
                              "Xero integration")
    def app_menu(self):
        ui.automenu([
            ("Send invoice and payments for a session",
             self._debug_choose_session,
             (self._debug_send_invoice_and_payments,)),
            ("Send invoice only for a session",
             self._debug_choose_session,
             (self._debug_send_invoice,)),
            ("Send payments for an existing invoice",
             self._debug_choose_session,
             (self._debug_send_payments,)),
            ], title="Xero debug")

    def _debug_choose_session(self, cont):
        ui.menu(session.sessionlist(
            cont, paidonly=True, closedonly=True, maxlen=100),
                title="Choose session")
        
    def _debug_send_invoice_and_payments(self, sessionid):
        log.info("Sending invoice and payments for %d", sessionid)
        iid = self._create_invoice_for_session(sessionid, approve=True)
        self._add_payments_for_session(args.sessionid, iid)
        log.info("...new invoice ID is %s", iid)
        ui.infopopup(["Invoice ID is {}".format(iid)])

    def _debug_send_invoice(self, sessionid):
        log.info("Sending invoice only for %d", sessionid)
        iid = self._create_invoice_for_session(sessionid, approve=True)
        log.info("...new invoice ID is %s", iid)
        ui.infopopup(["Invoice ID is {}".format(iid)])

    def _debug_send_payments(self, sessionid):
        ids = td.s.query(SessionNote)\
                  .filter(SessionNote.sessionid == sessionid)\
                  .filter(SessionNote.ntype == 'xeroinv')\
                  .order_by(SessionNote.time.desc())\
                  .all()
        log.info("Sending payments for %d: %d available invoices",
                 sessionid, len(ids))
        ui.infopopup(["Available invoice IDs:"] + [x.text for x in ids])
        if ids:
            self._add_payments_for_session(sessionid, ids[0].text)
        else:
            ui.toast("No invoice - doing nothing")
        
    def _create_invoice_for_session(self, sessionid, approve=False):
        """Create an invoice for a session

        Returns the invoice's GUID.  Does not check whether the
        invoice has already been created, or record the GUID against
        the session.
        """
        session = td.s.query(Session).get(sessionid)
        if not session:
            raise XeroError("Session {} does not exist".format(sessionid))
        if not session.endtime:
            raise XeroError("Session {} is still open".format(sessionid))
        if not session.actual_totals:
            raise XeroError("Session {} has no totals recorded".format(
                sessionid))
        
        invoices = Element("Invoices")
        inv = SubElement(invoices, "Invoice")
        inv.append(_textelem("Type", "ACCREC"))
        if self.contact:
            inv.append(self.contact)
        inv.append(_textelem("LineAmountTypes", "Inclusive"))
        inv.append(_textelem(
            "Date", session.date.isoformat()))
        inv.append(_textelem(
            "DueDate", (session.date + self.due_days).isoformat()))
        if self.tillweb_base_url:
            inv.append(_textelem(
                "Url", self.tillweb_base_url + session.tillweb_url()))
        inv.append(_textelem(
            "Reference", self.reference_template.format(session=session)))
        if self.branding_theme_id:
            inv.append(_textelem(
                "BrandingThemeID", self.branding_theme_id))
        if approve:
            inv.append(_textelem("Status", "AUTHORISED"))
        litems = SubElement(inv, "LineItems")
        for dept, amount in session.dept_totals:
            li = SubElement(litems, "LineItem")
            li.append(_textelem("Description", dept.description))
            li.append(_textelem("AccountCode", dept.accinfo))
            li.append(_textelem("LineAmount", str(amount)))
            if self.tracking:
                li.append(self.tracking)
        # If there is a discrepancy between the till totals and the
        # actual totals, this must be recorded in a separate account
        if session.error != zero:
            if not self.discrepancy_account:
                raise XeroError(
                    "Session {} has a discrepancy between till total and "
                    "actual total, but no account is configured to record "
                    "this.".format(session.id))
            li = SubElement(litems, "LineItem")
            li.append(_textelem("Description", "Till discrepancy"))
            li.append(_textelem("AccountCode", self.discrepancy_account))
            li.append(_textelem("LineAmount", str(session.error)))
            li.append(_textelem("TaxType", "NONE"))
            if self.tracking:
                li.append(self.tracking)
        xml = tostring(invoices)
        r = requests.put(XERO_ENDPOINT_URL + "Invoices/",
                         data={'xml': xml},
                         auth=self.oauth)
        if r.status_code == 400:
            root = fromstring(r.text)
            messages = [e.text for e in root.findall(".//Message")]
            raise XeroError("Xero rejected invoice: {}".format(
                ", ".join(messages)))
        if r.status_code != 200:
            raise XeroError("Received {} response".format(r.status_code))
        root = fromstring(r.text)
        if root.tag != "Response":
            raise XeroError("Response root tag '{}' was not 'Response'".format(
                root.tag))
        i = root.find("./Invoices/Invoice")
        if not i:
            raise XeroError("Response did not contain invoice details")
        invid = _fieldtext(i, "InvoiceID")
        if not invid:
            raise XeroError("No invoice ID was returned")
        #warnings = [w.text for w in i.findall("./Warnings/Warning/Message")]
        return invid

    def _add_payments_for_session(self, sessionid, invoice):
        """Add payments for a session to an existing invoice

        The invoice is specified by its Xero InvoiceID.  It must be
        Approved, otherwise adding payments will fail.  This call does
        not check the invoice state, or whether payments have already
        been added.
        """
        session = td.s.query(Session).get(sessionid)
        if not session:
            raise XeroError("Session {} does not exist".format(sessionid))
        if not session.endtime:
            raise XeroError("Session {} is still open".format(sessionid))
        if not session.actual_totals:
            raise XeroError("Session {} has no totals recorded".format(
                sessionid))
        
        payments = Element("Payments")
        for total in session.actual_totals:
            pm = payment.methods[total.paytype_id]
            account, date, ref = pm.accounting_info(total)
            if total.amount == zero:
                continue
            p = SubElement(payments, "Payment")
            SubElement(p, "Invoice").append(_textelem("InvoiceID", invoice))
            SubElement(p, "Account").append(_textelem("Code", account))
            p.append(_textelem("Date", date.isoformat()))
            p.append(_textelem("Amount", str(total.amount)))
            p.append(_textelem("Reference", ref))

        xml = tostring(payments)
        r = requests.put(XERO_ENDPOINT_URL + "Payments/",
                         data={'xml': xml},
                         auth=self.oauth)
        if r.status_code == 400:
            root = fromstring(r.text)
            messages = [e.text for e in root.findall(".//Message")]
            raise XeroError("Xero rejected payments: {}".format(
                ", ".join(messages)))
        if r.status_code != 200:
            raise XeroError("Received {} response".format(r.status_code))
        root = fromstring(r.text)
        if root.tag != "Response":
            raise XeroError("Response root tag '{}' was not 'Response'".format(
                root.tag))

    def url_for_invoice(self, id):
        url = "/AccountsReceivable/View.aspx?InvoiceID={}".format(id)
        if self.shortcode:
            url = "/organisationlogin/default.aspx?shortcode={}"\
                  "&redirecturl={}".format(self.shortcode, url)
        return "https://go.xero.com" + url

def _textelem(name, text):
    e = Element(name)
    e.text = text
    return e

def _fieldtext(c, field):
    f = c.find(field)
    if f is None:
        return
    return f.text
