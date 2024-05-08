import socket
import tempfile
import io
import textwrap
import subprocess
import fcntl
import array
import sys
import cups
import glob
try:
    import qrcode
    _qrcode_supported = True
except ImportError:
    _qrcode_supported = False
import imagesize

from reportlab.pdfgen import canvas
from reportlab.lib.units import toLength
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Flowable
from reportlab.platypus import Frame
from reportlab.platypus import BaseDocTemplate
from reportlab.platypus import PageTemplate

import logging
log = logging.getLogger(__name__)


class PrinterConfigurationError(Exception):
    def __init__(self, desc):
        self.desc = desc

    def __str__(self):
        return f"PrinterConfigurationError('{self.desc}')"


class PrinterError(Exception):
    def __init__(self, printer, desc):
        self.printer = printer
        self.desc = desc

    def __str__(self):
        return f"PrinterError({self.printer}, '{self.desc}')"


def test_ping(host):
    """Check whether a host is alive using ping; returns True if it is alive.
    """
    with open('/dev/null', 'w') as null:
        r = subprocess.call("ping -q -w 2 -c 1 %s" % host,
                            shell=True, stdout=null, stderr=null)
    if r == 0:
        return True
    return False


def _lrwrap(l, r, width):
    w = textwrap.wrap(l, width)
    if len(w) == 0:
        w = [""]
    if len(w[-1]) + len(r) >= width:
        w.append("")
    w[-1] = w[-1] + (' ' * (width - len(w[-1]) - len(r))) + r
    return w


def _wrap(l, width):
    w = textwrap.wrap(l, width)
    if len(w) == 0:
        w = [""]
    return w


class ReceiptElement:
    """The null receipt element

    Outputs as a blank line
    """
    def __str__(self):
        return "(blank line)"


class TextElement(ReceiptElement):
    def __init__(self, left="", center="", right="",
                 colour=None, font=None, emph=None, underline=None):
        self.left = left
        self.center = center
        self.right = right
        if colour is not None:
            self.colour = colour
        if font is not None:
            self.font = font
        if emph is not None:
            self.emph = emph
        if underline is not None:
            self.underline = underline

    def __str__(self):
        return "\t".join((self.left, self.center, self.right))


class QRCodeElement(ReceiptElement):
    def __init__(self, data):
        self.qrcode_data = data

    def __str__(self):
        return "QR code: " + self.qrcode_data


class ImageElement(ReceiptElement):
    def __init__(self, image):
        assert image.startswith(b"P4")  # only B&W PBM format supported
        width, height = imagesize.get(io.BytesIO(image))
        data_lines = [
            line
            for line in image.splitlines()
            if not line.startswith(b"#")
        ]
        assert data_lines[0] == b"P4"
        assert data_lines[1] == f"{width} {height}".encode("ascii")
        self.image_data = bytes().join(data_lines[2:])
        self.image_width = width
        self.image_height = height

    def __str__(self):
        return "Image"


class ReceiptCanvas:
    def __init__(self):
        self.story = []

    def printline(self, l="",
                  colour=None, font=None, emph=None, underline=None):
        s = l.split("\t")
        left = s[0] if len(s) > 0 else ""
        center = s[1] if len(s) > 1 else ""
        right = s[2] if len(s) > 2 else ""
        self.story.append(TextElement(
            left, center, right, colour=colour,
            font=font, emph=emph, underline=underline))

    def printqrcode(self, data):
        self.story.append(QRCodeElement(data))

    def printimage(self, image):
        self.story.append(ImageElement(image))

    def add_story(self, story):
        self.story += story

    def set_story(self, story):
        self.story = story

    def get_story(self):
        return self.story

    def __iter__(self):
        return iter(self.story)


class printer:
    """Base printer class.

    Printing with canvases looks something like this:
    with printer as d:
        d.printline("foo")
        d.printline("bar")
    """
    def __init__(self, driver, description=None):
        self._driver = driver
        self.description = description
        self._canvas = None

    def __enter__(self):
        if self._canvas:
            raise PrinterError(self, "Already started in __enter__()")
        self._canvas = self.get_canvas()
        return self._canvas

    def __exit__(self, type, value, tb):
        try:
            if tb is None:
                self.print_canvas(self._canvas)
        finally:
            self._canvas = None

    def offline(self):
        return

    @property
    def canvastype(self):
        return self._driver.canvastype

    def get_canvas(self):
        return self._driver.get_canvas()

    def print_canvas(self, canvas):
        pass

    def kickout(self):
        # Not all connection methods will support kickout, even if the
        # driver does support it.  It wouldn't make sense if the driver
        # submits to a print queue, for example!
        pass

    def __str__(self):
        return self.description or "Base printer class"


class _null_printer_driver:
    canvastype = "receipt"

    def get_canvas(self):
        return ReceiptCanvas()


class nullprinter(printer):
    # XXX change to just writing to a BytesIO and throwing it away
    """A "dummy" printer that just writes to the log.
    """
    def __init__(self, name=None, description=None):
        if name:
            self._name = f"nullprinter {name}"
        else:
            self._name = "nullprinter"
        super().__init__(_null_printer_driver(), description)

    def print_canvas(self, canvas):
        for i in canvas:
            log.info("%s: %s", self._name, str(i))

    def __str__(self):
        return self.description or self._name


class badprinter(nullprinter):
    """A null printer that always reports it is offline, for testing.

    Attempts to print will raise an exception.
    """
    def offline(self):
        return "badprinter is always offline!"

    def print_canvas(self, canvas):
        raise PrinterError(self, "badprinter is always offline!")


# XXX Add a 'logprinter' class


class fileprinter(printer):
    """Print to a file.  The file may be a device file!
    """
    def __init__(self, filename, driver, description=None):
        self._filename = filename
        super().__init__(driver, description=description)

    def __str__(self):
        return self.description or f"Print to file {self._filename}"

    def _getfilename(self):
        gi = glob.iglob(self._filename)
        try:
            return next(gi)
        except StopIteration:
            return self._filename

    def offline(self):
        """Is the printer available?

        If the printer is unavailable for any reason, return a description
        of that reason; otherwise return None.
        """
        try:
            f = open(self._getfilename(), 'ab')
            f.close()
        except IOError as e:
            return str(e)

    def print_canvas(self, canvas):
        offline = self.offline()
        if offline:
            raise PrinterError(self, offline)
        with open(self._getfilename(), 'ab') as f:
            self._driver.process_canvas(canvas, f)

    def kickout(self):
        offline = self.offline()
        if offline:
            raise PrinterError(self, offline)
        with open(self._getfilename(), 'ab') as f:
            self._driver.kickout(f)


def _lpgetstatus(f):
    LPGETSTATUS = 0x060b
    buf = array.array('b', [0])
    fcntl.ioctl(f, LPGETSTATUS, buf)
    status = buf[0]
    if status & 0x20:
        return "out of paper"  # LP_POUTPA
    if ~status & 0x10:
        return "off-line"  # LP_PSELECD
    if ~status & 0x08:
        return "error light is on"  # LP_PERRORP


def _chunks(iterable, chunk_size):
    """Produce chunks of up-to a parameterised size from an iterable input."""
    chunk = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) == chunk_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


class linux_lpprinter(fileprinter):
    """Print to a lp device file - /dev/lp? or /dev/usblp? on Linux

    Expects the specified file to support the LPGETSTATUS ioctl.
    """
    def __init__(self, *args, **kwargs):
        if not sys.platform.startswith("linux"):
            raise PrinterError(
                self, f"linux_lpprinter: wrong platform '{sys.platform}' "
                "(expected 'linux...')")
        super().__init__(*args, **kwargs)

    def offline(self):
        try:
            f = open(self._getfilename(), 'ab')
            status = _lpgetstatus(f)
            f.close()
            return status
        except IOError as e:
            return str(e)

    def __str__(self):
        return self.description or f"Print to lp device {self._filename}"


class autodetect_printer:
    """Use the first available device

    A device is available if the glob matches an existing file.  It
    doesn't matter whether the printer is in a "ready" state: it is
    sufficient that it is connected.

    printers is a list of (glob, driver, LPGETSTATUS supported?)

    All drivers must support the same canvas type
    """
    NOT_CONNECTED = "No printer connected"

    def __init__(self, printers, description=None):
        self.canvastype = None
        for path, driver, getstatus in printers:
            if self.canvastype:
                if driver.canvastype != self.canvastype:
                    raise PrinterConfigurationError(
                        "autodetect_printer can only be used with drivers "
                        "that all support the same canvas type")
            else:
                self.canvastype = driver.canvastype
                # XXX using the get_canvas method of the first driver
                # in the list is making an assumption that the
                # canvases provided by each driver are all compatible.
                # It's true at the time of writing, but may need
                # revisiting if more drivers are implemented!
                self.get_canvas = driver.get_canvas
        self._printers = printers
        self.description = description
        self._canvas = None

    @staticmethod
    def _globmatch(path):
        gi = glob.iglob(path)
        try:
            return next(gi)
        except StopIteration:
            return

    def _find_printer(self):
        # Return device file, driver, lpgetstatus_supported
        for path, driver, getstatus in self._printers:
            filename = self._globmatch(path)
            if filename:
                return filename, driver, getstatus
        return None, None, None

    def __enter__(self):
        if self._canvas:
            raise PrinterError(self, "Already started in __enter__()")
        self._canvas = self.get_canvas()
        return self._canvas

    def __exit__(self, type, value, tb):
        try:
            if tb is None:
                self.print_canvas(self._canvas)
        finally:
            self._canvas = None

    def offline(self):
        filename, driver, lpgetstatus_supported = self._find_printer()
        if not filename:
            return self.NOT_CONNECTED
        if lpgetstatus_supported:
            try:
                with open(filename, 'ab') as f:
                    return _lpgetstatus(f)
            except IOError as e:
                return str(e)

    def print_canvas(self, canvas):
        filename, driver, lpgetstatus_supported = self._find_printer()
        if not filename:
            raise PrinterError(self, self.NOT_CONNECTED)
        with open(filename, 'ab') as f:
            status = None
            if lpgetstatus_supported:
                status = _lpgetstatus(f)
            if status:
                raise PrinterError(self, status)
            driver.process_canvas(canvas, f)

    def kickout(self):
        filename, driver, lpgetstatus_supported = self._find_printer()
        if not filename:
            raise PrinterError(self, self.NOT_CONNECTED)
        with open(filename, 'ab') as f:
            status = None
            if lpgetstatus_supported:
                status = _lpgetstatus(f)
            if status:
                raise PrinterError(self, status)
            driver.kickout(f)

    def __str__(self):
        return self.description or "one of: " + ', '.join(
            (glob for glob, driver, status in self._printers))


class netprinter(printer):
    """Print to a network socket.  connection is a (hostname, port) tuple.
    """
    def __init__(self, connection, driver, description=None,
                 family=socket.AF_INET):
        self._connection = connection
        self._family = family
        super().__init__(driver, description=description)

    def __str__(self):
        return self.description or f"Print to network {self._connection}"

    def offline(self):
        """Is the printer available?

        If the printer is unavailable for any reason, return a description
        of that reason; otherwise return None.
        """
        host = self._connection[0]
        if not test_ping(host):
            return f"Printer {host} did not respond to ping"

    def _connect(self):
        s = socket.socket(self._family)
        s.connect(self._connection)
        f = s.makefile('wb')
        return s, f

    # XXX there's too much copy-and-paste here for my liking
    def print_canvas(self, canvas):
        offline = self.offline()
        if offline:
            raise PrinterError(self, offline)
        s, f = self._connect()
        try:
            self._driver.process_canvas(canvas, f)
        finally:
            f.close()
            s.close()

    def kickout(self):
        offline = self.offline()
        if offline:
            raise PrinterError(self, offline)
        s, f = self._connect()
        try:
            self._driver.kickout(f)
        finally:
            f.close()
            s.close()


class tmpfileprinter(printer):
    """Print to a temporary file.

    Calls the "finish" method with the filename before the file is
    deleted.  This method does nothing in this class: it expected that
    subclasses will override it.
    """
    def __str__(self):
        return self.description or "Print to temporary file"

    def print_canvas(self, canvas):
        with tempfile.NamedTemporaryFile(suffix=self._driver.filesuffix) as f:
            self._driver.process_canvas(canvas, f)
            f.flush()
            self.finish(f.name)

    def finish(self, filename):
        pass


class commandprinter(tmpfileprinter):
    """Invoke a command to print.

    The command is expected to have a '%s' in it into which the
    filename to print will be substituted.
    """
    def __init__(self, printcmd, *args, **kwargs):
        self._printcmd = printcmd
        super().__init__(*args, **kwargs)

    def __str__(self):
        return self.description or f"Print to command '{self._printcmd}'"

    def finish(self, filename):
        with open('/dev/null', 'w') as null:
            subprocess.call(self._printcmd % filename,
                            shell=True, stdout=null, stderr=null)


class cupsprinter(printer):
    """Print to a CUPS printer.

    If host, port and/or encryption are specified they are passed to
    the cups.Connection() constructor.  encryption should be
    cups.HTTP_ENCRYPT_ALWAYS, cups.HTTP_ENCRYPT_IF_REQUESTED,
    cups.HTTP_ENCRYPT_NEVER or cups.HTTP_ENCRYPT_REQUIRED.
    """
    def __init__(self, printername, driver, options={}, description=None,
                 host=None, port=None, encryption=None):
        super().__init__(driver, description)
        self._printername = printername
        self._options = options
        self._connect_kwargs = {}
        if host is not None:
            self._connect_kwargs['host'] = host
        if port is not None:
            self._connect_kwargs['port'] = port
        if encryption is not None:
            self._connect_kwargs['encryption'] = encryption

    def __str__(self):
        x = self.description or f"Print to '{self._printername}'"
        o = self.offline()
        if o:
            x = x + f" (offline: {o})"
        return x

    def offline(self):
        try:
            conn = cups.Connection(**self._connect_kwargs)
            accepting = conn.getPrinterAttributes(
                self._printername)['printer-is-accepting-jobs']
            if accepting:
                return
            return f"'{self._printername}' is not accepting jobs at the moment"
        except cups.IPPError as e:
            return str(e)
        except RuntimeError as e:
            return str(e)

    def print_canvas(self, canvas):
        f = io.BytesIO()
        self._driver.process_canvas(canvas, f)
        f.flush()
        connection = cups.Connection(**self._connect_kwargs)
        job = connection.createJob(self._printername, "quicktill output",
                                   self._options)
        connection.startDocument(self._printername, job, "quicktill",
                                 self._driver.mimetype, 1)
        b = f.getvalue()
        connection.writeRequestData(b, len(b))
        connection.finishDocument(self._printername)
        f.close()


class escpos:
    """The ESC/POS protocol for controlling receipt printers.
    """
    filesuffix = ".dat"
    mimetype = "application/octet-stream"
    canvastype = "receipt"

    ep_reset = bytes([27, 64, 27, 116, 16])
    ep_pulse = bytes([27, ord('p'), 0, 50, 50])
    ep_underline = (bytes([27, 45, 0]), bytes([27, 45, 1]), bytes([27, 45, 2]))
    ep_emph = (bytes([27, 69, 0]), bytes([27, 69, 1]))
    ep_colour = (bytes([27, 114, 0]), bytes([27, 114, 1]))
    ep_font = (bytes([27, 77, 0]), bytes([27, 77, 1]))
    ep_left = bytes([27, 97, 0])
    ep_center = bytes([27, 97, 1])
    ep_right = bytes([27, 97, 2])
    ep_ff = bytes([27, 100, 7])
    ep_fullcut = bytes([27, 105])
    ep_unidirectional_on = bytes([27, 85, 1])
    ep_unidirectional_off = bytes([27, 85, 0])
    # follow ep_bitimage_sd with 16-bit little-endian data length
    ep_bitimage_sd = bytes([27, 42, 0])
    ep_bitimage_dd_v24 = bytes([27, 42, 33])  # double-density, 24-dot vertical
    ep_line_spacing_none = bytes([27, 51, 0])
    ep_line_spacing_default = bytes([27, 50])
    ep_short_feed = bytes([27, 74, 5])
    ep_half_dot_feed = bytes([27, 74, 1])

    default_underline = 0
    default_colour = 0
    default_emph = 0

    @staticmethod
    def _ep_2d_cmd(*params):
        """Assemble an ESC/POS 2d barcode command.

        params are either 8-bit integers or bytes(), which will be
        concatenated.
        """
        p = b''.join([bytes([x]) if isinstance(x, int) else x for x in params])
        pL = len(p) & 0xff
        pH = (len(p) >> 8) & 0xff
        return bytes([29, ord('('), ord('k'), pL, pH]) + p

    def __init__(self, cpl, dpl, coding, has_cutter=False,
                 lines_before_cut=3, default_font=0,
                 native_qrcode_support=False):
        self.fontcpl = cpl
        self.dpl = dpl
        self.coding = coding
        self.has_cutter = has_cutter
        self.lines_before_cut = lines_before_cut
        self.default_font = default_font
        if native_qrcode_support:
            self._qrcode = self._qrcode_native
        else:
            self._qrcode = self._qrcode_emulated

    def get_canvas(self):
        return ReceiptCanvas()

    def process_canvas(self, canvas, f):
        colour = self.default_colour
        font = self.default_font
        emph = self.default_emph
        underline = self.default_underline
        cpl = self.fontcpl[font]
        f.write(escpos.ep_reset)
        f.write(escpos.ep_font[font])
        printed = False

        for i in canvas:
            printed = True
            if hasattr(i, 'left') \
               or hasattr(i, 'center') \
               or hasattr(i, 'right'):
                left = getattr(i, 'left', '')
                center = getattr(i, 'center', '')
                right = getattr(i, 'right', '')
                new_colour = getattr(i, 'colour', self.default_colour)
                if new_colour != colour:
                    colour = new_colour
                    f.write(escpos.ep_colour[colour])
                new_font = getattr(i, 'font', self.default_font)
                if new_font != font:
                    font = new_font
                    f.write(escpos.ep_font[font])
                    cpl = self.fontcpl[font]
                new_emph = getattr(i, 'emph', self.default_emph)
                if new_emph != emph:
                    emph = new_emph
                    f.write(escpos.ep_emph[emph])
                new_underline = getattr(i, 'underline', self.default_underline)
                if new_underline != underline:
                    underline = new_underline
                    f.write(escpos.ep_underline[underline])

                # Possible cases:
                # Center is empty - can use lrwrap()
                # Center is not empty, left and right are empty - can use wrap,
                # and send the "centered text" control code
                # Center is not empty, and left and right are not empty -
                # can't use any wrap (XXX or: much fancier wrap than
                # currently implemented!)
                if not center:
                    ll = _lrwrap(left, right, cpl)
                    for i in ll:
                        f.write(("%s\n" % i).encode(self.coding, 'replace'))
                elif not left and not right:
                    f.write(escpos.ep_center)
                    ll = _wrap(center, cpl)
                    for i in ll:
                        f.write(("%s\n" % i).encode(self.coding, 'replace'))
                    f.write(escpos.ep_left)
                else:
                    pad = max(cpl - len(left) - len(center) - len(right), 0)
                    padl = pad // 2
                    padr = pad - padl
                    f.write(
                        ("%s%s%s%s%s\n" % (
                            left, ' ' * padl, center, ' ' * padr, right))
                        .encode(self.coding))
            elif hasattr(i, 'image_data'):
                assert 8 * len(i.image_data) == i.image_width * i.image_height
                self._image(i.image_data, i.image_width, i.image_height, f)
            elif hasattr(i, 'qrcode_data'):
                self._qrcode(i.qrcode_data, f)
            else:
                f.write(b'\n')

        if printed:
            f.write(escpos.ep_ff)
            if self.has_cutter:
                f.write(b'\n' * self.lines_before_cut + escpos.ep_left)
                f.write(escpos.ep_fullcut)
            f.flush()

    def _image(self, data, width, height, f):
        # Print a PBM bit-image
        if width > self.dpl:
            # Image too wide for paper
            return

        # Calculate padding required to center the image
        padding = (self.dpl - width) // 2
        padchars = [False] * padding

        # Partition the bitmap into lines
        lines = []
        for chunk in _chunks(data, width // 8):
            line = padchars.copy()
            for byte in chunk:
                for bit in f"{int(byte):08b}":
                    line.append(bool(int(bit)))
            lines.append(line)

        # Compact up to twenty-four bit-lines into each row
        rows = []
        for linerange in _chunks(lines, 24):
            row = []
            for column in zip(*linerange):
                for segment in _chunks(column, 8):
                    binary = str().join("1" if bit else "0" for bit in segment)
                    row.append(int(binary or "0", base=2))
            rows.append(bytes(row))

        # Write the commands to render the padded image
        f.write(escpos.ep_line_spacing_none)
        f.write(escpos.ep_unidirectional_on)
        for row in rows:
            width_info = (len(row) // 3).to_bytes(length=2, byteorder="little")
            f.write(escpos.ep_bitimage_dd_v24 + width_info + row + b'\n')
        f.write(escpos.ep_unidirectional_off)
        f.write(escpos.ep_line_spacing_default)

        # Clear the line for subsequent content
        f.write(b'\r\n')

    def _qrcode_native(self, data, f):
        # Set the size of a "module", in dots.  The default is apparently
        # 3 (which is also the lowest).  The maximum is 16.

        # Experience has shown that scanning QR codes from curved
        # receipt paper with larger module sizes is difficult; it's
        # better to keep the module size low so the camera can be
        # closer to the paper and the paper can be held flat using
        # fingers on the margin.
        ms = 8
        if self.dpl == 420:  # 58mm paper width
            # if len(data) > 14: ms = 14
            # if len(data) > 24: ms = 12
            # if len(data) > 34: ms = 11
            # if len(data) > 44: ms = 10
            # if len(data) > 58: ms = 9
            # if len(data) > 64: ms = 8
            if len(data) > 84:
                ms = 7
            if len(data) > 119:
                ms = 6
            if len(data) > 177:
                ms = 5
            if len(data) > 250:
                ms = 4
            if len(data) > 439:
                ms = 3
            if len(data) > 742:
                return  # Too big to print
        else:  # 80mm paper width
            # if len(data) > 34: ms = 15
            # if len(data) > 44: ms = 14
            # if len(data) > 45: ms = 13
            # if len(data) > 58: ms = 12
            # if len(data) > 64: ms = 11
            # if len(data) > 84: ms = 10
            # if len(data) > 119: ms = 9
            # if len(data) > 137: ms = 8
            if len(data) > 177:
                ms = 7
            if len(data) > 250:
                ms = 6
            if len(data) > 338:
                ms = 5
            if len(data) > 511:
                ms = 4
            if len(data) > 790:
                ms = 3
            if len(data) > 1273:
                return  # Too big to print
        f.write(self._ep_2d_cmd(49, 67, ms))

        # Set error correction:
        # 48 = L = 7% recovery
        # 49 = M = 15% recovery
        # 50 = Q = 25% recovery
        # 51 = H = 30% recovery
        f.write(self._ep_2d_cmd(49, 69, 51))

        # Send QR code data
        f.write(self._ep_2d_cmd(49, 80, 48, data))

        # Print the QR code
        f.write(escpos.ep_center)
        f.write(self._ep_2d_cmd(49, 81, 48))
        f.write(escpos.ep_left)

    def _qrcode_emulated(self, data, f):
        if not _qrcode_supported:
            f.write("qrcode library not installed".encode(self.coding))
            return
        q = qrcode.QRCode(border=2,
                          error_correction=qrcode.constants.ERROR_CORRECT_H)
        q.add_data(data)
        code = q.get_matrix()
        f.write(escpos.ep_unidirectional_on)
        # To get a good print, we print two rows at a time - but only
        # feed the paper through by one row.  This means that each
        # part of the code should be printed twice.  We're also
        # printing each pair of rows twice, advancing the paper by
        # half a dot inbetween.  We only use 6 of the 8 pins of the
        # printer to keep this code simple.
        lt = {
            (False, False): bytes([0x00]),
            (False, True): bytes([0x1c]),
            (True, False): bytes([0xe0]),
            (True, True): bytes([0xfc]),
        }
        while len(code) > 0:
            if len(code) > 1:
                row = zip(code[0], code[1])
            else:
                row = zip(code[0], [False] * len(code[0]))
            code = code[1:]
            row = b''.join(lt[x] * 3 for x in row)
            width = len(row)
            if width > self.dpl:
                # Code too wide for paper
                break
            padding = (self.dpl - width) // 2
            width = width + padding
            padchars = bytes([0]) * padding
            header = escpos.ep_bitimage_sd \
                + bytes([width & 0xff, (width >> 8) & 0xff])
            f.write(header + padchars + row + b'\r')
            f.write(escpos.ep_half_dot_feed)
            f.write(header + padchars + row + b'\r')
            f.write(escpos.ep_short_feed)
        f.write(escpos.ep_unidirectional_off)

    def kickout(self, f):
        f.write(escpos.ep_pulse)
        f.flush()


class Epson_TM_U220_driver(escpos):
    """Driver for Epson TM-U220 dot-matrix receipt printers
    """
    def __init__(self, paperwidth, coding='iso-8859-1', has_cutter=False):
        # Characters per line with fonts 0 and 1
        if paperwidth == 57 or paperwidth == 58:
            cpl = (25, 30)
            dpl = 148
        elif paperwidth == 76:
            cpl = (33, 40)
            dpl = 192
        else:
            raise Exception("Unknown paper width")
        escpos.__init__(self, cpl, dpl, coding, has_cutter,
                        default_font=1)


class Epson_TM_T20_driver(escpos):
    """Driver for Epson TM-T20 thermal receipt printers
    """
    def __init__(self, paperwidth, coding='iso-8859-1'):
        # Characters per line with fonts 0 and 1
        if paperwidth == 57 or paperwidth == 58:
            cpl = (35, 46)
            dpl = 420
        elif paperwidth == 80:
            cpl = (48, 64)
            dpl = 576
        else:
            raise Exception(f"Unknown paper width {paperwidth}")
        escpos.__init__(self, cpl, dpl, coding, has_cutter=True,
                        lines_before_cut=0, default_font=0,
                        native_qrcode_support=True)


class Aures_ODP_333_driver(escpos):
    """Driver for Aures ODP 333 thermal receipt printers

    Note that when connected over USB this printer doesn't support the
    LPGETSTATUS ioctl.
    """
    def __init__(self, coding='iso-8859-1'):
        # Characters per line with fonts 0 and 1
        cpl = (42, 56)
        dpl = 512
        escpos.__init__(self, cpl, dpl, coding, has_cutter=True,
                        lines_before_cut=0, default_font=0,
                        native_qrcode_support=True)


class CenterLine(Flowable):
    def __init__(self, text, font, fontsize, pitch):
        self.text = text
        self.font = font
        self.fontsize = fontsize
        self.pitch = pitch

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        return self.width, self.pitch

    def draw(self):
        c = self.canv
        c.setFont(self.font, self.fontsize)
        c.drawCentredString(self.width / 2, self.pitch - self.fontsize,
                            self.text)


class LRLine(Flowable):
    def __init__(self, ltext, rtext, font, fontsize, pitch):
        self.ltext = ltext
        self.rtext = rtext
        self.font = font
        self.fontsize = fontsize
        self.pitch = pitch

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        # Use a very simple algorithm because we are always working on
        # small amounts of text
        words = self.ltext.split()
        if not words:
            self._leftlines = []
            self._extraline = True
            return self.width, self.pitch
        lines = [words.pop(0)]
        while words:
            cw = words.pop(0)
            trial = lines[-1] + " " + cw
            width = stringWidth(trial, self.font, self.fontsize)
            if width > availWidth:
                lines.append(cw)
            else:
                lines[-1] = trial
        # Does the rtext fit on the last line?
        if self.rtext:
            trial = lines[-1] + " " + self.rtext
            extraline = stringWidth(
                trial, self.font, self.fontsize) > availWidth
        else:
            extraline = False
        height = len(lines) * self.pitch
        if extraline:
            height += self.pitch
        self._leftlines = lines
        self._extraline = extraline
        return self.width, height

    def draw(self):
        c = self.canv
        c.setFont(self.font, self.fontsize)
        y = len(self._leftlines) * self.pitch - self.fontsize
        if self._extraline:
            y += self.pitch
        for l in self._leftlines:
            c.drawString(0, y, l)
            y -= self.pitch
        if not self._extraline:
            y += self.pitch
        c.drawRightString(self.width, y, self.rtext)


class pdf_driver:
    """PDF driver that offers a receipt canvas
    """
    filesuffix = ".pdf"
    mimetype = "application/pdf"
    canvastype = "receipt"

    def __init__(self, pagesize=A4, columns=2, margin=40, colgap=20,
                 fontname="Courier", fontsizes=[10, 8], pitches=[12, 10]):
        self.pagesize = pagesize
        self.columns = columns
        self.margin = margin
        self.colgap = colgap
        self.fontname = fontname
        self.fontsizes = fontsizes
        self.pitches = pitches

    def get_canvas(self):
        return ReceiptCanvas()

    def process_canvas(self, canvas, f):
        frames = []
        colwidth = (self.pagesize[0]
                    - (2 * self.margin)
                    - ((self.columns - 1) * self.colgap)) / self.columns
        colheight = self.pagesize[1] \
            - (2 * self.margin)
        colspacing = colwidth + self.colgap
        for col in range(0, self.columns):
            frames.append(Frame(
                self.margin + (colspacing * col), self.margin,
                colwidth, colheight))
        pagetemplate = PageTemplate(id='default', frames=frames)
        doctemplate = BaseDocTemplate(f, pagesize=self.pagesize,
                                      pageTemplates=[pagetemplate],
                                      showBoundary=1)

        story = []

        for i in canvas:
            if hasattr(i, 'left') \
               or hasattr(i, 'center') \
               or hasattr(i, 'right'):
                left = getattr(i, 'left', '')
                center = getattr(i, 'center', '')
                right = getattr(i, 'right', '')
                font = self.fontname
                if getattr(i, 'emph', 0) or getattr(i, 'colour', 0):
                    font += "-Bold"
                fontsize = self.fontsizes[getattr(i, 'font', 0)]
                pitch = self.pitches[getattr(i, 'font', 0)]
                if not center:
                    story.append(LRLine(left, right, font, fontsize, pitch))
                elif center:
                    story.append(CenterLine(center, font, fontsize, pitch))
            else:
                pass

        doctemplate.build(story)

    def kickout(self, f):
        pass


# The rest of this file deals with offering PDF canvases
# (canvastype='pdf' as opposed to canvastype='receipt').  We use
# reportlab.pdfgen, but augment it somewhat because its API is
# deficient in inconvenient ways:
#
# 1. The API requires output file details when creating a canvas, but
# then merely stores them and ignores them until save() is called.  We
# support passing None as the filename when creating the canvas, and
# add an optional filename argument to save()
#
# 2. The canvas knows the page size, but doesn't have a supported
# method to fetch it.  We add one.
#
# 3. We add a method to clear the current page (such that save() will
# not call showPage)
#
# All of these additions depend on undocumented implementation details
# of reportlab.pdfgen, so may break randomly in the future. XXX

class Canvas(canvas.Canvas):
    """reportlab.pdfgen.Canvas modified by quicktill
    """
    def getPageSize(self):
        return self._pagesize

    def clearPage(self):
        self._code = []

    def save(self, filename=None):
        if filename is None:
            filename = self._filename
        self._doc.SaveToFile(filename, self)


class pdf_page:
    """PDF driver that offers a PDF canvas

    The PDF canvas is extended to make the page size readable via a
    getPageSize() method.
    """
    filesuffix = ".pdf"
    mimetype = "application/pdf"
    canvastype = "pdf"

    def __init__(self, pagesize=A4):
        self._pagesize = pagesize

    def get_canvas(self):
        canvas = Canvas(None, pagesize=self._pagesize)
        canvas.setAuthor("quicktill")
        return canvas

    def process_canvas(self, canvas, f):
        canvas.save(filename=f)


class LabelCanvas(Canvas):
    """Canvas augmented to provide n-up printing
    """
    def __init__(self, labellist, labelsize, *args, **kwargs):
        self._labellist = labellist
        self._labelsize = labelsize
        super().__init__(*args, **kwargs)
        self._startpage()

    def _startpage(self):
        self._cpll = list(self._labellist)
        self.saveState()
        self._nextlabel()

    def _nextlabel(self):
        self.restoreState()
        if self._cpll:
            self.saveState()
            lpos = self._cpll.pop(0)
            self.translate(*lpos)
        else:
            super().showPage()
            self._startpage()

    def getPageSize(self):
        return self._labelsize

    def showPage(self):
        self._nextlabel()

    def _end(self, fileobj):
        if len(self._cpll) == (len(self._labellist) - 1):
            # We're still set up to draw the first label on the
            # current page - the code will just be the save and
            # transform for the first label.  Drop it.
            self.clearPage()
        else:
            # Flush the current page before saving
            super().showPage()
        self.save(filename=fileobj)


class pdf_labelpage:
    """n-up PDF driver that offers a PDF canvas

    A driver that prints onto laser label paper.  It offers a PDF
    canvas, extended to make the page size readable via a
    getPageSize() method.  Each individual label is treated as a
    separate page; the canvas overrides the showPage() method such
    that it can be called after each individual label has been output,
    and takes care of changing the origin to enable the next label to
    be output.
    """
    filesuffix = ".pdf"
    mimetype = "application/pdf"
    canvastype = "pdf"

    def __init__(self, labelsacross, labelsdown,
                 labelwidth, labelheight,
                 horizlabelgap, vertlabelgap,
                 pagesize=A4):
        self.width = toLength(labelwidth)
        self.height = toLength(labelheight)
        self._pagesize = pagesize
        horizlabelgap = toLength(horizlabelgap)
        vertlabelgap = toLength(vertlabelgap)
        pagewidth = pagesize[0]
        pageheight = pagesize[1]
        sidemargin = (pagewidth - (self.width * labelsacross)
                      - (horizlabelgap * (labelsacross - 1))) / 2
        endmargin = (pageheight - (self.height * labelsdown)
                     - (vertlabelgap * (labelsdown - 1))) / 2
        self.label = 0
        self.ll = []
        for y in range(0, labelsdown):
            for x in range(0, labelsacross):
                # We assume that labels are centered top-to-bottom
                # and left-to-right, and that the gaps between them
                # are consistent.  The page origin is in the bottom-left.
                # We record the bottom-left-hand corner of each label.
                xpos = sidemargin + ((self.width + horizlabelgap) * x)
                ypos = (pageheight - endmargin
                        - ((self.height + vertlabelgap) * y) - self.height)
                self.ll.append((xpos, ypos))

    def get_canvas(self):
        canvas = LabelCanvas(self.ll, (self.width, self.height),
                             None, pagesize=self._pagesize)
        canvas.setAuthor("quicktill")
        return canvas

    def process_canvas(self, canvas, f):
        canvas._end(f)
