from __future__ import unicode_literals, print_function, division

import requests
from oauthlib.oauth1 import SIGNATURE_RSA, SIGNATURE_TYPE_AUTH_HEADER, SIGNATURE_HMAC
from requests_oauthlib import OAuth1
from xml.etree.ElementTree import Element, SubElement, tostring, fromstring
from . import td
import datetime
import logging
log = logging.getLogger(__name__)

XERO_ENDPOINT_URL = "https://api.xero.com/api.xro/2.0/"

class Api(object):
    def __init__(self, consumer_key, private_key):
        self.oauth_token = consumer_key
        
        self.oauth = OAuth1(
            consumer_key,
            resource_owner_key=consumer_key,
            rsa_key=private_key,
            signature_method=SIGNATURE_RSA,
            signature_type=SIGNATURE_TYPE_AUTH_HEADER)

    def get(self, what):
        print("Getting {}".format(what))
        r = requests.get(XERO_ENDPOINT_URL + what, auth=self.oauth)
        print("Got {}".format(r))
        return r

def _textelem(name, text):
    e = Element(name)
    e.text = text
    return e

def send_session_totals(api, session, contact, reference=None,
                        differences_account=None):
    """Send session totals to Xero

    session is a models.Session instance.  Returns a string describing
    what happened.
    """
    if not session.endtime:
        return "Session isn't closed!  Could not send."

    invoices = Element("Invoices")
    inv = SubElement(invoices, "Invoice")
    inv.append(_textelem("Type", "ACCREC"))
    c = SubElement(inv, "Contact")
    c.append(_textelem("Name", contact))
    inv.append(_textelem("Date", session.date.isoformat()))
    inv.append(_textelem(
        "DueDate", (session.date + datetime.timedelta(days=4)).isoformat()))
    if reference:
        inv.append(_textelem("Reference", reference))
    inv.append(_textelem(
        "LineAmountTypes", "Inclusive"))
    litems = SubElement(inv, "LineItems")
    for dept, total in session.dept_totals:
        extras = fromstring("<e>{}</e>".format(dept.accinfo))
        li = SubElement(litems, "LineItem")
        li.append(_textelem("Description", dept.description + " sales"))
        li.append(_textelem("Quantity", "1.00"))
        li.append(_textelem("UnitAmount", unicode(total)))
        for sub in extras:
            li.append(sub)

    if differences_account:
        li = SubElement(litems, "LineItem")
        li.append(_textelem("AccountCode", differences_account))
        li.append(_textelem("Description", "Error"))
        li.append(_textelem("Quantity", "1.00"))
        li.append(_textelem("UnitAmount", unicode(session.error)))
    
    xml = tostring(invoices)
    log.debug("XML to send: {}".format(xml))
    r = requests.put(XERO_ENDPOINT_URL + "Invoices/",
                     data={'xml': xml},
                     auth=api.oauth)
    log.debug("Response: {}".format(r))
    log.debug("Response data: {}".format(r.text))
    return "Session {} sent to Xero: response code {}".format(
        session.id, r.status_code)
