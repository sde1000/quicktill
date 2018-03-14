import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gtk, Pango, GLib, Gdk, PangoCairo
import sys
import cairo
import time
import math
import textwrap

if not hasattr(cairo, 'OPERATOR_DIFFERENCE'):
    # This has been in cairo since 1.10 and is still not in the
    # version of pycairo in Ubuntu 17.10!
    cairo.OPERATOR_DIFFERENCE = 23

from . import ui
from . import keyboard
from . import tillconfig

import logging
log = logging.getLogger(__name__)

colours = {
    "black": (0.0, 0.0, 0.0),
    "red": (1.0, 0.0, 0.0),
    "green": (0.0, 1.0, 0.0),
    "yellow": (1.0, 1.0, 0.0),
    "blue": (0.0, 0.0, 1.0),
    "magenta": (1.0, 0.0, 1.0),
    "cyan": (0.0, 1.0, 1.0),
    "white": (1.0, 1.0, 1.0),
}

class GtkWindow(Gtk.Window):
    def __init__(self, drawing_area):
        super(GtkWindow, self).__init__(title="Quicktill")
        self.add(drawing_area)
        self.connect("delete-event", _quit)
        self.connect("key_press_event", self._keypress)
        self.show_all()

    keys = {
        '\r': keyboard.K_CASH,
        '\n': keyboard.K_CASH,
        '\x01': keyboard.K_HOME,        # Ctrl-A
        '\x04': keyboard.K_DEL,         # Ctrl-D
        '\x05': keyboard.K_END,         # Ctrl-E
        '\x06': keyboard.K_RIGHT,       # Ctrl-F
        '\x0b': keyboard.K_EOL,         # Ctrl-K
        '\x0f': keyboard.K_QUANTITY,    # Ctrl-O
        '\x10': keyboard.K_PRINT,       # Ctrl-P
        '\x14': keyboard.K_MANAGETRANS, # Ctrl-T
        '\x18': keyboard.K_CLEAR,       # Ctrl-X
        '\x19': keyboard.K_CANCEL,      # Ctrl-Y
        Gdk.KEY_Left: keyboard.K_LEFT,
        Gdk.KEY_Right: keyboard.K_RIGHT,
        Gdk.KEY_Up: keyboard.K_UP,
        Gdk.KEY_Down: keyboard.K_DOWN,
        Gdk.KEY_KP_Left: keyboard.K_LEFT,
        Gdk.KEY_KP_Right: keyboard.K_RIGHT,
        Gdk.KEY_KP_Up: keyboard.K_UP,
        Gdk.KEY_KP_Down: keyboard.K_DOWN,
        Gdk.KEY_BackSpace: keyboard.K_BACKSPACE,
        Gdk.KEY_Delete: keyboard.K_DEL,
        Gdk.KEY_KP_Delete: keyboard.K_DEL,
        Gdk.KEY_Page_Up: keyboard.K_PAGEUP,
        Gdk.KEY_Page_Down: keyboard.K_PAGEDOWN,
        Gdk.KEY_KP_Page_Up: keyboard.K_PAGEUP,
        Gdk.KEY_KP_Next: keyboard.K_PAGEDOWN, # Odd name!
        Gdk.KEY_Tab: keyboard.K_TAB,
        Gdk.KEY_Home: keyboard.K_HOME,
        Gdk.KEY_End: keyboard.K_END,
    }
    def _keypress(self, widget, event):
        k = None
        log.debug("Gtk keypress %s", Gdk.keyval_name(event.keyval))
        if event.keyval in self.keys:
            k = self.keys[event.keyval]
        elif event.string:
            if event.string in self.keys:
                k = self.keys[event.string]
            elif event.string.isprintable():
                k = event.string
        if k:
            # This may raise an exception, which would be ignored if
            # we returned normally from this callback function.  If we
            # get an exception, cache it in the main loop so it's
            # picked up on exit from iterate().  The main loop is
            # guaranteed to be the GLib one when Gtk is in use.
            try:
                ui.handle_raw_keyboard_input(k)
            except Exception as e:
                tillconfig.mainloop._exc_info = sys.exc_info()

class gtk_root(Gtk.DrawingArea):
    """Root window with single-line header
    """
    supports_fullscreen = True

    def __init__(self, monospace_font, font, min_height=24, min_width=80):
        super().__init__()
        self.monospace = monospace_font
        self.font = font if font else monospace_font
        fontmap = PangoCairo.font_map_get_default()
        pangoctx = fontmap.create_context()
        metrics = pangoctx.get_metrics(self.monospace)
        self.fontwidth = metrics.get_approximate_digit_width() // Pango.SCALE
        self.ascent = metrics.get_ascent() // Pango.SCALE
        self.descent = metrics.get_descent() // Pango.SCALE
        self.fontheight = self.ascent + self.descent

        self._contents = []
        self._ontop = []
        self.left = "Quicktill"
        self.middle = ""
        self._cursor_state = False # Alternates between shown and not-shown
        self._cursor_location = None
        self._cursor_timeout()

        # Set the minimum size
        self.set_size_request(min_width * self.fontwidth,
                              min_height * self.fontheight)

        self.connect("draw", self._redraw)
        self._clockalarm()

    def size(self):
        """Return (height, width) in characters
        """
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        return (height // self.fontheight, width // self.fontwidth)

    def update_header(self, left, middle):
        self.left = left
        self.middle = middle
        width = self.get_allocated_width()
        self.damage(0, 0, self.fontheight, width)

    def _clockalarm(self):
        width = self.get_allocated_width()
        self.damage(0, 0, self.fontheight, width)
        now = time.time()
        nexttime = math.ceil(now) + 0.01
        tillconfig.mainloop.add_timeout(nexttime - now, self._clockalarm,
                                        "clock")

    def new(self, height, width, y, x, colour=ui.colour_default,
            always_on_top=False):
        """Create a child text window
        """
        mh, mw = self.size() # In characters
        pw = self.get_allocated_width()
        ph = self.get_allocated_height()
        if height == "max":
            height = mh
        if height == "page":
            height = mh - 1
        if width == "max":
            width = mw
        if y == "center":
            y = (ph - (height * self.fontheight)) // 2
        elif y == "page":
            y = self.fontheight
        else:
            y = y * self.fontheight
        if x == "center":
            x = (pw - (width * self.fontwidth)) // 2
        else:
            x = x * self.fontwidth
        new = text_window(
            self, height, width, y, x, colour,
            monospace_font=self.monospace, font=self.font)
        if always_on_top:
            self._ontop.append(new)
        else:
            self._contents.append(new)
        return new

    def _remove(self, window):
        if window in self._contents:
            self._contents.remove(window)
        if window in self._ontop:
            self._ontop.remove(window)

    def isendwin(self):
        return False

    def flush(self):
        pass

    def set_fullscreen(self, fullscreen):
        window = self.get_toplevel()
        if fullscreen:
            window.fullscreen()
        else:
            window.unfullscreen()
        return True

    def _redraw(self, wid, ctx):
        # The window background is black
        ctx.save()
        ctx.set_source_rgb(0.0, 0.0, 0.0)
        ctx.paint()
        ctx.restore()
        # Draw the header line
        width = self.get_allocated_width()
        ctx.save()
        ctx.set_source_rgb(*colours[ui.colour_header.background])
        ctx.rectangle(0, 0, width, self.fontheight)
        ctx.fill()
        ctx.set_source_rgb(*colours[ui.colour_header.foreground])
        layout = PangoCairo.create_layout(ctx)
        layout.set_font_description(self.font)
        layout.set_text(self.left, -1)
        ctx.move_to(0, 0)
        PangoCairo.show_layout(ctx, layout)
        layout.set_text(self.middle, -1)
        midw, midh = layout.get_pixel_size()
        ctx.move_to((width - midw) / 2, 0)
        PangoCairo.show_layout(ctx, layout)
        layout.set_text(time.strftime("%a %d %b %Y %H:%M:%S %Z"), -1)
        timew, timeh = layout.get_pixel_size()
        ctx.move_to(width - timew, 0)
        PangoCairo.show_layout(ctx, layout)
        ctx.restore()

        for w in self._contents + self._ontop:
            ctx.save()
            w.draw(wid, ctx)
            ctx.restore()
        if self._contents:
            cursor = self._contents[-1].cursor_location
            self._cursor_location = cursor
            if cursor and self._cursor_state:
                self._cursor_drawn = cursor
                ctx.set_operator(cairo.OPERATOR_DIFFERENCE)
                ctx.set_source_rgb(1.0, 1.0, 1.0)
                y, x, height, width = cursor
                ctx.rectangle(x, y, width, height)
                ctx.fill()

    def damage(self, y, x, height, width):
        self.queue_draw_area(x, y, width, height)

    def _cursor_timeout(self):
        tillconfig.mainloop.add_timeout(0.5, self._cursor_timeout, "cursor")
        if self._cursor_location:
            self.damage(*self._cursor_location)
        self._cursor_state = not self._cursor_state

class window_stack:
    def __init__(self, stack, drawable):
        self._stack = stack
        self._drawable = drawable

    def restore(self):
        self._drawable._contents += self._stack
        for i in self._stack:
            self._drawable.damage(i.y, i.x, i.height, i.width)

class window:
    """A rectangular area of the display

    Windows exist in a stack; each window is responsible for drawing
    itself and the windows stacked on top of it.

    There is also a list of "always on top" windows that are drawn
    after the main window stack, and which are only responsible for
    drawing themselves.
    """
    def __init__(self, drawable, height, width, y, x):
        self._drawable = drawable
        # These are in pixels
        self.y = y
        self.x = x
        self.height = height
        self.width = width

    def save_stack(self):
        # Hide this window and all windows on top of it and return
        # an object that can be used to restore them
        i = self._drawable._contents.index(self)
        stack = self._drawable._contents[i:]
        self._drawable._contents = self._drawable._contents[:i]
        for i in stack:
            self._drawable.damage(i.y, i.x, i.height, i.width)
        return window_stack(stack, self._drawable)

    def damage(self, y, x, height, width):
        # Damage in window-relative coordinates
        self._drawable.damage(self.y + y, self.x + x, height, width)

    def draw(self, wid, ctx):
        return

    @property
    def cursor_location(self):
        return

class text_window(window):
    """A window to draw text in.
    """
    def __init__(self, drawable, height, width, y, x,
                 colour=ui.colour_default,
                 monospace_font=None, font=None):
        # y and x are in pixels, height and width are in characters
        self.monospace = monospace_font
        self.font = font if font else monospace_font
        fontmap = PangoCairo.font_map_get_default()
        pangoctx = fontmap.create_context()
        metrics = pangoctx.get_metrics(self.monospace)
        self.fontwidth = metrics.get_approximate_digit_width() // Pango.SCALE
        self.ascent = metrics.get_ascent() // Pango.SCALE
        self.descent = metrics.get_descent() // Pango.SCALE
        self.fontheight = self.ascent + self.descent
        super(text_window, self).__init__(
            drawable, height * self.fontheight, width * self.fontwidth,
            y, x)
        self.height_chars = height
        self.width_chars = width
        self.cur_y = 0
        self.cur_x = 0
        self.colour = colour
        self._cursor_on = True
        self._surface = cairo.ImageSurface(
            cairo.FORMAT_ARGB32, self.width, self.height)
        self.erase()

    @property
    def cursor_location(self):
        # Return desired cursor location in GtkWindow coordinates
        if not self._cursor_on:
            return
        return (self.y + self.cur_y * self.fontheight,
                self.x + self.cur_x * self.fontwidth,
                self.fontheight,
                self.fontwidth)

    def set_cursor(self, state):
        if self._cursor_on and not state:
            self._drawable.damage(*self.cursor_location)
        self._cursor_on = state

    def destroy(self):
        self.damage(0, 0, self.height, self.width)
        self._drawable._remove(self)
        del self._surface

    def draw(self, wid, ctx):
        ctx.set_source_surface(self._surface, self.x, self.y)
        ctx.paint()

    def size(self):
        # Size in characters
        return (self.height_chars, self.width_chars)

    def addstr(self, y, x, text, colour=None):
        if not colour:
            colour = self.colour
        ctx = cairo.Context(self._surface)
        # Draw the background
        ctx.set_source_rgb(*colours[colour.background])
        ctx.rectangle(x * self.fontwidth, y * self.fontheight,
                      len(text) * self.fontwidth, self.fontheight)
        ctx.fill()
        layout = PangoCairo.create_layout(ctx)
        layout.set_text(text, -1)
        layout.set_font_description(self.monospace)
        ctx.set_source_rgb(*colours[colour.foreground])
        ctx.move_to(x * self.fontwidth, y * self.fontheight)
        PangoCairo.show_layout(ctx, layout)
        self.damage(y * self.fontheight, x * self.fontwidth,
                    self.fontheight, len(text) * self.fontwidth)
        self.move(y, x + len(text))

    def wrapstr(self, y, x, width, s, colour=None, display=True):
        """Display a string wrapped to specified width.

        Returns the number of lines that the string was wrapped over.
        """
        if not colour:
            colour = self.colour
        ctx = cairo.Context(self._surface)
        ctx.set_source_rgb(*colours[colour.foreground])
        layout = PangoCairo.create_layout(ctx)
        layout.set_text(s, -1)
        layout.set_font_description(self.font)
        layout.set_width(width * self.fontwidth * Pango.SCALE)
        width, height = layout.get_pixel_size()
        lines = height // self.fontheight
        if display:
            ctx.move_to(x * self.fontwidth, y * self.fontheight)
            PangoCairo.show_layout(ctx, layout)
            self.damage(y * self.fontheight, x * self.fontwidth,
                        height, width)
        return lines

    def flush(self):
        pass

    def move(self, y, x):
        if self._cursor_on and (y != self.cur_y or x != self.cur_x):
            self._drawable.damage(*self.cursor_location)
        self.cur_y = y
        self.cur_x = x

    def getyx(self):
        return (self.cur_y, self.cur_x)

    def _rect(self, ctx, radius, x1, x2, y1, y2):
        pi2 = math.pi / 2
        ctx.arc(x1 + radius, y1 + radius, radius, 2 * pi2, 3 * pi2)
        ctx.arc(x2 - radius, y1 + radius, radius, 3 * pi2, 4 * pi2)
        ctx.arc(x2 - radius, y2 - radius, radius, 0 * pi2, 1 * pi2)
        ctx.arc(x1 + radius, y2 - radius, radius, 1 * pi2, 2 * pi2)
        ctx.close_path()

    def border(self, title=None, clear=None):
        x1 = self.fontwidth / 2
        y1 = self.fontheight / 2
        x2 = x1 + (self.width_chars - 1) * self.fontwidth
        y2 = y1 + (self.height_chars - 1) * self.fontheight
        ctx = cairo.Context(self._surface)
        ctx.set_source_rgb(*colours[self.colour.foreground])
        self._rect(ctx, self.fontwidth, x1, x2, y1, y2)
        ctx.stroke()
        if title:
            layout = PangoCairo.create_layout(ctx)
            layout.set_text(title, -1)
            layout.set_font_description(self.font)
            width, height = layout.get_pixel_size()
            ctx.set_source_rgb(*colours[self.colour.background])
            x = self.fontwidth + 4
            ctx.rectangle(x, 0, width, self.fontheight)
            ctx.fill()
            ctx.set_source_rgb(*colours[self.colour.foreground])
            ctx.move_to(x, 0)
            PangoCairo.show_layout(ctx, layout)
        if clear:
            layout = PangoCairo.create_layout(ctx)
            layout.set_text(clear, -1)
            layout.set_font_description(self.font)
            width, height = layout.get_pixel_size()
            ctx.set_source_rgb(*colours[self.colour.background])
            x = self.width - self.fontwidth - width - 4
            y = self.height - self.fontheight
            ctx.rectangle(x, y, width, self.fontheight)
            ctx.fill()
            ctx.set_source_rgb(*colours[self.colour.foreground])
            ctx.move_to(x, y)
            PangoCairo.show_layout(ctx, layout)
        self.damage(0, 0, self.height, self.width)

    def erase(self):
        # Fill with background colour
        ctx = cairo.Context(self._surface)
        ctx.set_source_rgb(*colours[self.colour.background])
        self._rect(ctx, self.fontwidth, 0, self.width, 0, self.height)
        ctx.fill()
        self.damage(0, 0, self.height, self.width)

def _quit(widget, event):
    tillconfig.mainloop.shutdown(0)

def run(fullscreen=False, font="sans 20", monospace_font="monospace 20"):
    """Start running with the GTK display system
    """
    monospace_font = Pango.FontDescription(monospace_font)
    font = Pango.FontDescription(font)
    ui.rootwin = gtk_root(monospace_font, font, 24, 80)
    ui.beep = Gdk.beep
    window = GtkWindow(ui.rootwin)
    if fullscreen:
        window.fullscreen()
    ui.toaster.notify_display_initialised()
    for i in ui.run_after_init:
        i()
    while tillconfig.mainloop.exit_code is None:
        ui.basicpage._ensure_page_exists()
        tillconfig.mainloop.iterate()
