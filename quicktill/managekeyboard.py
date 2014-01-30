from __future__ import unicode_literals
from . import keyboard,ui,td,user
from .models import KeyCap

class popup(user.permission_checked,ui.dismisspopup):
    """
    This popup window enables the keycaps of line keys to be edited.

    """
    permission_required=('edit-keycaps',
                         'Change the names of keys on the keyboard')
    def __init__(self):
        ui.dismisspopup.__init__(self,8,60,title="Edit Keycaps",
                                 colour=ui.colour_input)
        self.addstr(
            2,2,"Press a line key; alter the legend and press Cash/Enter.")
        self.addstr(4,2,"Keycode:")
        self.addstr(5,2," Legend:")
        self.keycode=None
        self.kcfield=ui.editfield(5,11,46,keymap={
                keyboard.K_CASH: (self.setcap,None)})
        self.kcfield.focus()
    def selectline(self,linekey):
        self.addstr(4,11," "*20)
        self.addstr(4,11,linekey.name)
        self.kcfield.set(linekey.keycap)
        self.keycode=linekey
    def setcap(self):
        if self.keycode is None: return
        if self.kcfield.f=="": return
        newcap=KeyCap(keycode=self.keycode.name,
                      keycap=self.kcfield.f)
        td.s.merge(newcap)
        td.s.flush()
    def keypress(self,k):
        if hasattr(k,'line'):
            self.selectline(k)
        else:
            ui.dismisspopup.keypress(self,k)
