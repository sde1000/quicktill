import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib
import sys
from . import listen
from . import tillconfig

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
        self.current_css_class = None
        ctx = self.get_style_context()
        if key.width > 1 or key.height > 1:
            ctx.add_class("key{}x{}".format(key.width, key.height))
        if hasattr(key.keycode, "line"):
            ctx.add_class("linekey")
        self.update_class()

    def update_text(self):
        self._lw.set_text(str(self.key.keycode))

    def update_class(self):
        ctx = self.get_style_context()
        desired_class = self.key.css_class or "no_key_class"
        if desired_class != self.current_css_class:
            if self.current_css_class:
                ctx.remove_class(self.current_css_class)
                self.current_css_class = None
        if desired_class:
            self.current_css_class = desired_class
            ctx.add_class(desired_class)

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
        self._buttons = {} # keycode -> button
        for loc, key in kb.items():
            row, col = loc
            button = kbutton(key, input_handler)
            if hasattr(key.keycode, 'name'):
                self._buttons[key.keycode.name] = button
            self.attach(button, col, row, key.width, key.height)
        listen.listener.listen_for('keycaps', self.keycap_updated)

    def keycap_updated(self, keycap):
        if keycap in self._buttons:
            self._buttons[keycap].update_text()
            self._buttons[keycap].update_class()

class kbwindow(Gtk.Window):
    """A window with an on-screen keyboard
    """
    def __init__(self, kb, input_handler):
        super().__init__(title="Quicktill keyboard")
        self.add(kbgrid(kb, input_handler))
        self.set_default_size(1200, 200)
        self.show_all()

def _add_css(css, priority):
    style_provider = Gtk.CssProvider()
    style_provider.load_from_data(css.encode("utf-8"))

    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        style_provider,
        priority)

def init_css():
    _add_css(application_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    if tillconfig.custom_css:
        _add_css(tillconfig.custom_css, Gtk.STYLE_PROVIDER_PRIORITY_USER)

def run_standalone(window):
    init_css()
    window.connect("delete-event", Gtk.main_quit)
    GLib.io_add_watch(sys.stdin, GLib.IO_IN | GLib.IO_ERR | GLib.IO_HUP,
                      Gtk.main_quit)
    Gtk.main()
