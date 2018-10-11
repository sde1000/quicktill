import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib
import sys

application_css = """
window {
  background-color: black;
}

button, button:backdrop {
  background-image: none;
  margin: 0px;
  border-image: none;
  border-color: rgba(50%, 50%, 50%, 0.5);
  border-radius: 6px;
}

button {
  font-family: sans;
  font-size: 12px;
  color: black;
}

.no_key_class {
  background-color: rgb(200, 200, 200);
  color: black;
}

button:active {
  background-color: white;
  color: black;
}

button.key2x2 {
  font-size: 18px;
  font-weight: bold;
}

button.key2x1 {
  font-size: 18px;
}

.payment {
  background-color: yellow;
}

.management {
  background-color: green;
  color: white;
}

.register {
  background-color: rgb(0, 255, 0);
  color: black;
}

.usertoken {
  background-color: yellow;
}

.clear {
  background-color: red;
  color: white;
}

.lock {
  background-color: red;
  color: white;
  font-weight: bold;
}

.numeric, .cursor {
  background-color: white;
  color: black;
  font-size: 18px;
}

.numeric:active, .cursor:active {
  background-color: black;
  color: white;
}

.kitchen {
  background-color: pink;
}

"""

class kbutton(Gtk.Button):
    """A button on an on-screen keyboard
    """
    def __init__(self, key, input_handler):
        super().__init__()
        self.key = key
        self._lw = Gtk.Label(
            str(key.keycode), justify=Gtk.Justification.CENTER)
        self._lw.set_line_wrap(True)
        self.add(self._lw)
        self.connect("clicked", lambda widget: input_handler(self.key.keycode))
        ctx = self.get_style_context()
        ctx.add_class(key.css_class or "no_key_class")
        if key.width > 1 or key.height > 1:
            ctx.add_class("key{}x{}".format(key.width, key.height))

    def do_get_preferred_width(self):
        # Return minimum width and natural width
        return 20, 20

class kbgrid(Gtk.Grid):
    """A Gtk widget representing an on-screen keyboard
    """
    def __init__(self, kb, input_handler):
        super().__init__()
        self.set_column_homogeneous(True)
        self.set_row_homogeneous(True)
        for loc, key in kb.items():
            row, col = loc
            button = kbutton(key, input_handler)
            self.attach(button, col, row, key.width, key.height)

class kbwindow(Gtk.Window):
    """A window with an on-screen keyboard
    """
    def __init__(self, kb, input_handler):
        super().__init__(title="Quicktill keyboard")
        self.add(kbgrid(kb, input_handler))
        self.set_default_size(1200, 200)
        self.show_all()

def init_css():
        style_provider = Gtk.CssProvider()
        style_provider.load_from_data(application_css.encode("utf-8"))

        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            style_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

def run_standalone(window):
    init_css()
    window.connect("delete-event", Gtk.main_quit)
    GLib.io_add_watch(sys.stdin, GLib.IO_IN | GLib.IO_ERR | GLib.IO_HUP,
                      Gtk.main_quit)
    Gtk.main()
