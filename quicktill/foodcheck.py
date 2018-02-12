from . import ui, foodorder, keyboard, tillconfig

class page(ui.basicpage):
    def __init__(self, hotkeys, user=None):
        ui.basicpage.__init__(self)
        self.user = user
        self.dl = [ui.lrline("Orders")]
        self.s = ui.scrollable(1, 0, self.w, self.h-3, self.dl,
                               show_cursor=False)
        self.addstr(self.h-1, 0, "Ctrl+X = Clear; Ctrl+Y = Cancel")
        self.addstr(self.h-2, 0, "Press O to check the menu.  Press C to "
                    "commit the menu.  Press Q to quit.")
        self.hotkeys = hotkeys
        self.s.focus()
    def pagename(self):
        return "Menu Check"
    def receive_order(self, lines):
        for dept, text, items, amount in lines:
            self.dl.append(ui.lrline("{}: {}".format(dept, text),
                                     tillconfig.fc(items * amount)))
        self.s.redraw()
        return True
    def ordernumber(self):
        return 1234
    def keypress(self,k):
        if k in self.hotkeys:
            return self.hotkeys[k]()
        elif k == 'c' or k == 'C':
            tillconfig.mainloop.shutdown(0)
        elif k == 'q' or k == 'Q':
            tillconfig.mainloop.shutdown(1)
        elif k == 'o' or k == 'O' or k == keyboard.K_CASH:
            foodorder.popup(self.receive_order, self.ordernumber)
        else:
            ui.beep()
