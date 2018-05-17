"""Till management functions.
"""

import sys
import os
from . import ui, keyboard, td, printer, session, user
from . import tillconfig, linekeys, stocklines, plu, modifiers
from .version import version
import subprocess

import logging
log=logging.getLogger(__name__)

class receiptprint(user.permission_checked,ui.dismisspopup):
    permission_required=('print-receipt-by-number',
                         'Print any receipt given the transaction number')
    def __init__(self):
        ui.dismisspopup.__init__(self,5,30,title="Receipt print",
                                 dismiss=keyboard.K_CLEAR,
                                 colour=ui.colour_input)
        self.addstr(2,2,"Receipt number:")
        self.rnfield = ui.editfield(
            2, 18, 10, validate=ui.validate_positive_nonzero_int, keymap={
                keyboard.K_CASH: (self.enter, None, True)})
        self.rnfield.focus()
    def enter(self):
        try:
            rn=int(self.rnfield.f)
        except:
            rn=None
        if rn is None: return
        self.dismiss()
        log.info("Manage Till: printing transaction %d",rn)
        ui.toast("The receipt is being printed.")
        with ui.exception_guard("printing the receipt",title="Printer error"):
            printer.print_receipt(rn)

@user.permission_required('version','See version information')
def versioninfo():
    """
    Display the till version information.

    """
    log.info("Version popup")
    ui.infopopup(["Quick till software %s"%version,
                  "(C) Copyright 2004-2018 Stephen Early",
                  "Configuration: %s"%tillconfig.configversion,
                  "Operating system: %s %s %s"%(os.uname()[0],
                                                os.uname()[2],
                                                os.uname()[3]),
                  "Python version: %s %s"%tuple(sys.version.split('\n')),
                  td.db_version()],
                 title="Software Version Information",
                 colour=ui.colour_info,dismiss=keyboard.K_CASH)

@user.permission_required('exit',"Exit the till software")
def restartmenu():
    log.info("Restart menu")
    menu = [(x[1], tillconfig.mainloop.shutdown, (x[0],))
            for x in tillconfig.exitoptions]
    ui.automenu(menu, title="Exit / restart options")

class slmenu(ui.keymenu):
    def __init__(self):
        log.info("Stock line / PLU management popup")
        menu=[
            ("1", "Stock lines", stocklines.stocklinemenu, None),
            ("2", "Price lookups", plu.plumenu, None),
            ("3", "Modifiers", modifiers.modifiermenu, None),
            ("4", "List stock lines with no key bindings",
             stocklines.listunbound, None),
            ("5", "List price lookups with no key bindings",
             plu.listunbound, None),
            ("6", "Return items from display to stock",
             stocklines.selectline,
             (stocklines.return_stock, "Return Stock",
              "Select the stock line to remove from display", ["display"])),
            ("7", "Edit key labels", linekeys.edit_keycaps, None),
        ]
        ui.keymenu.__init__(
            self, menu, title="Stock line and PLU options",
            blurb="You can press a line key here to go directly to "
            "editing stock lines, price lookups and modifiers that are "
            "already bound to it.")
    def keypress(self, k):
        if hasattr(k, 'line'):
            linekeys.linemenu(k, self.line_selected, allow_stocklines=True,
                              allow_plus=True, allow_mods=True)
        else:
            ui.keymenu.keypress(self, k)
    def line_selected(self, kb):
        self.dismiss()
        td.s.add(kb)
        if kb.stockline:
            stocklines.modify(kb.stockline)
        elif kb.plu:
            plu.modify(kb.plu)
        else:
            modifiers.modify(kb.modifier)

@user.permission_required('netinfo', 'See network information')
def netinfo():
    log.info("Net info popup")
    v4=subprocess.check_output(["ip","-4","addr"]).decode('ascii')
    v6=subprocess.check_output(["ip","-6","addr"]).decode('ascii')
    ui.infopopup(["IPv4:"]+v4.split('\n')+["IPv6:"]+v6.split('\n'),
                 title="Network information",colour=ui.colour_info)

@user.permission_required('fullscreen', 'Enter / leave fullscreen mode')
def fullscreen(setting):
    ui.rootwin.set_fullscreen(setting)

def sys_menu():
    log.info("System menu")
    menu = [
        ("1", "Software versions", versioninfo, None),
        ("2", "Network status", netinfo, None),
    ]
    if ui.rootwin.supports_fullscreen:
        menu += [
            ("3", "Enter fullscreen mode", fullscreen, (True,)),
            ("4", "Leave fullscreen mode", fullscreen, (False,)),
        ]
    ui.keymenu(menu, title="System information and settings")

def debug_menu():
    log.info("Debug menu")
    def raise_test_exception():
        raise Exception("Test exception")

    def several_toasts():
        ui.toast("Toast number one")
        ui.toast("Toast number two")
        ui.toast("The third toast")

    def long_toast():
        import time
        ui.toast("Delay for 10 seconds...")
        time.sleep(10)
        ui.toast("Delay done")

    def raise_print_exception():
        with ui.exception_guard("testing exception raised in printer driver"):
            with printer.driver as d:
                d.printline("This line is printed before the exception")
                raise Exception

    menu = [
        ("1", "Raise uncaught exception", raise_test_exception, None),
        ("2", "Series of toasts", several_toasts, None),
        ("3", "Toast covering a long operation", long_toast, None),
        ("4", "Raise exception while printing", raise_print_exception, None),
    ]
    ui.keymenu(menu, title="Debug")

def popup():
    log.info("Till management menu")
    if not tillconfig.exitoptions:
        exit = ("8", "Exit till software", tillconfig.mainloop.shutdown, (0,))
    elif len(tillconfig.exitoptions) == 1:
        exit = ("8", tillconfig.exitoptions[0][1],
                tillconfig.mainloop.shutdown, (tillconfig.exitoptions[0][0],))
    else:
        exit = ("8", "Exit / restart till software",
                restartmenu, None)
    menu=[
        ("1", "Sessions", session.menu, None),
        ("2", "Current session summary", session.currentsummary, None),
        ("4", "Stock lines, PLUs and modifiers", slmenu, None),
        ("6", "Print a receipt", receiptprint, None),
        ("7", "Users", user.usersmenu, None),
        exit,
        ("9", "System information and settings", sys_menu, None),
        ]
    if tillconfig.debug:
        menu.append(("0", "Debug options", debug_menu, None))

    ui.keymenu(menu, title="Management options")
