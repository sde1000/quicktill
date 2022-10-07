from . import payment
from .secretstore import Secrets, SecretDoesNotExist, SecretNotAvailable
from .models import zero, PayType, Payment, Session, Transaction
from . import ui
from . import tillconfig
from . import td
from .keyboard import K_CANCEL, K_CASH, K_CLEAR
import json
import requests
import uuid
from contextlib import closing
from decimal import Decimal
from sqlalchemy.orm import joinedload
import datetime
import logging

log = logging.getLogger(__name__)

api_version = "2022-08-23"

minimum_charge = "1.00"

# This is a list of device_id that can be used for testing terminal
# checkouts in sandbox mode.
sandbox_devices = {
    '9fa747a2-25ff-48ee-b078-04381f7c828f': "Succeed up to $25",
    '841100b9-ee60-4537-9bcf-e30b2ba5e215': "Buyer will cancel",
    '0a956d49-619a-4530-8e5e-8eac603ffc5e': "Will time out instantly",
    'da40d603-c2ea-4a65-8cfd-f42e36dab0c7': "Offline terminal",
    'e371fb66-29a2-45a6-a928-f8de0e864242': "Ping times out instantly",
    '7647344e-aea2-4cff-ac53-513644de434d': "Ping offline terminal",
}

# Payment metadata keys

checkout_device_name_key = "square:checkout_device_name"
checkout_details_key = "square:checkout_details"
checkout_id_key = "square:checkout_id"
checkout_key = "square:checkout_object"
payment_id_key = "square:payment_id"
payment_key = "square:payment_object"
refund_details_key = "square:refund_details"
refund_id_key = "square:refund_id"
refund_key = "square:refund_object"
refund_card_key = "square:refund_card"


# The following keys should be purged after a couple of days: they are
# not valid beyond the day the transaction took place
purgeable_metadata_keys = [
    checkout_device_name_key,
    checkout_details_key,
    checkout_id_key,
    checkout_key,
    refund_details_key,
]


def idempotency_key():
    return str(uuid.uuid4())


class Location:
    """Square API Location object

    Locations represent the sources of orders and fulfillments for
    businesses (such as physical brick and mortar stores, online
    marketplaces, warehouses, or anywhere a seller does business).
    """
    def __init__(self, d):
        self.source_data = d
        self.id = d.get("id")
        self.name = d.get("name")
        self.status = d.get("status")
        self.currency = d.get("currency")

    def __str__(self):
        return f"{self.id}: {self.name} ({self.status}, {self.currency})"


class DeviceCode:
    """Square API DeviceCode object

    Represents a (possibly in-progress or failed) pairing between a
    location and a Square Terminal. The "code" is used to log the
    Terminal in. The "device_id" is provided in calls to create
    TerminalCheckout and TerminalAction objects.
    """
    def __init__(self, d):
        self.source_data = d
        self.id = d.get("id")
        self.name = d.get("name")
        self.code = d.get("code")
        self.product_type = d.get("product_type")
        self.location_id = d.get("location_id")
        self.status = d.get("status")
        self.device_id = d.get("device_id")

    def as_state(self):
        return {
            'id': self.id,
            'name': self.name,
            'code': self.code,
            'device_id': self.device_id,
        }


class TerminalCheckout:
    """Square API TerminalCheckout object

    Represents a request to carry out a transaction on a Square Terminal.
    """
    def __init__(self, d):
        self.source_data = d
        self.id = d.get("id")
        self.status = d.get("status")
        self.cancel_reason = d.get("cancel_reason")
        self.payment_ids = d.get("payment_ids")


class DeviceMetadata:
    """Square API DeviceMetadata object
    """
    def __init__(self, d):
        self.source_data = d
        self.app_version = d.get("app_version")
        self.battery_percentage = d.get("battery_percentage")
        self.charging_state = d.get("charging_state")
        self.ip_address = d.get("ip_address")
        self.network_connection_type = d.get("network_connection_type")
        self.os_version = d.get("os_version")
        self.payment_region = d.get("payment_region")
        self.serial_number = d.get("serial_number")
        self.wifi_network_name = d.get("wifi_network_name")
        self.wifi_network_strength = d.get("wifi_network_strength")


class TerminalAction:
    """Square API TerminalAction object

    Represents a request to carry out an action on a Square Terminal
    that does not result in a completed Payment
    """
    def __init__(self, d):
        self.source_data = d
        self.id = d.get("id")
        self.cancel_reason = d.get("cancel_reason")
        self.device_id = d.get("device_id")
        self.device_metadata = DeviceMetadata(d.get("device_metadata")) \
            if "device_metadata" in d else None
        self.status = d.get("status")
        self.type = d.get("type")


class Money:
    """Square API Money object
    """
    two_decimal_currencies = ("AUD", "CAD", "GBP", "USD", "EUR")
    zero_decimal_currencies = ("JPY",)

    def __init__(self, d):
        self.source_data = d
        self.amount = d.get("amount")
        self.currency = d.get("currency")

    def as_decimal(self):
        if self.currency in self.two_decimal_currencies:
            return Decimal(self.amount) / Decimal("100")
        elif self.currency in self.zero_decimal_currencies:
            return Decimal(self.amount)
        raise Exception(f"Unknown Square currency {self.currency}")

    @classmethod
    def from_decimal(cls, amount, currency):
        if currency in cls.two_decimal_currencies:
            amount = amount * 100
        elif currency in cls.zero_decimal_currencies:
            pass
        else:
            raise Exception(f"Unknown Square currency {currency}")
        return cls({"amount": int(amount), "currency": currency})


class Card:
    """Square API Card object
    """
    def __init__(self, d):
        self.source_data = d
        self.bin = d.get("bin")
        self.card_brand = d.get("card_brand")
        self.cardholder_name = d.get("cardholder_name")
        self.exp_month = d.get("exp_month")
        self.exp_year = d.get("exp_year")
        self.last_4 = d.get("last_4")

        self.cardnum = f"{self.bin}...{self.last_4}"
        self.expires = f"{self.exp_month}/{self.exp_year}"

    def __str__(self):
        return self.cardnum


class CardPaymentDetails:
    """Square API CardPaymentDetails object
    """
    def __init__(self, d):
        self.source_data = d
        self.application_cryptogram = d.get("application_cryptogram")
        self.application_identifier = d.get("application_identifier")
        self.application_name = d.get("application_name")
        self.auth_result_code = d.get("auth_result_code")
        self.entry_method = d.get("entry_method")
        self.verification_method = d.get("verification_method")
        self.status = d.get("status")
        self.card = Card(d.get("card", {}))


class ProcessingFee:
    """Square API ProcessingFee object
    """
    def __init__(self, d):
        self.source_data = d
        self.amount_money = Money(d.get('amount_money'))
        self.effective_at = d.get('effective_at')
        self.type = d.get('type')


class SquarePayment:
    """Square API Payment object

    Named SquarePayment to distinguish it from models.Payment

    Represents a completed payment.

    processing_fee is populated a short time (10–15 seconds) after the
    payment is created.
    """
    def __init__(self, d):
        self.source_data = d
        self.id = d.get("id")
        self.total_money = Money(d.get("total_money", {}))
        if "refunded_money" in d:
            self.refunded_money = Money(d["refunded_money"])
        else:
            self.refunded_money = None
        self.status = d.get("status")
        self.card_details = CardPaymentDetails(d.get("card_details", {}))
        self.processing_fee = [
            ProcessingFee(x) for x in d.get("processing_fee", [])]
        self.version_token = d.get("version_token")


class PaymentRefund:
    """Square API PaymentRefund object

    Represents a refund, possibly still in progress. When created,
    status is "PENDING". After some time (possibly hours) this will
    change to "COMPLETED", "REJECTED" or "FAILED".

    processing_fee is populated a short time (10–15 seconds) after the
    refund is created.
    """
    def __init__(self, d):
        self.source_data = d
        self.id = d.get("id")
        self.amount_money = Money(d.get("amount_money", {}))
        self.payment_id = d.get("payment_id")
        self.processing_fee = [
            ProcessingFee(x) for x in d.get("processing_fee", [])]
        self.reason = d.get("reason")
        self.status = d.get("status")


class _SquareAPIError(Exception):
    """A Square API call returned one or more errors
    """
    def __init__(self, description, errors=[]):
        super().__init__(description)
        self.errors = errors

    def __contains__(self, code):
        for e in self.errors:
            if code in e.get("code") or code in e.get("category"):
                return True
        return False

    def __str__(self):
        return f"Square API error: {self.description}; errors=[self.errors]"


class _SquareAPISession:
    def __init__(self, sandbox, secret):
        if sandbox:
            self.api = "https://connect.squareupsandbox.com/v2/"
        else:
            self.api = "https://connect.squareup.com/v2/"
        self._secret = secret
        self.session = requests.Session()
        self.session.hooks['response'].append(self._response_hook)
        self.session.verify = True
        self.session.headers.update(
            {'Square-Version': api_version,
             'Authorization': f"Bearer {secret}",
             'Content-Type': "application/json",
             })

    def close(self):
        self.session.close()

    def _response_hook(self, r, *args, **kwargs):
        if r.status_code >= 400:
            try:
                d = r.json()
            except Exception:
                raise _SquareAPIError(
                    f"{r.url}: {r.status_code} HTTP response with no JSON")
            errors = d.get("errors", [])
            raise _SquareAPIError(
                f"{r.url}: {r.status_code} HTTP response", errors=errors)

    def list_locations(self):
        r = self.session.get(self.api + "locations")
        d = r.json()
        return [Location(x) for x in d.get("locations", [])]

    def get_location(self, location_id):
        r = self.session.get(self.api + "locations/" + location_id)
        d = r.json()
        return Location(d["location"]) if "location" in d else None

    def list_device_codes(self, location_id, status="PAIRED"):
        params = {
            "location_id": location_id,
            "status": status,
            "product_type": "TERMINAL_API",
        }
        r = self.session.get(f"{self.api}devices/codes", params=params)
        d = r.json()
        return [DeviceCode(x) for x in d.get("device_codes", [])]

    def get_device_code(self, device_code_id):
        r = self.session.get(self.api + "devices/codes/" + device_code_id)
        d = r.json()
        return DeviceCode(d["device_code"]) if "device_code" in d else None

    def create_device_code(self, location_id, name):
        params = {
            "idempotency_key": idempotency_key(),
            "device_code": {
                "product_type": "TERMINAL_API",
                "location_id": location_id,
                "name": name,
            },
        }
        r = self.session.post(self.api + "devices/codes",
                              data=json.dumps(params))
        d = r.json()
        return DeviceCode(d["device_code"]) if "device_code" in d else None

    def create_terminal_checkout(self, checkout_data):
        r = self.session.post(self.api + "terminals/checkouts",
                              data=json.dumps(checkout_data))
        d = r.json()
        return TerminalCheckout(d["checkout"]) if "checkout" in d else None

    def cancel_terminal_checkout(self, checkout_id):
        r = self.session.post(
            f"{self.api}terminals/checkouts/{checkout_id}/cancel")
        d = r.json()
        return TerminalCheckout(d["checkout"]) if "checkout" in d else None

    def get_terminal_checkout(self, checkout_id):
        r = self.session.get(f"{self.api}terminals/checkouts/{checkout_id}")
        d = r.json()
        return TerminalCheckout(d["checkout"]) if "checkout" in d else None

    def create_terminal_action(self, action_data):
        r = self.session.post(self.api + "terminals/actions",
                              data=json.dumps(action_data))
        d = r.json()
        return TerminalAction(d["action"]) if "action" in d else None

    def cancel_terminal_action(self, action_id):
        r = self.session.post(
            f"{self.api}terminals/actions/{action_id}/cancel")
        d = r.json()
        return TerminalAction(d["action"]) if "action" in d else None

    def get_terminal_action(self, action_id):
        r = self.session.get(f"{self.api}terminals/actions/{action_id}")
        d = r.json()
        return TerminalAction(d["action"]) if "action" in d else None

    def get_payment(self, payment_id):
        r = self.session.get(f"{self.api}payments/{payment_id}")
        d = r.json()
        return SquarePayment(d["payment"]) if "payment" in d else None

    def list_payments(self, begin_time, end_time, location_id):
        payments = []
        # XXX The session start and end times are currently stored in
        # localtime; really they should be stored with timezone
        # info. A database change for the future!  In the meantime, we
        # err on the side of requesting too much data.
        params = {
            "begin_time": (
                begin_time.astimezone(datetime.timezone.utc)
                - datetime.timedelta(hours=1)).isoformat("T", "milliseconds"),
            "end_time": (
                end_time.astimezone(datetime.timezone.utc)
                + datetime.timedelta(hours=1)).isoformat("T", "milliseconds"),
            "location_id": location_id,
        }
        r = {"cursor": None}
        while "cursor" in r:
            params['cursor'] = r['cursor']
            r = self.session.get(
                f"{self.api}payments", params=params)
            d = r.json()
            payments.extend(SquarePayment(p) for p in d.get("payments", []))
        return payments

    def get_refund(self, refund_id):
        r = self.session.get(f"{self.api}refunds/{refund_id}")
        d = r.json()
        return PaymentRefund(d["refund"]) if "refund" in d else None

    def list_refunds(self, begin_time, end_time, location_id):
        refunds = []
        # XXX The session start and end times are currently stored in
        # localtime; really they should be stored with timezone
        # info. A database change for the future!  In the meantime, we
        # err on the side of requesting too much data.
        params = {
            "begin_time": (
                begin_time.astimezone(datetime.timezone.utc)
                - datetime.timedelta(hours=1)).isoformat("T", "milliseconds"),
            "end_time": (
                end_time.astimezone(datetime.timezone.utc)
                + datetime.timedelta(hours=1)).isoformat("T", "milliseconds"),
            "location_id": location_id,
        }
        r = {"cursor": None}
        while "cursor" in r:
            params['cursor'] = r['cursor']
            r = self.session.get(
                f"{self.api}refunds", params=params)
            d = r.json()
            refunds.extend(PaymentRefund(p) for p in d.get("refunds", []))
        return refunds

    def create_refund(self, refund_data):
        r = self.session.post(self.api + "refunds",
                              data=json.dumps(refund_data))
        d = r.json()
        return PaymentRefund(d["refund"]) if "refund" in d else None


class _SquarePaymentProgress(ui.basicpopup):
    """Popup window that progresses a Square payment
    """
    def __init__(self, register, payment_instance):
        # At this point, register is guaranteed to be current. Every
        # other time we are called (keypress or timeout) the register
        # may have ceased to be current and this should be checked
        # using register.entry_noninteractive(); if it returns False
        # we should clean up and exit since the payment will now be
        # progressing on another terminal.
        log.debug("SquarePaymentProgress starting")
        self.register = register
        self.payment_id = payment_instance.id
        super().__init__(
            7, 60, title=f"{payment_instance.paytype.description} payment",
            cleartext="Press Cancel to abort",
            colour=ui.colour_input)
        self.win.set_cursor(False)
        self.win.drawstr(2, 2, 14, "Terminal: ", align=">")
        self.win.drawstr(4, 2, 14, "Status: ", align=">")
        self.terminal = ui.label(2, 16, 43)
        self.terminal.set(payment_instance.meta.get(
            checkout_device_name_key).value)
        self.status = ui.label(4, 16, 43, contents="Connecting to Square")
        self.session = payment_instance.paytype.driver.api_session()
        # NB if timeout is set to "0" then update() is called before the
        # display is flushed
        self.timeout = tillconfig.mainloop.add_timeout(
            0.1, self._timer_update, "square progress init")

    def notify_hide(self):
        # The register page is about to be deselected. It may be
        # hidden, or it may be dismissed entirely. We can't continue
        # processing in the background with no register page, so halt
        # our timer and exit.
        log.debug("SquarePaymentProgress notify_hide: dismissing")
        if self.timeout:
            self.timeout.cancel()
            self.timeout = None
        self.dismiss()

    def dismiss(self):
        log.debug("SquarePaymentProgress dismiss")
        self.session.close()
        del self.session
        super().dismiss()

    def keypress(self, k):
        self.timeout.cancel()
        self.timeout = None
        if k == K_CANCEL:
            self.update(cancel=True)
        else:
            self.update(cancel=False)

    def _timer_update(self):
        # Timer doesn't start database session
        with td.orm_session():
            self.update()

    def update(self, cancel=False):
        # Called by timer or if Cancel key is pressed
        log.debug("SquarePaymentProgress update(cancel=%s)", cancel)
        self.timeout = None
        if not self.register.entry_noninteractive():
            self.dismiss()
            return
        p = td.s.query(Payment)\
                .options(joinedload('meta'))\
                .get(self.payment_id)
        details = json.loads(p.meta[checkout_details_key].value)
        if checkout_id_key in p.meta:
            # The checkout has been created; we need to read it for
            # an update. If we are cancelling, read it by posting to
            # the cancel endpoint instead
            if cancel:
                checkout = self.session.cancel_terminal_checkout(
                    p.meta[checkout_id_key].value)
            else:
                checkout = self.session.get_terminal_checkout(
                    p.meta[checkout_id_key].value)
        else:
            # Post the checkout, even if we are supposed to be
            # cancelling: there is no guarantee that we haven't
            # previously posted it and lost the response.
            c = {
                "idempotency_key": details["idempotency_key"],
                "checkout": {
                    "amount_money": details["amount"],
                    "device_options": {
                        "skip_receipt_screen": details["skip_receipt_screen"],
                        "device_id": details["device_id"],
                    },
                    "payment_type": "CARD_PRESENT",
                    "reference_id": str(p.id),
                    "note": f"Transaction {p.transaction.id} payment {p.id}",
                },
            }
            checkout = self.session.create_terminal_checkout(c)
        p.set_meta(checkout_id_key, checkout.id)
        p.set_meta(checkout_key, json.dumps(checkout.source_data))
        if checkout.status == "PENDING":
            self.status.set("Waiting for terminal")
            self.timeout = tillconfig.mainloop.add_timeout(
                1, self._timer_update, "square progress wait terminal")
            return
        elif checkout.status == "IN_PROGRESS":
            self.status.set("Waiting for customer")
            self.timeout = tillconfig.mainloop.add_timeout(
                5, self._timer_update, "square progress wait customer")
            return
        elif checkout.status == "CANCEL_REQUESTED":
            self.status.set("Attempting to cancel")
            self.timeout = tillconfig.mainloop.add_timeout(
                2, self._timer_update, "square progress wait cancel")
            return
        elif checkout.status == "CANCELED":
            self.dismiss()
            if checkout.cancel_reason == "SELLER_CANCELED":
                p.text = f"{p.paytype.description} cancelled from till"
            elif checkout.cancel_reason == "BUYER_CANCELED":
                p.text = f"{p.paytype.description} cancelled from terminal"
            elif checkout.cancel_reason == "TIMED_OUT":
                p.text = f"{p.paytype.description} timed out"
            else:
                p.text = f"{p.paytype.description} {checkout.cancel_reason}"
            p.pending = False
            self.register.payments_update()
            return
        elif checkout.status == "COMPLETED":
            # Fetch the payments. If there is more than one payment, insert
            # additional payments in the transaction.
            for idx, square_payment_id in enumerate(checkout.payment_ids):
                if idx == 0:
                    payment = p
                else:
                    payment = Payment(
                        transaction=p.transaction,
                        paytype=p.paytype,
                        user=p.user,
                        source=p.source,
                    )
                    td.s.add(payment)
                square_payment = self.session.get_payment(square_payment_id)
                payment.set_meta(payment_id_key, square_payment_id)
                payment.set_meta(
                    payment_key, json.dumps(square_payment.source_data))
                payment.amount = square_payment.total_money.as_decimal()
                payment.pending = False
                payment.text = f"{payment.paytype.description} "\
                    f"{square_payment_id[:6]}"
            # XXX insert additional payments into register dl?
            self.register.payments_update()
            self.dismiss()
            return
        else:
            self.status.set(f"Unrecognised checkout status {checkout.status}")
            self.timeout = tillconfig.mainloop.add_timeout(
                20, self._timer_update, "square progress wait unknown status")
            return


class _SquareRefundProgress(ui.basicpopup):
    """Popup window that progresses a Square refund
    """
    def __init__(self, register, payment_instance):
        # At this point, register is guaranteed to be current. Every
        # other time we are called (timeout) the register
        # may have ceased to be current and this should be checked
        # using register.entry_noninteractive(); if it returns False
        # we should clean up and exit since the payment will now be
        # progressing on another terminal.
        log.debug("SquareRefundProgress starting")
        self.register = register
        self.payment_id = payment_instance.id
        super().__init__(
            5, 36, title=f"{payment_instance.paytype.description} refund",
            colour=ui.colour_input)
        self.win.set_cursor(False)
        self.win.drawstr(2, 2, 32, "Connecting to Square")
        self.session = payment_instance.paytype.driver.api_session()
        # NB if timeout is set to "0" then update() is called before the
        # display is flushed
        self.timeout = tillconfig.mainloop.add_timeout(
            0.1, self._timer_update, "square refund progress init")

    def notify_hide(self):
        # The register page is about to be deselected. It may be
        # hidden, or it may be dismissed entirely. We can't continue
        # processing in the background with no register page, so halt
        # our timer and exit.
        log.debug("SquareRefundProgress notify_hide: dismissing")
        if self.timeout:
            self.timeout.cancel()
            self.timeout = None
        self.dismiss()

    def dismiss(self):
        log.debug("SquareRefundProgress dismiss")
        self.session.close()
        del self.session
        super().dismiss()

    def _timer_update(self):
        # Timer doesn't start database session
        with td.orm_session():
            self.update()

    def update(self):
        # Called by timer
        log.debug("SquareRefundProgress update")
        self.timeout = None
        if not self.register.entry_noninteractive():
            self.dismiss()
            return
        p = td.s.query(Payment)\
                .options(joinedload('meta'))\
                .get(self.payment_id)
        failed = f"{p.paytype.description} refund failed"
        details = json.loads(p.meta[refund_details_key].value)
        op = td.s.query(Payment)\
                 .options(joinedload('meta'))\
                 .get(details["till_payment_id"])
        # Sanity checks
        if not op or op.paytype != p.paytype \
           or payment_id_key not in op.meta \
           or payment_key not in op.meta:
            # We don't have enough details to continue
            # Abort the refund
            self.dismiss()
            p.text = failed
            p.pending = False
            self.register.payments_update()
            ui.infopopup(["The original payment could not be found or "
                          "was in an incorrect state."], title="Square error")
            return
        # Fetch the card details from the original payment
        op_sq = SquarePayment(json.loads(op.meta[payment_key].value))
        card = op_sq.card_details.card
        try:
            if refund_id_key in p.meta:
                # The refund has been created; we need to read it for
                # an update.
                refund = self.session.get_refund(
                    p.meta[refund_id_key].value)
            else:
                # The refund has not been created yet, or we might have
                # crashed after creating it but before committing its ID
                # to the database.
                refund = self.session.create_refund({
                    "idempotency_key": details["idempotency_key"],
                    "amount_money": details["amount"],
                    "payment_id": op.meta[payment_id_key].value,
                    "reason": f"Transaction {p.transid} refund {p.id}",
                    "payment_version_token": details["payment_version_token"],
                })
        except _SquareAPIError as e:
            # Abort the refund
            if "VERSION_MISMATCH" in e:
                # If this was a VERSION_MISMATCH we need to update the
                # cached SquarePayment on the original payment before
                # we exit, so we don't just get another
                # VERSION_MISMATCH when we try again
                self._update_original_payment(op)
            self.dismiss()
            p.text = failed
            p.pending = False
            self.register.payments_update()
            for error in e.errors:
                log.warning("Refund error code '%s'", error.get('code'))
            return
        p.set_meta(refund_id_key, refund.id)
        p.set_meta(refund_key, json.dumps(refund.source_data))
        p.set_meta(refund_card_key, json.dumps(card.source_data))
        if refund.status not in ("PENDING", "COMPLETED"):
            # The refund failed.
            self.dismiss()
            p.text = failed
            p.pending = False
            self.register.payments_update()
            log.warning("Refund ended up in state '%s'", refund.status)
            return
        # The refund succeeded.
        p.text = f"{p.paytype.description} refund {refund.id[:6]}"
        p.amount = -refund.amount_money.as_decimal()
        p.pending = False
        self.register.payments_update()
        td.s.commit()  # Ensure refund committed even if orig update failes
        self._update_original_payment(op)
        self.dismiss()

    def _update_original_payment(self, p):
        try:
            sp = self.session.get_payment(p.meta[payment_id_key].value)
        except _SquareAPIError:
            log.warning(
                "Could not fetch updated Square payment for %d", p.id)
            return
        p.set_meta(payment_key, json.dumps(sp.source_data))


def _load_driver(paytype):
    d = td.s.query(PayType).get(paytype)
    if not d:
        ui.infopopup([f"Payment type '{paytype}' not found"],
                     title="Error")
        return
    driver = d.driver
    if not driver.config_valid:
        ui.infopopup([f"Configuration for {driver.paytype} is not valid.",
                      "",
                      f"The problem is: {driver.config_problem}"],
                     title="Payment method configuration error")
        return
    return driver


class _NewTerminal(ui.dismisspopup):
    """Popup window to create a new DeviceCode
    """
    def __init__(self, paytype):
        self.paytype = paytype
        super().__init__(18, 60, title="Add new terminal",
                         colour=ui.colour_input)
        self.win.wrapstr(
            2, 2, 56,
            "Ensure that the new terminal is connected to WiFi and has "
            "installed any available software updates before continuing. "
            "After you select 'Add' you must complete the pairing process "
            "on the terminal within 5 minutes.")
        self.win.wrapstr(
            7, 2, 56,
            "To check for software updates, select 'Change Settings' on "
            "the terminal, then 'General', and at the bottom of the screen "
            "'About Terminal'. The software update status is then shown "
            "at the top of the screen, and if any updates are available "
            "you will be prompted to install them.")
        self.win.drawstr(14, 2, 6, "Name: ", align=">")
        self.namefield = ui.editfield(
            14, 8, 50, keymap={K_CLEAR: (self.dismiss, None)})
        button = ui.buttonfield(
            16, 27, 7, "Add", keymap={K_CASH: (self.finish, None)})
        ui.map_fieldlist([self.namefield, button])
        self.namefield.focus()

    def finish(self):
        if not self.namefield.f:
            ui.infopopup(["You must give the new terminal a name."],
                         title="Error")
            return
        self.dismiss()
        driver = _load_driver(self.paytype)
        if not driver:
            return
        dc = None
        with ui.exception_guard("creating device code"):
            with closing(driver.api_session()) as s:
                dc = s.create_device_code(driver._location, self.namefield.f)
        if not dc:
            return
        ui.infopopup([f"This terminal will be called '{self.namefield.f}'.",
                      "",
                      "On the new terminal, select 'Sign in' and then "
                      "'Use a device code'.",
                      "",
                      f"Enter the device code '{dc.code}'.",
                      "",
                      "You must do this within 5 minutes, otherwise the "
                      "code will expire and you will have to try again.",
                      "",
                      "After entering the device code, use the "
                      "Manage Terminals function again to check the pairing "
                      "has succeeded and store the new terminal details."],
                     title="Pair new terminal", colour=ui.colour_confirm,
                     dismiss=K_CASH)


class _ManageTerminal(ui.dismisspopup):
    """Popup window that fetches terminal details

    This popup does two entirely separate things. It fetches status
    information from the terminal and displays it: this doesn't
    require access to the database so no database session is started
    on timer callbacks.

    It also allows the terminal to be enabled and disabled, which
    requires database access to read and write the state.
    """
    def __init__(self, paytype, terminal):
        super().__init__(16, 60, title="Square Terminal details",
                         colour=ui.colour_input, dismiss=K_CASH)
        self.paytype = paytype
        self.terminal = terminal
        driver = _load_driver(paytype)
        self.action_params = {
            'idempotency_key': idempotency_key(),
            'action': {
                'device_id': terminal["device_id"],
                'type': "PING",
            },
        }
        self.win.set_cursor(False)
        self.win.drawstr(2, 2, 15, "Terminal name: ", align=">")
        self.win.drawstr(2, 17, 30, terminal["name"])
        self.win.drawstr(3, 2, 15, "Device code: ", align=">")
        self.win.drawstr(3, 17, 30, terminal["code"])
        self.win.drawstr(4, 2, 15, "Device ID: ", align=">")
        self.win.drawstr(4, 17, 30, terminal["device_id"])
        self.win.drawstr(5, 2, 15, "Disabled? ", align=">")
        self.win.drawstr(13, 2, 56, "Press 1 to enable the terminal or 0 to "
                         "disable it.")
        self.disabled = ui.label(5, 17, 10)
        self.win.drawstr(7, 2, 24, "Fetching device status: ", align=">")
        self.status = ui.label(7, 26, 30, contents="Connecting to Square")
        self.session = driver.api_session()
        self.action_id = None
        self.device_metadata = None
        # NB if timeout is set to "0" then update() is called before the
        # display is flushed
        self.timeout = tillconfig.mainloop.add_timeout(
            0.1, self.update, "square manageterminal init")
        self.timeout_length = self._timeout_policy()
        self.update_disabled()

    @staticmethod
    def _timeout_policy():
        yield 1
        yield 2
        yield 3
        yield 5
        while True:
            yield 10

    def notify_hide(self):
        # The register page is about to be deselected. It may be
        # hidden, or it may be dismissed entirely. We can't continue
        # processing in the background with no register page, so halt
        # our timer and exit.
        log.debug("Square Terminal Maintenance notify_hide: dismissing")
        self.dismiss()

    def dismiss(self):
        log.debug("Square Terminal Maintenance dismiss")
        if self.timeout:
            self.timeout.cancel()
            self.timeout = None
        if self.session:
            self.session.close()
        del self.session
        super().dismiss()

    def keypress(self, k):
        if k == "1":
            self.update_disabled(new_disabled_state=False)
        elif k == "0":
            self.update_disabled(new_disabled_state=True)
        else:
            super().keypress(k)

    def update(self):
        # Until device metadata is received, poll for it
        self.timeout = None
        if not self.session:
            return
        try:
            if not self.action_id:
                action = self.session.create_terminal_action(self.action_params)
                self.action_id = action.id
            else:
                action = self.session.get_terminal_action(self.action_id)
        except Exception as e:
            self.status.set(str(e))
            self.session.close()
            self.session = None
            return

        if action.status == "PENDING":
            self.status.set("Waiting for terminal")
            self.timeout = tillconfig.mainloop.add_timeout(
                next(self.timeout_length), self.update,
                "square terminal manage wait terminal")
        elif action.status == "IN_PROGRESS":
            self.status.set("Waiting for terminal response")
            self.timeout = tillconfig.mainloop.add_timeout(
                next(self.timeout_length), self.update,
                "square terminal manage wait terminal response")
        elif action.status == "CANCEL_REQUESTED":
            self.status.set("Cancelling request")
            self.timeout = tillconfig.mainloop.add_timeout(
                next(self.timeout_length), self.update,
                "square terminal manage wait terminal cancel")
        elif action.status == "CANCELED":
            self.status.set("Request cancelled")
            self.session.close()
            self.session = None
        elif action.status == "COMPLETED":
            self.status.set("Done")
            self.session.close()
            self.session = None
            md = action.device_metadata
            if md:
                del self.status
                self.win.clear(7, 2, 1, 56)
                y = 7
                self.win.drawstr(
                    y, 2, 56,
                    f"Battery charge: {md.battery_percentage}%"
                    + (" (Charging)" if md.charging_state == "CHARGING"
                       else ""))
                y += 1
                if md.network_connection_type == "WIFI":
                    self.win.drawstr(
                        y, 2, 56,
                        f"WiFi network name: {md.wifi_network_name}")
                    self.win.drawstr(
                        y + 1, 2, 56,
                        f"WiFi signal strength: {md.wifi_network_strength}")
                    y += 2
                else:
                    self.win.drawstr(
                        y, 2, 56, "Connected by Ethernet")
                    y += 1
                self.win.drawstr(
                    y, 2, 56,
                    f"IP address: {md.ip_address}")
                y += 1
                self.win.drawstr(
                    y, 2, 56,
                    f"App version: {md.app_version}  "
                    f"OS version: {md.os_version}")
                y += 1
            else:
                self.status.set("No data received")
        else:
            self.status.set("Unknown response status")

    def update_disabled(self, new_disabled_state=None):
        driver = _load_driver(self.paytype)
        state = driver._read_state(lock=new_disabled_state is not None)
        if new_disabled_state is not None:
            if new_disabled_state:
                if self.terminal["id"] not in state["disabled"]:
                    state["disabled"].append(self.terminal["id"])
            else:
                if self.terminal["id"] in state["disabled"]:
                    state["disabled"].remove(self.terminal["id"])
            driver._save_state(state)
        self.disabled.set("Yes" if self.terminal["id"] in state["disabled"]
                          else "No")


def _manage_terminals(paytype):
    d = _load_driver(paytype)
    if not d:
        return
    try:
        with ui.exception_guard("updating Square information",
                                suppress_exception=False):
            d._check_state(refresh=True)
    except Exception:
        return
    state = d._read_state()
    terminals = state["devices"]
    disabled = state["disabled"]
    f = ui.tableformatter(" l l l l ")
    header = f("Name", "Code", "Device ID", "State")
    menu = [("Add new terminal", _NewTerminal, (d.paytype.paytype,))]
    menu.extend(
        (f(t['name'], t['code'], t['device_id'],
           "Disabled" if t['id'] in disabled else "Available"),
         _ManageTerminal, (paytype, t))
        for t in terminals)
    ui.menu(menu, blurb=[header], title="Manage terminals")


def _test_connection(paytype):
    d = _load_driver(paytype)
    if not d:
        return
    l = None
    with ui.exception_guard("connecting to Square"):
        with closing(d.api_session()) as s:
            l = s.get_location(d._location)
    if l:
        ui.infopopup(
            [f"Mode: {'Sandbox' if d._sandbox_mode else 'Production'}",
             "",
             "Location details:",
             "",
             f"      ID: {l.id}",
             f"    Name: {l.name}",
             f"  Status: {l.status}",
             f"Currency: {l.currency}"],
            title="Connected to Square",
            colour=ui.colour_info, dismiss=K_CASH)


class SquareTerminal(payment.PaymentDriver):
    """Square Terminal

    https://developer.squareup.com/docs/terminal-api/overview

    PayType.config is a json object, as follows:

    - "secretstore" is the name of a secret store containing a secret
      named "api-key"

    - "sandbox" is set to True if using the Square "sandbox" developer
      mode, or False for production mode

    - "location" is the location ID of the Location the terminals are
      registered to; see https://developer.squareup.com/docs/locations-api

    - "mincharge" is the minimum payment amount to attempt. If we send
      a payment lower than Square's minimum to a terminal, it will
      display an error message and the transaction will fail.

    - "rollover_guard_time" is the time at which Square considers the
      next financial day to start. It is possible to configure Square
      to bundle up payments by financial day and pay them out net of
      fees to the associated bank account; this setting prevents
      payments from ending up in the wrong bundle and causing
      reconciliation to fail.

    - "skip_receipt_screen" is set to True to skip the screen on the
      terminal that offers to print a card receipt.

    PayType.state is used as a cache of terminal details so we can
    avoid calling list_device_codes() for every transaction. We also
    store a "disabled" setting for each terminal to temporarily remove
    it from the menu: the Devices API doesn't have any way to disable
    or remove a terminal once paired, it's currently only possible
    through the Square Dashboard. We refresh the cache whenever the
    "Manage Terminals" menu is opened.
    """
    mergeable = True

    def read_config(self):
        try:
            c = json.loads(self.paytype.config)
        except Exception:
            return "Config is not valid json"

        problems = []

        self._secretstore = None
        self._secret = None
        self._secretstore_name = c.get('secretstore')
        if not self._secretstore_name:
            problems.append("No secret store configured")
        else:
            self._secretstore = Secrets.find(self._secretstore_name)
            if not self._secretstore:
                problems.append("Secret store not found")
            else:
                try:
                    self._secret = self._secretstore.fetch("api-key")
                except SecretDoesNotExist:
                    problems.append("Secret not found in store")
                except SecretNotAvailable:
                    problems.append("Cannot read secret from store")

        self._sandbox_mode = c.get('sandbox')
        if self._sandbox_mode is None:
            problems.append("Sandbox/Production mode not set")

        self._location = c.get('location')
        if not self._location:
            problems.append("Location not specified")

        try:
            self._minimum_charge = Decimal(c.get('mincharge', minimum_charge))
        except Exception:
            self._minimum_charge = Decimal(minimum_charge)
            problems.append("Minimum charge is invalid")

        try:
            self._rollover_guard_time = c.get('rollover_guard_time', None)
            if self._rollover_guard_time:
                self._rollover_guard_time = datetime.time.fromisoformat(
                    self._rollover_guard_time)
        except Exception:
            self._rollover_guard_time = None
            problems.append("Rollover guard time is invalid")

        try:
            self._skip_receipt_screen = bool(c.get('skip_receipt_screen', True))
        except Exception:
            self._skip_receipt_screen = True
            problems.append("Skip receipt screen is invalid")

        return ", ".join(problems)

    def save_config(self):
        cfg = {
            'secretstore': getattr(self, "_secretstore_name", None),
            'sandbox': getattr(self, "_sandbox_mode", None),
            'location': getattr(self, "_location", None),
            'mincharge': str(getattr(self, "_minimum_charge", minimum_charge)),
            'skip_receipt_screen': getattr(self, "_skip_receipt_screen", True)
        }
        if hasattr(self, "_rollover_guard_time") and self._rollover_guard_time:
            cfg['rollover_guard_time'] = str(self._rollover_guard_time)
        self.paytype.config = json.dumps(cfg)

    def _read_state(self, lock=False):
        if lock:
            self.paytype = td.s.query(PayType)\
                               .filter(PayType.paytype == self.paytype.paytype)\
                               .with_for_update()\
                               .one_or_none()
        try:
            state = json.loads(self.paytype.state)
        except Exception:
            state = {}
        return state

    def _save_state(self, state):
        self.paytype.state = json.dumps(state)
        td.s.commit()

    def _check_state(self, refresh=False):
        # If state is invalid, update; if it is valid, simply return it
        state = self._read_state()
        if refresh or 'currency' not in state or 'devices' not in state:
            with closing(self.api_session()) as s:
                state = self._read_state(lock=True)
                if refresh or 'currency' not in state:
                    loc = s.get_location(self._location)
                    state['currency'] = loc.currency
                if refresh or 'devices' not in state:
                    devicecodes = s.list_device_codes(self._location)
                    state['devices'] = [x.as_state() for x in devicecodes]
                # 'disabled' is a list of device code IDs that are not
                # to be offered to the user when starting
                # payments. Ensure that all the device code IDs in the
                # 'disabled' list still exist.
                devicecode_ids = [x['id'] for x in state['devices']]
                state['disabled'] = [i for i in state.get('disabled', [])
                                     if i in devicecode_ids]
                self._save_state(state)
        return state

    def api_session(self):
        return _SquareAPISession(self._sandbox_mode, self._secret)

    def start_payment(self, register, transid, amount, outstanding):
        # rollover_guard_time applies to refunds as well as payments,
        # so check it before checking whether we are refunding
        if self._rollover_guard_time:
            session = Session.current(td.s)
            # session should not be None; this should have been
            # checked in register code before we are called.
            if not session:
                return
            now = datetime.datetime.now()
            date = now.date()
            if now.time() < self._rollover_guard_time:
                date = date - datetime.timedelta(days=1)
            if date != session.date:
                ui.infopopup(
                    [f"The card machines 'roll over' from one day to the next "
                     f"at around {self._rollover_guard_time}, so a card "
                     f"transaction performed now would be received with "
                     f"the card payments for {date:%d %B}.",
                     "",
                     f"The current session is for {session.date:%d %B}.",
                     "",
                     f"To perform a {self.paytype} transaction, close the "
                     f"current session and start a new one dated {date}.",
                     ],
                    title=f"{self.paytype} transactions not allowed")
                return
        if amount < zero:
            self._start_refund(register, transid, amount, outstanding)
            return
        if amount < self._minimum_charge:
            ui.infopopup(
                [f"The minimum amount you can charge using "
                 f"{self.paytype.description} is "
                 f"{tillconfig.fc(self._minimum_charge)}."],
                title=f"{self.paytype.description} payment")
            return
        if amount > outstanding:
            ui.infopopup(
                [f"You can't take an overpayment using "
                 f"{self.paytype.description}."],
                title="Overpayment not accepted")
            return
        state = self._check_state()

        devices = [(ds['device_id'], ds['name']) for ds in state['devices']
                   if ds['id'] not in state['disabled']]
        if self._sandbox_mode:
            devices.extend(sandbox_devices.items())
        idk = idempotency_key()
        square_amount = Money.from_decimal(amount, state["currency"])
        menu = [
            (device_name,
             self._create_pending_payment,
             (self.paytype.paytype, register, transid, outstanding,
              {
                  checkout_device_name_key: device_name,
                  checkout_details_key: json.dumps({
                      'idempotency_key': idk,
                      'amount': square_amount.source_data,
                      'device_id': device_id,
                      'skip_receipt_screen': self._skip_receipt_screen,
                  }),
              }),
             )
            for device_id, device_name in devices]
        title = f"{self.paytype} payment of {tillconfig.fc(amount)}"
        if len(menu) > 1:
            ui.automenu(menu, title=title,
                        blurb=["", "Select terminal for payment:"])
        elif len(menu) == 1:
            menu[0][1](*menu[0][2])
        else:
            ui.infopopup(["No terminals are available.", "",
                          f"Register or enable terminals using Manage Till → "
                          f"Payment methods → {self.paytype} → "
                          f"Manage terminals."], title=title)

    def _start_refund(self, register, transid, amount, outstanding):
        if amount < outstanding:
            ui.infopopup(
                ["You can't refund more than the amount due back."],
                title="Refund too large")
            return

        trans = td.s.query(Transaction).get(transid)
        related = trans.related_transaction_ids()

        # Filter payments by age: if over a year old they can't be
        # refunded through Square
        oldest_refundable = datetime.date.today()\
            - datetime.timedelta(days=364)
        payments = td.s.query(Payment)\
                       .options(joinedload('meta'))\
                       .filter(Payment.paytype == self.paytype)\
                       .filter(Payment.transid.in_(related))\
                       .filter(Payment.amount > zero)\
                       .filter(Payment.time > oldest_refundable)\
                       .order_by(Payment.time)\
                       .all()

        f = ui.tableformatter(" c l l l r r r ")
        header = f("Transaction", "Time", "Card number", "Expires",
                   "Paid", "Refunded", "Available")
        idk = idempotency_key()

        try:
            with closing(self.api_session()) as s:
                # really want the walrus for this... :=
                menu = [
                    self._refund_details_from_payment(
                        s, f, idk, payment, register, transid,
                        amount, outstanding)
                    for payment in payments]
                menu = [x for x in menu if x]
        except _SquareAPIError as e:
            ui.infopopup(
                ["There was an error fetching payment information from "
                 "Square. Please try again later.",
                 "",
                 f"The error was: {e}"], title="Square error")
            return

        if not menu:
            ui.infopopup(
                [f"There are no eligible {self.paytype.description} "
                 f"payments in the transactions that were voided to "
                 f"set up this refund, so it's not possible to issue a "
                 f"refund using {self.paytype.description}.",
                 "",
                 f"Hint: you must find the transaction with the original "
                 f"{self.paytype.description} payment in that you need to "
                 f"refund, and void the appropriate lines from there.",
                 "",
                 "Payments that have already been fully refunded cannot "
                 "be used to issue further refunds.",
                 ], title="No refundable payments found")
            return

        blurb = [
            ui.emptyline(),
            ui.lrline(
                "Check that the card details match the customer's card, "
                "and the original payment amount is as expected. The "
                "refund will be sent directly to this card."),
            ui.emptyline(),
            ui.lrline(
                "Hint: if the payment was made using a phone or watch, "
                "the card number will be different to the original card "
                "and can be viewed in the wallet application on the "
                "device."),
            ui.emptyline(),
            header,
        ]

        ui.menu(menu, blurb=blurb, title="Choose payment to refund")

    def _refund_details_from_payment(
            self, s, f, idk, payment, register, transid, amount, outstanding):
        # Refresh the SquarePayment because it will probably have changed
        # (fees added) since it was cached
        pi = s.get_payment(payment.meta[payment_id_key].value)
        payment.set_meta(payment_key, json.dumps(pi.source_data))
        card = pi.card_details.card
        paid = pi.total_money.as_decimal()
        refunded = pi.refunded_money.as_decimal() if pi.refunded_money \
            else zero
        available = paid - refunded
        if available <= zero:
            return

        fc = tillconfig.fc

        refund_amount = min(available, -amount)
        square_amount = Money.from_decimal(
            refund_amount, pi.total_money.currency)

        return (
            f(payment.transid, payment.time.strftime("%H:%M"),
              card.cardnum, card.expires,
              fc(paid), fc(refunded), fc(available)),
            SquareTerminal._create_pending_payment,
            (self.paytype.paytype, register, transid, outstanding, {
                refund_details_key: json.dumps({
                    'idempotency_key': idk,
                    'amount': square_amount.source_data,
                    'till_payment_id': payment.id,
                    'payment_version_token': pi.version_token,
                }),
            }),
        )

    @staticmethod
    def _create_pending_payment(
            paytype, register, transid, outstanding, metadata):
        # Load the payment method and driver
        pm = td.s.query(PayType).get(paytype)
        if not pm:
            ui.infopopup([f"Payment method {paytype} has been deleted!"],
                         title="Error")
            return
        if not pm.active:
            ui.infopopup([f"{pm.description} is no longer active."],
                         title="Error")
            return
        # Check that the transaction and outstanding amount have not changed
        # since the device menu was popped up
        reg_trans = register.gettrans()
        if not reg_trans:
            ui.infopopup(["Transaction has vanished since payment "
                          "was started."], title="Error")
            return
        if reg_trans.id != transid:
            ui.infopopup(["Active transaction in register has changed "
                          "since payment was started."], title="Error")
            return
        if reg_trans.balance != outstanding:
            ui.infopopup(["Transaction balance has changed since "
                          "payment was started."], title="Error")
            return
        user = ui.current_user().dbuser
        td.s.add(user)  # hack! See github issue #220
        p = Payment(transaction=reg_trans, amount=zero, paytype=pm,
                    text=pm.description, user=user,
                    source=tillconfig.terminal_name, pending=True)
        for k, v in metadata.items():
            p.set_meta(k, v)
        td.s.add(p)
        td.s.flush()  # ensure p.id is known
        pline = payment.pline(p)
        register.add_payments(transid, [pline])
        pm.driver.resume_payment(register, p)

    def resume_payment(self, register, payment_instance):
        if payment_instance.paytype != self.paytype:
            return
        if checkout_details_key in payment_instance.meta:
            _SquarePaymentProgress(register, payment_instance)
        elif refund_details_key in payment_instance.meta:
            _SquareRefundProgress(register, payment_instance)
        else:
            ui.infopopup(["Can't work out whether this pending Square "
                          "payment is a checkout or a refund"],
                         title="Error")

    def receipt_details(self, d, p):
        if p.paytype != self.paytype:
            return
        if payment_key not in p.meta and refund_card_key not in p.meta:
            return
        d.printline(f"{p.text}:")
        if p.amount < zero:
            pi = None
            card = Card(json.loads(p.meta[refund_card_key].value))
            d.printline(f"     Refund amount: {tillconfig.fc(-p.amount)}")
        else:
            pi = SquarePayment(json.loads(p.meta[payment_key].value))
            card = pi.card_details.card
        d.printline(f"       Card number: {card.cardnum}")
        d.printline(f"       Expiry date: {card.expires}")
        if p.amount >= zero:
            entry_method = pi.card_details.entry_method
            aid = pi.card_details.application_identifier
            aname = pi.card_details.application_name
            acryptogram = pi.card_details.application_cryptogram
            authcode = pi.card_details.auth_result_code
            vmethod = pi.card_details.verification_method
            d.printline(f" Card entry method: {entry_method}")
            if aid:
                d.printline(f"    Application ID: {aid}")
            if aname:
                d.printline(f"  Application name: {aname}")
            if acryptogram:
                d.printline(f"    App cryptogram: {acryptogram}")
            if vmethod:
                d.printline(f"               CVM: {vmethod}")
            if authcode:
                d.printline(f"         Auth code: {authcode}")
        d.printline()

    def total(self, sessionid, fields):
        # The Payment objects stored in the payment_key and refund_key
        # metadata are likely to be missing their processing_fee data:
        # Square do not guarantee a time frame for this field to be
        # populated, they merely state it is likely to be "ten seconds
        # or so".
        #
        # We start by bulk fetching payments and refunds for the time
        # frame covered by the session. Any payments that happen to
        # fall outside this time frame can be fetched by ID.
        session = td.s.query(Session).get(sessionid)
        with closing(self.api_session()) as s:
            sqpayments = {
                sp.id: sp for sp in s.list_payments(
                    session.starttime, session.endtime, self._location)}
            sqrefunds = {
                sr.id: sr for sr in s.list_refunds(
                    session.starttime, session.endtime, self._location)}

            payments = td.s.query(Payment)\
                           .join(Transaction)\
                           .filter(Transaction.sessionid == sessionid)\
                           .filter(Payment.paytype == self.paytype)\
                           .options(joinedload('meta'))\
                           .all()
            amount = zero
            fees = zero
            for p in payments:
                if p.amount > zero:
                    if payment_id_key not in p.meta:
                        raise payment.PaymentTotalError(
                            f"Payment {p.id} is missing {payment_id_key} "
                            f"metadata")
                    sqid = p.meta[payment_id_key].value
                    if sqid in sqpayments:
                        sp = sqpayments[sqid]
                    else:
                        log.warning(
                            "Square payment %d not in bulk fetch", p.id)
                        sp = s.get_payment(sqid)
                    if not sp:
                        raise payment.PaymentTotalError(
                            f"Could not retrieve Square Payment details for "
                            f"payment number {p.id}")
                    p.set_meta(payment_key, json.dumps(sp.source_data))
                    amount += sp.total_money.as_decimal()
                    if not sp.processing_fee:
                        raise payment.PaymentTotalError(
                            f"No Square fees listed for payment number {p.id}")
                    for pf in sp.processing_fee:
                        fees += pf.amount_money.as_decimal()
                elif p.amount < zero:
                    if refund_id_key not in p.meta:
                        raise payment.PaymentTotalError(
                            f"Refund {p.id} is missing {refund_id_key} "
                            f"metadata")
                    sqid = p.meta[refund_id_key].value
                    if sqid in sqrefunds:
                        sr = sqrefunds[sqid]
                    else:
                        log.warning(
                            "Square refund %d not in bulk fetch", p.id)
                        sr = s.get_refund(sqid)
                    if not sr:
                        raise payment.PaymentTotalError(
                            f"Could not retrieve Square Refund details for "
                            f"refund number {p.id}")
                    p.set_meta(refund_key, json.dumps(sr.source_data))
                    amount -= sr.amount_money.as_decimal()
                    if not sr.processing_fee:
                        raise payment.PaymentTotalError(
                            f"No Square fees listed for refund number {p.id}")
                    for pf in sr.processing_fee:
                        fees += pf.amount_money.as_decimal()
        return (amount, fees)

    def manage(self):
        ui.automenu([
            ("Manage terminals", _manage_terminals, (self.paytype.paytype,)),
            ("Test connection to Square", _test_connection,
             (self.paytype.paytype,)),
        ], title=f"{self.paytype} management")

    def _configure_secretstore(self):
        self._secretstore_name = input("Secret store name: ")
        self.save_config()

    def _configure_sandbox(self):
        self._sandbox_mode = \
            input("Sandbox or Production mode? ") != "Production"
        self.save_config()

    def _configure_location(self):
        print("Location needs configuring\n")
        with closing(self.api_session()) as s:
            locations = s.list_locations()
        for n, l in enumerate(locations):
            print(f"{n}: {l.name} ({l.status})")
        idx = int(input("Location number: "))
        self._location = locations[idx].id
        self.save_config()

    def configure_cmd(self):
        if self.config_valid:
            print("Configuration is currently valid.\n")
            if self._sandbox_mode:
                print("*** IN SANDBOX MODE: no devices can be paired ***\n")
            with closing(self.api_session()) as s:
                l = s.get_location(self._location)
                print(f"Current location: {l}\n")
                devicecodes = s.list_device_codes(l.id, status="PAIRED")
                if devicecodes:
                    print("Paired devices:")
                    for dc in devicecodes:
                        print(f"{dc.code} {dc.name} ({dc.device_id})")
                else:
                    print("No paired devices.")

            print("\nTo reconfigure, delete current configuration using web "
                  "interface and try again.")
            return 0
        print(f"Current configuration problems: {self.config_problem}\n")

        if not hasattr(self, "_secretstore_name"):
            self.save_config()
            print("Default configuration saved. Run again to continue.")
            return 1

        if not getattr(self, "_secretstore_name", None):
            self._configure_secretstore()
            return 1
        if not self._secretstore:
            print(f"Add a quicktill.secretstore.Secrets() to the configuration "
                  f"file with key_name '{self._secretstore_name}' to "
                  f"continue. Use the following command to generate the key:")
            print("runtill generate-secret-key")
            return 1
        if not self._secret:
            print("Use the following command to set the API key:")
            print(f"runtill passwd {self._secretstore_name} api-key")
            return 1

        if self._sandbox_mode is None:
            self._configure_sandbox()
            return 1

        if not self._location:
            self._configure_location()
