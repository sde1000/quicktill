import keyboard,ui,td,tillconfig

# User interface for checking and editing the keyboard.  This really
# only supports modification of keycaps of line keys; binding of keys
# to stock lines is done from the stock lines management menu.

class popup(ui.basicpopup):
    """This popup window enables keycaps to be edited, as long as the keycode
    is in keyboard.lines."""
    def __init__(self):
        ui.basicpopup.__init__(self,8,60,title="Edit Keycaps",
                               cleartext="Press Clear to dismiss",
                               colour=ui.colour_input)
        self.win=self.pan.window()
        self.win.addstr(2,2,"Press a line key; alter the legend and press Cash/Enter.")
        self.win.addstr(4,2,"Keycode:")
        self.win.addstr(5,2," Legend:")
        self.keycode=None
        km={}
        for i in keyboard.lines:
            km[i]=(self.selectline,(i,),False)
        km[keyboard.K_CASH]=(self.setcap,None,False)
        km[keyboard.K_CLEAR]=(self.dismiss,None,False)
        self.kcfield=ui.editfield(self.win,5,11,46,keymap=km)
        self.kcfield.focus()
    def selectline(self,line):
        self.win.addstr(4,11," "*20)
        self.win.addstr(4,11,"%s"%keyboard.kcnames[line])
        self.kcfield.set(ui.kb.keycap(line))
        self.keycode=line
    def setcap(self):
        if self.keycode is None: return
        if self.kcfield.f=="": return
        td.keyboard_setcap(tillconfig.kbtype,keyboard.kcnames[self.keycode],
                           self.kcfield.f)
        ui.kb.setkeycap(self.keycode,self.kcfield.f)
