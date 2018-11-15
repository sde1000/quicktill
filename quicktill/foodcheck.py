from . import ui
from . import keyboard
from . import tillconfig
from . import cmdline
from . import event
from . import user
from . import ui_ncurses

import logging
log = logging.getLogger(__name__)

class page(ui.basicpage):
    def __init__(self, *args, commitcode=0, quitcode=1, menuurl=None, **kwargs):
        super().__init__()
        self._commitcode = commitcode
        self._quitcode = quitcode
        self._menuurl = menuurl
        self.user = user.built_in_user(
            "Test Menu File",
            "Test",
            ["kitchen-order"])
        self.dl = [ui.lrline("Orders")]
        prompt = ("Ctrl+X = Clear; Ctrl+Y = Cancel.  "
                  "Press O to check the menu.  Press C to commit the menu.  "
                  "Press Q to quit.")
        promptheight = self.win.wrapstr(0, 0, self.w, prompt, display=False)
        self.win.wrapstr(self.h - promptheight, 0, self.w, prompt)
        self.s = ui.scrollable(1, 0, self.w, self.h - promptheight - 1, self.dl,
                               show_cursor=False)
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

    def keypress(self, k):
        if k == 'c' or k == 'C':
            tillconfig.mainloop.shutdown(self._commitcode)
        elif k == 'q' or k == 'Q':
            tillconfig.mainloop.shutdown(self._quitcode)
        elif k == 'o' or k == 'O' or k == keyboard.K_CASH:
            from . import foodorder
            foodorder.kitchenprinters = []
            foodorder.popup(self.receive_order, None, self._menuurl,
                            ordernumberfunc=self.ordernumber)
        else:
            ui.beep()

class testmenu(cmdline.command):
    help = "test a menu file"
    database_required = False

    @staticmethod
    def add_arguments(parser):
        parser.add_argument("url", help="URL of menu file to test")
        parser.add_argument("--commit-exit-code",
                            type=int, default=0, dest="commitcode",
                            help="exit code when menu commit is requested")
        parser.add_argument("--quit-exit-code",
                            type=int, default=1, dest="quitcode",
                            help="exit code when menu commit is not requested")

    @staticmethod
    def run(args):
        tillconfig.mainloop = event.SelectorsMainLoop()
        tillconfig.firstpage = lambda: page(commitcode=args.commitcode,
                                            quitcode=args.quitcode,
                                            menuurl=args.url)
        try:
            ui_ncurses.run()
        except:
            log.exception("Exception caught at top level running foodcheck")

        return tillconfig.mainloop.exit_code
