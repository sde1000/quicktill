from __future__ import unicode_literals
from . import ui,version,printer,foodorder
import logging
log=logging.getLogger(__name__)

class lockpage(ui.basicpage):
    def __init__(self):
        ui.basicpage.__init__(self)
        self.addstr(1,1,"This till is locked.")
        self.updateheader()
        self._y=3
        unsaved=[p for p in ui.basicpage._pagelist if p!=self]
        if unsaved:
            self.line("The following users have unsaved work "
                      "on this terminal:")
            for p in unsaved:
                self.line("  {} ({})".format(p.pagename(),p.unsaved_data))
            self.line("")
        rpproblem=printer.driver.offline()
        if rpproblem:
            self.line("Receipt printer problem: {}".format(rpproblem))
            log.info("Receipt printer problem: %s",rpproblem)
        kpproblem=foodorder.kitchenprinter.offline()
        if kpproblem:
            self.line("Kitchen printer problem: {}".format(kpproblem))
            log.info("Kitchen printer problem: %s",kpproblem)
        self.addstr(self.h-1,0,"Till version: {}".format(version.version))
        self.win.move(0,0)
    def line(self,s):
        self.addstr(self._y,1,s)
        self._y=self._y+1
    def pagename(self):
        return "Lock"
    def deselect(self):
        # This page ceases to exist when it disappears.
        ui.basicpage.deselect(self)
        self.dismiss()
