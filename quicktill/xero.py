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
from . import delivery
from . import keyboard
from .models import Session, zero
from .models import Delivery, Supplier
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
        # Commit at this point to ensure the totals are recorded in
        # the till database.
        td.s.commit()
        ui.toast("Sending session details to accounting system...")
        try:
            with ui.exception_guard("creating the Xero invoice",
                                    suppress_exception=False):
                invid = self.xero._create_invoice_for_session(
                    sessionid, approve=True)
        except XeroError:
            return
        # Record the Xero invoice ID
        session.accinfo = invid
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

class XeroDeliveryHooks(delivery.DeliveryHooks):
    def __init__(self, xero):
        self.xero = xero

    def preConfirm(self, deliveryid):
        d = td.s.query(Delivery).get(deliveryid)
        if self.xero.start_date and self.xero.start_date > d.date:
            return
        if not d.supplier.accinfo:
            return
        if not self.xero.oauth:
            ui.infopopup(
                ["This terminal does not have access to Xero, the "
                 "accounting system, so the delivery can't be confirmed "
                 "from here.", "",
                 "Please save the delivery here, and confirm it using "
                 "a terminal that does have access to Xero."],
                title="No access to accounts")
            return True

    def confirmed(self, deliveryid):
        d = td.s.query(Delivery).get(deliveryid)
        if self.xero.start_date and self.xero.start_date > d.date:
            ui.toast("Not sending this delivery to Xero - delivery is dated "
                     "before the Xero start date")
            return
        if not d.supplier.accinfo:
            ui.toast("Not sending this delivery to Xero - the supplier "
                     "is not linked to a Xero contact")
            return
        if not self.xero.oauth:
            ui.toast("Not sending this delivery to Xero - this terminal "
                     "does not have access to Xero.")
            return
        self.xero._send_delivery(deliveryid)

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
                 # (which may be a callable that takes a session and returns
                 # the contact ID)
                 sales_contact_id=None,
                 # Invoices will be created with a reference using the
                 # following template:
                 reference_template="Session {session.id}",
                 # Use this tracking category on all relevant entries
                 tracking_category_name=None,
                 tracking_category_value=None,
                 # Use this tracking category on departments
                 department_tracking_category_name=None,
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
        XeroDeliveryHooks(self)
        if consumer_key and private_key:
            self.oauth = OAuth1(
                consumer_key,
                resource_owner_key=consumer_key,
                rsa_key=private_key,
                signature_method=SIGNATURE_RSA,
                signature_type=SIGNATURE_TYPE_AUTH_HEADER)
        else:
            self.oauth = None
        self.sales_contact = sales_contact_id
        self.tracking_category_name = tracking_category_name
        self.tracking_category_value = tracking_category_value
        self.department_tracking_category_name = department_tracking_category_name
        self.reference_template = reference_template
        self.due_days = datetime.timedelta(days=due_days)
        self.tillweb_base_url = tillweb_base_url
        self.branding_theme_id = branding_theme_id
        self.shortcode = shortcode
        self.discrepancy_account = discrepancy_account
        self.start_date = start_date

    def _get_sales_contact(self, session):
        if callable(self.sales_contact):
            sales_contact_id = self.sales_contact(session)
        else:
            sales_contact_id = self.sales_contact
        contact = None
        if sales_contact_id:
            contact = Element("Contact")
            contact.append(_textelem("ContactID", sales_contact_id))
        return contact

    def _get_tracking(self, department):
        tracking = []
        if self.tracking_category_name and self.tracking_category_value:
            tracking.append((self.tracking_category_name, self.tracking_category_value))
        if department and self.department_tracking_category_name:
            v = self._tracking_for_department(department)
            if v:
                tracking.append((self.department_tracking_category_name, v))
        if tracking:
            t = Element("Tracking")
            for name, option in tracking:
                tc = SubElement(t, "TrackingCategory")
                tc.append(_textelem("Name", name))
                tc.append(_textelem("Option", option))
            return t

    @user.permission_required("xero-admin", "Xero integration admin")
    def app_menu(self):
        if not self.oauth:
            ui.infopopup(["This terminal does not have access to Xero.  "
                          "Please use a different terminal."],
                         title="Accounts not available")
            return
        ui.automenu([
            ("Link a supplier with a Xero contact",
             choose_supplier,
             (self._link_supplier_with_contact, False)),
            ("Unlink a supplier from its Xero contact",
             choose_supplier,
             (self._unlink_supplier, True)),
            ("Send a delivery to Xero as a bill",
             choose_delivery,
             (self._send_delivery, self.start_date, False)),
            ("Re-send a delivery to Xero as a bill",
             choose_delivery,
             (self._send_delivery, self.start_date, True)),
            ("Test the connection to Xero",
             self.check_connection, ()),
            ("Xero debug menu",
             self._debug_menu, ())],
                    title="Xero options")

    @user.permission_required("xero-debug", "Low-level access to the "
                              "Xero integration")
    def _debug_menu(self):
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
            ("Send bill for a delivery",
             self._debug_choose_delivery,
             (self._debug_send_bill,))
            ], title="Xero debug")

    def _debug_choose_session(self, cont):
        ui.menu(session.sessionlist(
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
        iid = self._create_invoice_for_session(sessionid, approve=True)
        session = td.s.query(Session).get(sessionid)
        session.accinfo = iid
        td.s.commit()
        self._add_payments_for_session(sessionid, iid)
        log.info("...new invoice ID is %s", iid)
        ui.infopopup(["Invoice ID is {}".format(iid)])

    def _debug_send_invoice(self, sessionid):
        log.info("Sending invoice only for %d", sessionid)
        iid = self._create_invoice_for_session(sessionid, approve=True)
        log.info("...new invoice ID is %s", iid)
        ui.infopopup(["Invoice ID is {}".format(iid)])

    def _debug_send_payments(self, sessionid):
        session = td.s.query(Session).get(sessionid)
        if session.accinfo:
            ui.toast("Sending payments for session {}".format(sessionid))
            self._add_payments_for_session(sessionid, session.accinfo)
        else:
            ui.toast("Session has no invoice - doing nothing")

    def _debug_send_bill(self, deliveryid):
        log.info("Sending bill for delivery %d", deliveryid)
        iid = self._create_bill_for_delivery(deliveryid)
        log.info("...new invoice ID is %s", iid)
        ui.infopopup(["Invoice ID is {}".format(iid)])

    def _sales_account_for_department(self, department):
        codes = department.accinfo.split("/")
        return codes[0]

    def _purchases_account_for_department(self, department):
        codes = department.accinfo.split("/")
        if len(codes) > 1:
            return codes[1]
        return codes[0]

    def _tracking_for_department(self, department):
        codes = department.accinfo.split("/")
        if len(codes) > 2:
            return codes[2]
    
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
        inv.append(self._get_sales_contact(session))
        inv.append(_textelem("LineAmountTypes", "Inclusive"))
        inv.append(_textelem("Date", session.date.isoformat()))
        inv.append(_textelem(
            "DueDate", (session.date + self.due_days).isoformat()))
        if self.tillweb_base_url:
            inv.append(_textelem(
                "Url", self.tillweb_base_url + "session/{}/".format(session.id)))
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
            li.append(_textelem("AccountCode",
                                self._sales_account_for_department(dept)))
            li.append(_textelem("LineAmount", str(amount)))
            tracking = self._get_tracking(dept)
            if tracking:
                li.append(tracking)
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
            tracking = self._get_tracking(None)
            if tracking:
                li.append(tracking)
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

    def _create_bill_for_delivery(self, deliveryid):
        d = td.s.query(Delivery).get(deliveryid)
        if not d:
            raise XeroError("Delivery {} does not exist".format(deliveryid))
        if not d.supplier.accinfo:
            raise XeroError("Supplier {} ({}) has no Xero contact info".format(
                d.supplier.id, d.supplier.name))
        
        invoices = Element("Invoices")
        inv = SubElement(invoices, "Invoice")
        inv.append(_textelem("Type", "ACCPAY"))
        contact = SubElement(inv, "Contact")
        contact.append(_textelem("ContactID", d.supplier.accinfo))
        inv.append(_textelem("LineAmountTypes", "Exclusive"))
        inv.append(_textelem("Date", d.date.isoformat()))
        inv.append(_textelem("InvoiceNumber", d.docnumber))
        if self.tillweb_base_url:
            inv.append(_textelem(
                "Url", self.tillweb_base_url + "delivery/{}/".format(d.id)))
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
                item.stocktype.format() + " " + item.description))
            li.append(_textelem(
                "AccountCode",
                self._purchases_account_for_department(
                    item.stocktype.department)))
            if item.costprice is not None:
                li.append(_textelem("UnitAmount", str(item.costprice)))
            prevqty = _textelem("Quantity", "1")
            li.append(prevqty)
            tracking = self._get_tracking(item.stocktype.department)
            if tracking:
                li.append(tracking)
            previtem = item

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

    def _send_delivery(self, deliveryid):
        d = td.s.query(Delivery).get(deliveryid)
        if not d.supplier.accinfo:
            ui.infopopup(["Couldn't send delivery {} to Xero; supplier {} "
                          "is not linked to a Xero contact.".format(
                              deliveryid, d.supplier.name)],
                         title="Error")
            return
        with ui.exception_guard("sending bill for delivery to Xero"):
            iid = self._create_bill_for_delivery(deliveryid)
            d.accinfo = iid
            td.s.flush()
            ui.toast("Delivery sent to Xero as draft bill")

    def _link_supplier_with_contact(self, supplierid):
        s = td.s.query(Supplier).get(supplierid)
        # Fetch possible contacts
        w = "Name.ToLower().Contains(\"{}\")".format(s.name.lower())
        r = requests.get(XERO_ENDPOINT_URL + "Contacts/", params={
            "where": w, "order": "Name"}, auth=self.oauth)
        if r.status_code != 200:
            ui.infopopup(["Failed to retrieve contacts from Xero: "
                          "error code {}".format(r.status_code)],
                         title="Xero Error")
            return
        root = fromstring(r.text)
        if root.tag != "Response":
            ui.infopopup(["Failed to retrieve contacts from Xero: "
                          "root element of response was '{}' instead of "
                          "'Response'".format(root.tag)],
                         title="Xero Error")
            return
        contacts = root.find("Contacts")
        if contacts:
            cl = contacts.findall("Contact")
        else:
            cl = []
        if len(cl) == 0:
            ui.infopopup(["There are no Xero contacts matching '{}'.  You "
                          "could try renaming the contact in Xero to match "
                          "the till, or renaming the supplier in the till "
                          "to match Xero.".format(s.name)],
                         title="No Matching Contacts")
            return
        ml = [ (c.find("Name").text, self._finish_link_supplier_with_contact,
                (supplierid, c.find("Name").text, c.find("ContactID").text))
               for c in cl ]
        ui.menu(
            ml, title="Choose matching contact",
            blurb="Choose the Xero contact to link to the supplier '{}'".format(
                s.name))

    def _finish_link_supplier_with_contact(self, supplierid, name, contactid):
        s = td.s.query(Supplier).get(supplierid)
        if not s:
            ui.infopopup(["Supplier {} not found.".format(supplierid)],
                         title="Error")
            return
        if s.accinfo == contactid:
            ui.infopopup(
                ["Supplier '{}' was already linked to Xero contact '{}'.".format(
                    s.name, name)],
                title="Supplier already linked")
            return
        s.accinfo = contactid
        ui.infopopup(["Supplier '{}' now linked to Xero contact '{}'.".format(
            s.name, name)],
                     title="Supplier linked", colour=ui.colour_info,
                     dismiss=keyboard.K_CASH)

    def _unlink_supplier(self, supplierid):
        s = td.s.query(Supplier).get(supplierid)
        s.accinfo = None
        ui.infopopup(["{} unlinked from Xero".format(s.name)],
                     title="Unlink supplier from Xero contact",
                     colour=ui.colour_info,
                     dismiss=keyboard.K_CASH)

    def check_connection(self):
        if not self.oauth:
            ui.infopopup(
                ["This terminal does not have access to the accounting "
                 "system."], title="Xero not available")
            return True
        r = requests.get(XERO_ENDPOINT_URL + "Organisation/", auth=self.oauth)
        if r.status_code != 200:
            ui.infopopup(["Failed to retrieve organisation details from Xero: "
                          "error code {}".format(r.status_code)],
                         title="Xero Error")
            return
        root = fromstring(r.text)
        if root.tag != "Response":
            ui.infopopup(["Failed to retrieve organisation details from Xero: "
                          "root element of response was '{}' instead of "
                          "'Response'".format(root.tag)],
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
                      "Organisation name: {}".format(_fieldtext(org, "Name")),
                      "Short code: {}".format(_fieldtext(org, "ShortCode"))],
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
            url = "/organisationlogin/default.aspx?shortcode={}"\
                  "&redirecturl={}".format(self.shortcode, url)
        return "https://go.xero.com" + url

    def _url_for_id(self, id, doctype):
        url = "/{}/View.aspx?InvoiceID={}".format(doctype, id)
        return self._wrap(url)

    def url_for_invoice(self, id):
        return self._url_for_id(id, "AccountsReceivable")

    def url_for_bill(self, id):
        return self._url_for_id(id, "AccountsPayable")

    def url_for_contact(self, id):
        return self._wrap("/Contacts/View/" + id)

    def decode_dept_accinfo(self, accinfo):
        """Return a list of strings to display given department accinfo
        """
        x = accinfo.split('/')
        return zip(
            ("Sales account", "Purchases account", "Tracking category"), x)

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
    lines = [(f(x.name, "Linked to {}".format(x.accinfo) if x.accinfo else ""),
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
                else "{} (not linked)".format(x.supplier.name),
                x.date, x.docnumber or ""),
              cont, (x.id,)) for x in q.all()]
    ui.menu(lines, title="Delivery List",
            blurb="Select a delivery and press Cash/Enter.")
