import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('PangoCairo', '1.0')
gi.require_foreign('cairo')
from gi.repository import Gtk, Pango, Gdk, PangoCairo
import sys
import os
import subprocess
import cairo
import time
import math
from . import keyboard_gtk
from . import ui
from . import keyboard
from . import tillconfig

import logging
log = logging.getLogger(__name__)

if not hasattr(cairo, 'OPERATOR_DIFFERENCE'):
    # This has been in cairo since 1.10 and is still not in the
    # version of pycairo in Ubuntu 17.10!
    cairo.OPERATOR_DIFFERENCE = 23

colours = {
    "black": (0.0, 0.0, 0.0),
    "red": (0.8, 0.0, 0.0),
    "green": (0.0, 0.8, 0.0),
    "yellow": (0.8, 0.8, 0.0),
    "blue": (0.0, 0.0, 0.8),
    "magenta": (0.8, 0.0, 0.8),
    "cyan": (0.0, 0.8, 0.8),
    "white": (1.0, 1.0, 1.0),
}


class GtkWindow(Gtk.Window):
    def __init__(self, drawing_area, kbgrid=None):
        super().__init__(title="Quicktill")
        if kbgrid:
            self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            self.box.pack_start(drawing_area, True, True, 0)
            self.box.pack_start(kbgrid, False, True, 0)
            self.add(self.box)
        else:
            self.add(drawing_area)
        self.connect("delete-event", _quit)
        self.connect("key_press_event", self._keypress)
        self.show_all()

    keys = {
        '\r': keyboard.K_CASH,
        '\n': keyboard.K_CASH,
        '\x01': keyboard.K_HOME,         # Ctrl-A
        '\x04': keyboard.K_DEL,          # Ctrl-D
        '\x05': keyboard.K_END,          # Ctrl-E
        '\x06': keyboard.K_RIGHT,        # Ctrl-F
        '\x0b': keyboard.K_EOL,          # Ctrl-K
        '\x0f': keyboard.K_QUANTITY,     # Ctrl-O
        '\x10': keyboard.K_PRINT,        # Ctrl-P
        '\x14': keyboard.K_MANAGETRANS,  # Ctrl-T
        '\x18': keyboard.K_CLEAR,        # Ctrl-X
        '\x19': keyboard.K_CANCEL,       # Ctrl-Y
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
        Gdk.KEY_KP_Next: keyboard.K_PAGEDOWN,  # Odd name!
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
            except Exception:
                tillconfig.mainloop._exc_info = sys.exc_info()
        return True  # Don't propagate the event to widgets in the window


class gtk_root(Gtk.DrawingArea):
    """Root window with single-line header
    """
    supports_fullscreen = True

    def __init__(self, monospace_font, font,
                 preferred_height=24, preferred_width=80,
                 minimum_height=14, minimum_width=80, pitch_adjust=0,
                 baseline_adjust=0):
        super().__init__()
        self.monospace = monospace_font
        self.font = font if font else monospace_font
        self._pitch_adjust = pitch_adjust
        self._baseline_adjust = baseline_adjust
        fontmap = PangoCairo.font_map_get_default()
        pangoctx = fontmap.create_context()
        metrics = pangoctx.get_metrics(self.monospace)
        self.fontwidth = metrics.get_approximate_digit_width() // Pango.SCALE
        self.ascent = metrics.get_ascent() // Pango.SCALE
        self.descent = metrics.get_descent() // Pango.SCALE
        self.fontheight = self.ascent + self.descent + self._pitch_adjust

        self._preferred_height = preferred_height
        self._minimum_height = minimum_height
        self._preferred_width = preferred_width
        self._minimum_width = minimum_width
        self._contents = []
        self._ontop = []
        self.left = "Quicktill"
        self.middle = ""
        self._cursor_state = False  # Alternates between shown and not-shown
        self._cursor_location = None
        self._cursor_timeout()

        self.connect("draw", self._redraw)
        self._clockalarm()

    def do_get_preferred_height(self):
        return self._minimum_height * self.fontheight, \
            self._preferred_height * self.fontheight

    def do_get_preferred_width(self):
        return self._minimum_width * self.fontwidth, \
            self._preferred_width * self.fontwidth

    def size(self):
        """Return (height, width) in characters
        """
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        return (height // self.fontheight, width // self.fontwidth)

    def update_header(self, left=None, middle=None):
        if left is not None:
            self.left = left
        if middle is not None:
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
        mh, mw = self.size()  # In characters
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
            monospace_font=self.monospace, font=self.font,
            pitch_adjust=self._pitch_adjust,
            baseline_adjust=self._baseline_adjust)
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
        leftw, lefth = layout.get_pixel_size()
        ctx.move_to(0, -self._baseline_adjust)
        PangoCairo.show_layout(ctx, layout)
        layout.set_text(time.strftime("%a %d %b %Y %H:%M:%S %Z"), -1)
        timew, timeh = layout.get_pixel_size()
        ctx.move_to(width - timew, -self._baseline_adjust)
        PangoCairo.show_layout(ctx, layout)
        layout.set_text(self.middle, -1)
        midw, midh = layout.get_pixel_size()
        ctx.move_to((width - timew + leftw - midw) / 2, -self._baseline_adjust)
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
                 monospace_font=None, font=None, pitch_adjust=0,
                 baseline_adjust=0):
        # y and x are in pixels, height and width are in characters
        self._baseline_adjust = baseline_adjust
        self.monospace = monospace_font
        self.font = font if font else monospace_font
        fontmap = PangoCairo.font_map_get_default()
        pangoctx = fontmap.create_context()
        metrics = pangoctx.get_metrics(self.monospace)
        self.fontwidth = metrics.get_approximate_digit_width() // Pango.SCALE
        self.ascent = metrics.get_ascent() // Pango.SCALE
        self.descent = metrics.get_descent() // Pango.SCALE
        self.pitch_adjust = pitch_adjust
        self.fontheight = self.ascent + self.descent + pitch_adjust
        super().__init__(
            drawable, height * self.fontheight, width * self.fontwidth,
            y, x)
        self.height_chars = height
        self.width_chars = width
        self.cur_y = 0
        self.cur_x = 0
        self.colour = colour
        self._cursor_on = True
        # XXX it should be possible to use a cairo.RecordingSurface
        # here to save memory on surfaces that will be written to on
        # initialisation and which will then be static, but this was
        # introduced in pycairo 1.11.0 and Ubuntu 16.04 to 17.10 only
        # have pycairo-1.10.0.  Ubuntu 18.04 has pycairo-1.16.0 so
        # implement it once all installations have been upgraded!
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
        self._surface.finish()
        del self._surface

    def draw(self, wid, ctx):
        ctx.set_source_surface(self._surface, self.x, self.y)
        ctx.paint()

    def size(self):
        # Size in characters
        return (self.height_chars, self.width_chars)

    def clear(self, y, x, height, width, colour=None):
        """Clear a rectangle to a solid colour
        """
        if not colour:
            colour = self.colour
        ctx = cairo.Context(self._surface)
        ctx.set_source_rgb(*colours[colour.background])
        ctx.rectangle(x * self.fontwidth, y * self.fontheight,
                      width * self.fontwidth, height * self.fontheight)
        ctx.fill()
        self.damage(y * self.fontheight, x * self.fontwidth,
                    height * self.fontheight, width * self.fontwidth)

    def addstr(self, y, x, text, colour=None):
        """Clear the background and draw monospace text
        """
        if not colour:
            colour = self.colour
        ctx = cairo.Context(self._surface)
        # Draw the background
        ctx.set_source_rgb(*colours[colour.background])
        ctx.rectangle(x * self.fontwidth, y * self.fontheight,
                      len(text) * self.fontwidth, self.fontheight)
        ctx.fill()
        self.damage(y * self.fontheight, x * self.fontwidth,
                    self.fontheight, len(text) * self.fontwidth)
        self.move(y, x + len(text))
        # Optimisation: if we are just drawing spaces to fill an area,
        # don't bother actually rendering the text!
        if text == ' ' * len(text):
            return
        layout = PangoCairo.create_layout(ctx)
        layout.set_text(text, -1)
        layout.set_font_description(self.monospace)
        ctx.set_source_rgb(*colours[colour.foreground])
        ctx.move_to(x * self.fontwidth,
                    y * self.fontheight - self._baseline_adjust)
        PangoCairo.show_layout(ctx, layout)

    def wrapstr(self, y, x, width, s, colour=None, display=True):
        """Display a string wrapped to specified width.

        Returns the number of lines that the string was wrapped over.

        Does not clear the background.
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
        lines = math.ceil(height / (self.fontheight - self.pitch_adjust))
        if display:
            ctx.move_to(x * self.fontwidth, y * self.fontheight)
            PangoCairo.show_layout(ctx, layout)
            self.damage(y * self.fontheight, x * self.fontwidth,
                        height, width)
        return lines

    def drawstr(self, y, x, width, s, colour=None, align="<", display=True):
        """Display a string.

        Align may be '<', '^' or '>', as for format specs.  If the
        string does not fit in the specified space, it will be clipped
        to that space and the method will return False; otherwise the
        method will return True.

        Does not clear the background.
        """
        if not colour:
            colour = self.colour
        ctx = cairo.Context(self._surface)
        ctx.set_source_rgb(*colours[colour.foreground])
        layout = PangoCairo.create_layout(ctx)
        layout.set_text(s, -1)
        layout.set_font_description(self.font)
        lwidth, lheight = layout.get_pixel_size()
        if display:
            # XXX maybe add some height at top and bottom for ascenders and
            # descenders - only really want to clip left and right!
            ctx.rectangle(x * self.fontwidth, y * self.fontheight,
                          width * self.fontwidth, lheight)
            ctx.clip()
            if align == '<':
                left = x * self.fontwidth
            elif align == '^':
                left = (x + width / 2) * self.fontwidth - (lwidth / 2)
            else:
                left = (x + width) * self.fontwidth - lwidth
            ctx.move_to(left, y * self.fontheight)
            PangoCairo.show_layout(ctx, layout)
            self.damage(y * self.fontheight, left,
                        lheight, lwidth)
        return lwidth > width * self.fontwidth

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
            self.bordertext(title, "U<")
        if clear:
            self.bordertext(clear, "L>")
        self.damage(0, 0, self.height, self.width)

    def bordertext(self, text, location, colour=None):
        """Draw text in the border

        location should be two characters; U or L as the first
        character to indicate upper or lower; <, ^ or > as the second
        character to indicate alignment.
        """
        ctx = cairo.Context(self._surface)
        layout = PangoCairo.create_layout(ctx)
        layout.set_text(text, -1)
        layout.set_font_description(self.font)
        width, height = layout.get_pixel_size()
        y = 0 if location[0] == "U" else (self.height - self.fontheight)
        if location[1] == "<":
            x = self.fontwidth + 4
        elif location[1] == "^":
            x = (self.width - width) / 2
        else:
            x = self.width - self.fontwidth - width - 4
        if colour is None:
            colour = self.colour
        ctx.set_source_rgb(*colours[colour.background])
        ctx.rectangle(x, y, width, self.fontheight)
        ctx.fill()
        ctx.set_source_rgb(*colours[colour.foreground])
        ctx.move_to(x, y)
        PangoCairo.show_layout(ctx, layout)
        self.damage(y, x, self.fontheight, width)

    def erase(self):
        # Fill with background colour
        ctx = cairo.Context(self._surface)
        ctx.set_source_rgb(*colours[self.colour.background])
        self._rect(ctx, self.fontwidth, 0, self.width, 0, self.height)
        ctx.fill()
        self.damage(0, 0, self.height, self.width)


def _quit(widget, event):
    tillconfig.mainloop.shutdown(0)


def _onscreen_keyboard_input(keycode):
    try:
        ui.handle_raw_keyboard_input(keycode)
    except Exception:
        tillconfig.mainloop._exc_info = sys.exc_info()


def _x_unblank_screen():
    r = subprocess.run(["/usr/bin/xset", "s", "reset"])
    if r.returncode != 0:
        log.error("_x_unblank_screen: xset returned %s", r.returncode)


def run(fullscreen=False, font="sans 20", monospace_font="monospace 20",
        keyboard=False, geometry=None, pitch_adjust=0, baseline_adjust=0,
        hide_pointer=False):
    """Start running with the GTK display system
    """
    if os.getenv('DISPLAY'):
        log.info("Running on X: using _x_unblank_screen")
        ui.unblank_screen = _x_unblank_screen

    monospace_font = Pango.FontDescription(monospace_font)
    font = Pango.FontDescription(font)
    ui.rootwin = gtk_root(monospace_font, font,
                          preferred_height=20 if keyboard else 24,
                          minimum_width=60, pitch_adjust=pitch_adjust,
                          baseline_adjust=baseline_adjust)
    ui.beep = Gdk.beep
    if keyboard and tillconfig.keyboard:
        keyboard_gtk.init_css()
        kbgrid = keyboard_gtk.kbgrid(
            tillconfig.keyboard, _onscreen_keyboard_input)
        wincontents = Gtk.Box(spacing=1,
                              orientation=Gtk.Orientation.VERTICAL)
        wincontents.pack_start(ui.rootwin, True, True, 0)
        wincontents.pack_end(kbgrid, True, True, 0)
        if tillconfig.keyboard_right:
            rhgrid = keyboard_gtk.kbgrid(
                tillconfig.keyboard_right, _onscreen_keyboard_input)
            split = 4  # maybe make this configurable?
            # Use a Grid to get a consistent split
            newbox = Gtk.Grid()
            newbox.attach(wincontents, 0, 0, split, 1)
            newbox.attach(rhgrid, split, 0, 1, 1)
            newbox.set_column_homogeneous(True)
            newbox.set_row_homogeneous(True)
            wincontents = newbox
    else:
        wincontents = ui.rootwin
    window = GtkWindow(wincontents)
    if geometry:
        window.resize(*geometry)
    if fullscreen:
        window.fullscreen()
    ui.toaster.notify_display_initialised()

    if hide_pointer:
        blank_cursor = Gdk.Cursor(Gdk.CursorType.BLANK_CURSOR)
        window.get_window().set_cursor(blank_cursor)

    for i in ui.run_after_init:
        i()
    while tillconfig.mainloop.exit_code is None:
        ui.basicpage._ensure_page_exists()
        tillconfig.mainloop.iterate()
