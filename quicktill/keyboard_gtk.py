import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Pango, GLib
import sys

class kbutton(Gtk.Button):
    """A button on an on-screen keyboard
    """
    def __init__(self, key, font, input_handler):
        super().__init__()
        self.key = key
        self._lw = Gtk.Label(
            str(key.keycode), justify=Gtk.Justification.CENTER)
        self._lw.modify_font(font)
        self._lw.set_line_wrap(True)
        self.add(self._lw)
        self.connect("clicked", lambda widget: input_handler(self.key.keycode))

    def do_get_preferred_width(self):
        # Return minimum width and natural width
        return 20, 20

class kbgrid(Gtk.Grid):
    """A Gtk widget representing an on-screen keyboard
    """
    def __init__(self, kb, font, input_handler):
        super().__init__()
        self.set_column_homogeneous(True)
        self.set_row_homogeneous(True)
        for loc, key in kb.items():
            row, col = loc
            button = kbutton(key, font, input_handler)
            self.attach(button, col, row, key.width, key.height)

class kbwindow(Gtk.Window):
    """A window with an on-screen keyboard
    """
    def __init__(self, kb, font, input_handler):
        super().__init__(title="Quicktill keyboard")
        self.add(kbgrid(kb, font, input_handler))
        self.set_default_size(1200, 200)
        self.show_all()

def get_font(font):
    return Pango.FontDescription(font)

def run_standalone(window):
    window.connect("delete-event", Gtk.main_quit)
    GLib.io_add_watch(sys.stdin, GLib.IO_IN | GLib.IO_ERR | GLib.IO_HUP,
                      Gtk.main_quit)
    Gtk.main()
