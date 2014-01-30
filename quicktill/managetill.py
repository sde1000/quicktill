"""Till management functions.

"""

from __future__ import unicode_literals
import sys,os
from . import ui,keyboard,td,printer,session,user
from . import tillconfig,managekeyboard,stocklines,event
from .version import version

import logging
log=logging.getLogger(__name__)

@user.permission_required(
    'restore-deferred','Restore deferred transactions to the current session')
def transrestore():
    log.info("Restore deferred transactions")
    td.trans_restore()
    ui.infopopup(["All deferred transactions have been restored."],
                 title="Confirmation",colour=ui.colour_confirm,
                 dismiss=keyboard.K_CASH)

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
        printer.print_receipt(rn)
        self.dismiss()

@user.permission_required('version','See version information')
def versioninfo():
    """
    Display the till version information.

    """
    log.info("Version popup")
    ui.infopopup(["Quick till software %s"%version,
                  "(C) Copyright 2004-2014 Stephen Early",
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
    ui.keymenu(menu,"Exit / restart options")

def popup():
    log.info("Till management menu")
    menu=[
        (keyboard.K_ONE,"Sessions",session.menu,None),
        (keyboard.K_TWO,"Current session summary",session.currentsummary,None),
        (keyboard.K_THREE,"Restore deferred transactions",transrestore,None),
        (keyboard.K_FOUR,"Stock lines",stocklines.popup,None),
        (keyboard.K_FIVE,"Keyboard",managekeyboard.popup,None),
        (keyboard.K_SIX,"Print a receipt",receiptprint,None),
        (keyboard.K_SEVEN,"Users",user.usersmenu,None),
        (keyboard.K_EIGHT,"Exit / restart",restartmenu,None),
        (keyboard.K_NINE,"Display till software versions",versioninfo,None),
        ]
    ui.keymenu(menu,"Management options")
