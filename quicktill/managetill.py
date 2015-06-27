"""Till management functions.

"""

from __future__ import unicode_literals
import sys,os
from . import ui,keyboard,td,printer,session,user
from . import tillconfig,linekeys,stocklines,plu,modifiers,event
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
        self.rnfield=ui.editfield(
            2,18,10,validate=ui.validate_int,keymap={
                keyboard.K_CASH: (self.enter,None,True)})
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
                  "(C) Copyright 2004-2015 Stephen Early",
                  "Configuration: %s"%tillconfig.configversion,
                  "Operating system: %s %s %s"%(os.uname()[0],
                                                os.uname()[2],
                                                os.uname()[3]),
                  "Python version: %s %s"%tuple(sys.version.split('\n')),
                  td.db_version()],
                 title="Software Version Information",
                 colour=ui.colour_info,dismiss=keyboard.K_CASH)

def exitoption(code):
    event.shutdowncode=code

@user.permission_required('exit',"Exit the till software")
def restartmenu():
    log.info("Restart menu")
    menu=[
        (keyboard.K_ONE,"Exit / restart till software",exitoption,(0,)),
        (keyboard.K_TWO,"Turn off till",exitoption,(2,)),
        (keyboard.K_THREE,"Reboot till",exitoption,(3,)),
        ]
    ui.keymenu(menu,title="Exit / restart options")

def slmenu():
    log.info("Stock line / PLU management popup")
    menu=[
        (keyboard.K_ONE,"Stock lines",stocklines.stocklinemenu,None),
        (keyboard.K_TWO,"Price lookups",plu.plumenu,None),
        (keyboard.K_THREE,"Modifiers",modifiers.modifiermenu,None),
        (keyboard.K_FOUR,"List stock lines with no key bindings",
         stocklines.listunbound,None),
        (keyboard.K_FIVE,"List price lookups with no key bindings",
         plu.listunbound,None),
        (keyboard.K_SIX,"Return items from display to stock",
         stocklines.selectline,
         (stocklines.return_stock,"Return Stock",
          "Select the stock line to remove from display",True)),
        (keyboard.K_SEVEN,"Edit key labels",linekeys.edit_keycaps,None),
        ]
    ui.keymenu(menu,title="Stock line and PLU options")

def netinfo():
    log.info("Net info popup")
    v4=subprocess.check_output(["ip","-4","addr"])
    v6=subprocess.check_output(["ip","-6","addr"])
    ui.infopopup(["IPv4:"]+v4.split('\n')+["IPv6:"]+v6.split('\n'),
                 title="Network information",colour=ui.colour_info)

def sysinfo_menu():
    log.info("System information menu")
    menu=[
        (keyboard.K_ONE,"Software versions",versioninfo,None),
        (keyboard.K_TWO,"Network status",netinfo,None),
        ]
    ui.keymenu(menu,title="System information")

def popup():
    log.info("Till management menu")
    menu=[
        (keyboard.K_ONE,"Sessions",session.menu,None),
        (keyboard.K_TWO,"Current session summary",session.currentsummary,None),
        (keyboard.K_FOUR,"Stock lines, PLUs and modifiers",slmenu,None),
        (keyboard.K_SIX,"Print a receipt",receiptprint,None),
        (keyboard.K_SEVEN,"Users",user.usersmenu,None),
        (keyboard.K_EIGHT,"Exit / restart",restartmenu,None),
        (keyboard.K_NINE,"System information",sysinfo_menu,None),
        ]
    ui.keymenu(menu,title="Management options")
