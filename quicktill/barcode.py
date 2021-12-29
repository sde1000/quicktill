"""Barcodes and barcode scanners

Barcodes are stored in a table in the database. Each barcode may refer
to a stock type or a price lookup.

Barcode scanners can be attached to the till in may different ways:
they may appear to be keyboards ('keyboard wedge' interface), serial
ports (real, or over USB or Bluetooth) or USB HID-POS devices.

For now we're using an external barcode scanner driver that sends
scans to us on UDP port 8456.

When a barcode is detected, a quicktill.barcode.scan instance is
passed to ui.handle_keyboard_input().
"""

import logging
import socket
from . import tillconfig
from . import ui
from . import td

log = logging.getLogger(__name__)

class barcode:
    def __init__(self, code):
        self.code = code

    def feedback(self, valid: bool) -> None:
        """Feedback to scanner user

        Attempt to indicate to the barcode scanner user whether this
        scan was recognised, for example by being successfully looked
        up in the database.

        The scanner may indicate this in a number of different
        ways. For example, the scanner may make a different pitch of
        beep, or project the aiming pattern using a different coloured light.
        """
        pass

    def __str__(self):
        return f"barcode('{self.code}')"

class barcodelistener:
    def __init__(self, address, addressfamily=socket.AF_INET):
        self.s = socket.socket(addressfamily, socket.SOCK_DGRAM)
        self.s.bind(address)
        self.s.setblocking(0)
        tillconfig.mainloop.add_fd(self.s.fileno(), self.doread,
                                   desc="barcode listener")

    def doread(self):
        d = self.s.recv(1024).strip().decode("utf-8")
        log.debug("Received barcode: {}".format(repr(d)))
        if d:
            ui.unblank_screen()
            with td.orm_session():
                ui.handle_keyboard_input(barcode(d))
