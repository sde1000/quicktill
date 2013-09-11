from . import keyboard,ui,td,tillconfig
from .models import KeyCap

# User interface for checking and editing the keyboard.  This really
# only supports modification of keycaps of line keys; binding of keys
# to stock lines is done from the stock lines management menu.

class popup(ui.dismisspopup):
    """This popup window enables keycaps to be edited, as long as the keycode
    is in keyboard.lines."""
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
    def selectline(self,line):
        self.addstr(4,11," "*20)
        self.addstr(4,11,"%s"%keyboard.kcnames[line])
        self.kcfield.set(ui.kb.keycap(line))
        self.keycode=line
    def setcap(self):
        if self.keycode is None: return
        if self.kcfield.f=="": return
        newcap=KeyCap(layout=tillconfig.kbtype,
                      keycode=keyboard.kcnames[self.keycode],
                      keycap=self.kcfield.f)
        td.s.merge(newcap)
        td.s.flush()
        ui.kb.setkeycap(self.keycode,self.kcfield.f)
    def keypress(self,k):
        if k in keyboard.lines:
            self.selectline(k)
        else:
            ui.dismisspopup.keypress(self,k)
