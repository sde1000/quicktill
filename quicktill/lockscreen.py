from __future__ import unicode_literals
from . import ui

class lockpage(ui.basicpage):
    def __init__(self):
        ui.basicpage.__init__(self)
        self.win.addstr(1,1,"This till is locked.")
        self.updateheader()
        unsaved=[p for p in ui.basicpage._pagelist if p!=self]
        if unsaved:
            self.win.addstr(3,1,"The following users have unsaved work "
                            "on this terminal:")
            y=4
            for p in unsaved:
                self.win.addstr(y,3,p.pagename())
                y=y+1
        self.win.move(0,0)
    def pagename(self):
        return "Lock"
    def deselect(self):
        # This page ceases to exist when it disappears.
        ui.basicpage.deselect(self)
        self.dismiss()
