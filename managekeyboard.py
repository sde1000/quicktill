import keyboard,ui

class popup(ui.basicpopup):
    def __init__(self):
        ui.basicpopup.__init__(self,7,50,title="Keyboard Check",
                               cleartext="Press Cash/Enter to continue",
                               colour=ui.colour_info)
        self.win=self.pan.window()
        self.win.addstr(2,2,"Press a key.")
        self.win.addstr(4,2,"Keycode:")
        self.win.addstr(5,2," Legend:")
        self.win.move(4,11)
    def keypress(self,k):
        self.win.addstr(4,11,"%d"%k)
        self.win.addstr(5,11," "*20)
        self.win.addstr(5,11,ui.kb.keycap(k))
        if k==keyboard.K_CASH:
            self.dismiss()
