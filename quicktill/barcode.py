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
from . import keyboard
from . import stocklines
from . import plu
from . import stocktype
from . import modifiers
from . import user
from .models import Barcode

log = logging.getLogger(__name__)


class barcode:
    def __init__(self, code):
        self.code = code
        self.binding = td.s.get(Barcode, code)

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
        log.debug(f"Received barcode: {d}")
        if d:
            ui.unblank_screen()
            with td.orm_session():
                ui.handle_keyboard_input(barcode(d))


class barcodefield(ui.editfield):
    def keypress(self, k):
        if hasattr(k, 'code'):
            self.setf(k.code)
        else:
            super().keypress(k)


class enter_barcode(ui.dismisspopup):
    def __init__(self, func):
        super().__init__(7, 60, title="Enter barcode", colour=ui.colour_input)
        self.func = func
        self.win.drawstr(2, 2, 9, "Barcode: ", align=">")
        self.f = barcodefield(2, 11, 47, flen=1000, keymap={
            keyboard.K_CLEAR: (self.dismiss, None)})
        self.b = ui.buttonfield(4, 26, 8, "Edit", keymap={
            keyboard.K_CASH: (self.enter, None)})
        ui.map_fieldlist([self.f, self.b])
        self.f.focus()

    def enter(self):
        if self.f.f:
            self.dismiss()
            self.func(barcode(self.f.f))
        else:
            ui.infopopup(["You must enter or scan a barcode."],
                         title="Error")


class _new_barcode_mixin:
    def keypress(self, k):
        if hasattr(k, 'code'):
            self.dismiss()
            edit_barcode(k)
        else:
            super().keypress(k)


class _barcode_change_confirmed(_new_barcode_mixin, ui.infopopup):
    def __init__(self, message):
        super().__init__(message, title="Barcode updated",
                         colour=ui.colour_info, dismiss=keyboard.K_CASH)


class edit_barcode(user.permission_checked, _new_barcode_mixin, ui.keymenu):
    permission_required = ('edit-barcode', "Change barcode assignment")

    def __init__(self, b):
        binding = b.binding
        if binding:
            m = binding.modifier
            if binding.stockline:
                desc = f'stock line "{binding.stockline}"'
            elif binding.plu:
                desc = f'price lookup "{binding.plu}"'
            elif binding.stocktype:
                desc = f'stock type "{binding.stocktype}"'
            else:
                desc = f'modifier "{binding.modifier}"'
                m = None
            if m:
                desc += f' with modifier "{m}"'
            blurb = f"Barcode {b.code} currently refers to {desc}."
        else:
            blurb = f"Barcode {b.code} is not currently in use."

        menu = [
            ("1", "Assign to a stock line", self.stockline, (b.code,)),
            ("2", "Assign to a price lookup", self.plu, (b.code,)),
            ("3", "Assign to a stock type", self.stocktype, (b.code,)),
            ("4", "Assign to a modifier", self.modifier, (b.code,)),
        ]
        if binding \
           and (binding.stockline or binding.plu or binding.stocktype):
            menu.append(
                ("5", "Change the default modifier",
                 self.defmodifier, (b.code,)))
        if binding:
            menu.append(
                ("6", "Forget this barcode", self.remove, (b.code,)))

        super().__init__(menu, ["", blurb], title="Assign barcode")

    @staticmethod
    def _clear_binding(code):
        b = barcode(code)
        binding = b.binding or Barcode(id=code)
        binding.plu = None
        binding.stocktype = None
        binding.stockline = None
        binding.modifier = None
        td.s.add(binding)
        return binding

    def stockline(self, code):
        stocklines.selectline(
            lambda stockline: self._finish_stockline(code, stockline),
            blurb=f'Choose a stock line to assign to barcode "{code}"')

    def _finish_stockline(self, code, stockline):
        binding = self._clear_binding(code)
        binding.stockline = stockline
        td.s.commit()
        _barcode_change_confirmed(
            [f'Barcode {code} is now assigned to stock line "{stockline}".'])

    def plu(self, code):
        plu.selectplu(
            lambda plu: self._finish_plu(code, plu),
            blurb=f'Choose a price lookup to assign to barcode "{code}"')

    def _finish_plu(self, code, plu):
        binding = self._clear_binding(code)
        binding.plu = plu
        td.s.commit()
        _barcode_change_confirmed(
            [f'Barcode {code} is now assigned to price lookup "{plu}".'])

    def stocktype(self, code):
        stocktype.choose_stocktype(lambda st: self._finish_stocktype(code, st),
                                   allownew=False)

    def _finish_stocktype(self, code, st):
        binding = self._clear_binding(code)
        binding.stocktype = st
        td.s.commit()
        _barcode_change_confirmed(
            [f'Barcode {code} is now assigned to stock type "{st}".'])

    def modifier(self, code):
        modifiers.selectmodifier(lambda m: self._finish_modifier(code, m))

    def _finish_modifier(self, code, m):
        binding = self._clear_binding(code)
        binding.modifier = m
        td.s.commit()
        _barcode_change_confirmed(
            [f'Barcode {code} is now assigned to modifier "{m}".'])

    def defmodifier(self, code):
        modifiers.selectmodifier(lambda m: self._finish_defmodifier(code, m),
                                 allow_none=True)

    def _finish_defmodifier(self, code, m):
        b = barcode(code)
        binding = b.binding
        if binding:
            binding.modifier = m
            td.s.commit()
            _barcode_change_confirmed(
                [f'Barcode {code} now has default modifier "{m}".'])
        else:
            _barcode_change_confirmed(
                [f"Barcode {code} was removed before you picked a modifier."])

    def remove(self, code):
        b = barcode(code)
        if b.binding:
            td.s.delete(b.binding)
            td.s.commit()
        _barcode_change_confirmed([f"Barcode {code} has been removed."])
