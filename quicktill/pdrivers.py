import socket
import os
import tempfile
import io
import textwrap
import subprocess
import fcntl
import array
import sys
from reportlab.pdfgen import canvas
from reportlab.lib.units import toLength
from reportlab.lib.pagesizes import A4
import cups
import glob
try:
    import qrcode
    _qrcode_supported = True
except ImportError:
    _qrcode_supported = False

import logging
log = logging.getLogger(__name__)

class PrinterError(Exception):
    def __init__(self,printer,desc):
        self.printer=printer
        self.desc=desc
    def __str__(self):
        return "PrinterError({},'{}')".format(self.printer,self.desc)

# Printer objects must not claim external resources when instances are
# created; they must only attempt to claim them when __enter__ is
# called.

# We break most printer definitions up into two classes: a connection
# and a protocol.  The connection object defines how we connect to the
# printer (USB, parallel, network etc.) and is passed an instance of a
# protocol object defining how to control the printer (paper width,
# options, etc.)

# Methods a printer driver should implement (these objects are used
# when a printer class is used in a with: statement)
# setdefattr - set default attributes for subsequent lines
# printline - print a line.  Text up to first \t is left-justified;
#  text up to second \t is centered; text after that is right-aligned
# cancut() - does the hardware support cutting?  If not, the caller can pause
# setattr/printline have optional attribute arguments:
#  colour (0/1 at the moment)
#  emph 0/1
#  font 0/1
#  underline 0/1/2
# kickout()

def test_ping(host):
    """
    Check whether a host is alive using ping; returns True if it is alive.

    """
    with open('/dev/null','w') as null:
        r=subprocess.call("ping -q -w 2 -c 1 %s"%host,
                          shell=True,stdout=null,stderr=null)
    if r==0: return True
    return False

def lrwrap(l,r,width):
    w=textwrap.wrap(l,width)
    if len(w)==0: w=[""]
    if len(w[-1])+len(r)>=width:
        w.append("")
    w[-1]=w[-1]+(' '*(width-len(w[-1])-len(r)))+r
    return w

def wrap(l,width):
    w=textwrap.wrap(l,width)
    if len(w)==0: w=[""]
    return w

class nullprinter:
    """
    A "dummy" printer that just writes to the log.

    """
    def __init__(self,name=None,description=None):
        if name: self._name="nullprinter {}".format(name)
        else: self._name="nullprinter"
        self._description=description
        self._started=False
    def __enter__(self):
        if self._started:
            raise PrinterError(self,"Nested call to __enter__()")
        log.info("%s: start",self._name)
        self._started = True
        return self
    def __exit__(self,type,value,tb):
        log.info("%s: end", self._name)
        if not self._started:
            raise PrinterError(self,"__exit__() called without __enter__()")
        self._started = False
    def offline(self):
        return
    def setdefattr(self,colour=None,font=None,emph=None,underline=None):
        pass
    def printline(self,l="",
                  colour=None,font=None,emph=None,underline=None):
        assert isinstance(l, str)
        log.info("%s: printline: %s",self._name,l)
        return True
    def printqrcode(self,code):
        log.info("%s: printqrcode: %s",self._name,code)
    def cancut(self):
        return False
    def kickout(self):
        log.info("%s: kickout",self._name)
    def __str__(self):
        return self._description or self._name

class badprinter(nullprinter):
    """
    A null printer that always reports it is offline, for testing.

    """
    def offline(self):
        return "badprinter is always offline!"
    def __enter__(self):
        raise PrinterError(self,"badprinter is always offline!")

class fileprinter:
    """Print to a file.  The file may be a device file!

    """
    def __init__(self,filename,driver,description=None):
        self._filename=filename
        self._driver=driver
        self._description=description
        self._file=None
    def __str__(self):
        return self._description or "Print to file {}".format(self._fileprinter)
    def _getfilename(self):
        gi=glob.iglob(self._filename)
        try:
            return next(gi)
        except StopIteration:
            return self._filename
    def offline(self):
        """If the printer is unavailable for any reason, return a description
        of that reason; otherwise return None.

        """
        if self._file: return 
        try:
            f = open(self._getfilename(), 'ab')
            f.close()
        except IOError as e:
            return str(e)
    def __enter__(self):
        if self._file:
            raise PrinterError(self,"Already started in start()")
        self._file = open(self._getfilename(), 'ab')
        return self._driver.start(self._file,self)
    def __exit__(self,type,value,tb):
        try:
            if tb is not None:
                self._driver.printline(
                    "An error occurred, the document may be incomplete")
            self._driver.end()
        except:
            pass
        self._file.close()
        self._file=None

class linux_lpprinter(fileprinter):
    """
    Print to a lp device file - /dev/lp? or /dev/usblp? on Linux

    Expects the specified file to support the LPGETSTATUS ioctl.

    """
    LPGETSTATUS=0x060b
    @staticmethod
    def _decode_status(status):
        if status & 0x20: return "out of paper" # LP_POUTPA
        if ~status & 0x10: return "off-line" # LP_PSELECD
        if ~status & 0x08: return "error light is on" # LP_PERRORP
    def __init__(self,*args,**kwargs):
        if not sys.platform.startswith("linux"):
            raise PrinterError(
                self,"linux_lpprinter: wrong platform '{}' "
                "(expected 'linux...')".format(sys.platform))
        fileprinter.__init__(self,*args,**kwargs)
    def offline(self):
        if self._file: return 
        try:
            f = open(self._getfilename(), 'ab')
            buf = array.array('b', [0])
            fcntl.ioctl(f, self.LPGETSTATUS, buf)
            f.close()
            return self._decode_status(buf[0])
        except IOError as e:
            return str(e)

class netprinter:
    """
    Print to a network socket.  connection is a (hostname,port) tuple.

    """
    def __init__(self,connection,driver,description=None):
        self._connection=connection
        self._driver=driver
        self._description=description
        self._socket=None
        self._file=None
    def __str__(self):
        return self._description or \
            "Print to network {}".format(self._connection)
    def offline(self):
        """
        If the printer is unavailable for any reason, return a description
        of that reason; otherwise return None.

        """
        if self._file:
            return
        host=self._connection[0]
        if not test_ping(host):
            return "Printer {} did not respond to ping".format(host)
    def __enter__(self):
        if self._file:
            raise PrinterError(self,"Already started in start()")
        self._socket=socket.socket(socket.AF_INET)
        self._socket.connect(self._connection)
        self._file=self._socket.makefile('wb')
        return self._driver.start(self._file,self)
    def __exit__(self,type,value,tb):
        try:
            if tb is not None:
                self._driver.printline(
                    "An error occurred, the document may be incomplete")
            self._driver.end()
        except:
            pass
        self._file.close()
        self._file=None
        self._socket.close()
        self._socket=None

class tmpfileprinter:
    """
    Print to a temporary file.  Call the "finish" method with the
    filename before the file is deleted.  This method does nothing in
    this class: it expected that subclasses will override it.

    """
    def __init__(self,driver,description=None):
        self._driver=driver
        self._file=None
        self._description=description
    def __str__(self):
        return self._description or "Print to temporary file"
    def offline(self):
        return
    def __enter__(self):
        if self._file:
            raise PrinterError(self,"Already started in start()")
        self._file=tempfile.NamedTemporaryFile(suffix=self._driver.filesuffix)
        return self._driver.start(self._file,self)
    def __exit__(self,type,value,tb):
        try:
            if tb is not None:
                self._driver.printline(
                    "An error occurred, the document may be incomplete")
            self._driver.end()
        except:
            pass
        tmpfilename=self._file.name
        self._file.flush()
        self.finish(self._file.name)
        self._file.close()
        self._file=None
    def finish(self,filename):
        pass

class commandprinter(tmpfileprinter):
    """
    Invoke a command to print.  The command is expected to have a '%s'
    in it into which the filename to print will be substituted.

    """
    def __init__(self,printcmd,*args,**kwargs):
        tmpfileprinter.__init__(self,*args,**kwargs)
        self._printcmd=printcmd
    def __str__(self):
        return self._description or "Print to command '{}'".format(self._printcmd)
    def finish(self,filename):
        with open('/dev/null','w') as null:
            r=subprocess.call(self._printcmd%filename,
                              shell=True,stdout=null,stderr=null)

class cupsprinter:
    """Print to a CUPS printer.

    If host, port and/or encryption are specified they are passed to
    the cups.Connection() constructor.  encryption should be
    cups.HTTP_ENCRYPT_ALWAYS, cups.HTTP_ENCRYPT_IF_REQUESTED,
    cups.HTTP_ENCRYPT_NEVER or cups.HTTP_ENCRYPT_REQUIRED.
    """
    def __init__(self, printername, driver, options={}, description=None,
                 host=None, port=None, encryption=None):
        self._driver = driver
        self._file = None
        self._description = description
        self._printername = printername
        self._options = options
        self._connect_kwargs = {}
        if host is not None:
            self._connect_kwargs['host'] = host
        if port is not None:
            self._connect_kwargs['port'] = port
        if encryption is not None:
            self._connect_kwargs['encryption'] = encryption
        self._file = None

    def __str__(self):
        x = self._description or "Print to '{}'".format(self._printername)
        o = self.offline()
        if o:
            x = x + " (offline: {})".format(o)
        return x

    def offline(self):
        try:
            conn = cups.Connection(**self._connect_kwargs)
            accepting = conn.getPrinterAttributes(
                self._printername)['printer-is-accepting-jobs']
            if accepting:
                return
            return "'{}' is not accepting jobs at the moment".format(
                self._printername)
        except cups.IPPError as e:
            return str(e)

    def __enter__(self):
        if self._file:
            raise PrinterError(self, "Already started in start()")
        self._file = io.BytesIO()
        return self._driver.start(self._file, self)

    def __exit__(self, type, value, tb):
        try:
            self._driver.end()
            if tb is not None:
                # An exception was raised while generating the file to print.
                # Don't print it.
                self._file = None
                return
        except:
            pass
        self._file.flush()
        connection = cups.Connection(**self._connect_kwargs)
        job = connection.createJob(self._printername, "quicktill output",
                                   self._options)
        doc = connection.startDocument(self._printername, job, "quicktill",
                                       self._driver.mimetype, 1)
        b = self._file.getvalue()
        connection.writeRequestData(b, len(b))
        connection.finishDocument(self._printername)
        self._file.close()
        self._file = None

def ep_2d_cmd(*params):
    """Assemble an ESC/POS 2d barcode command.

    params are either 8-bit integers or bytes(), which will be
    concatenated.
    """
    p = b''.join([bytes([x]) if isinstance(x, int) else x for x in params])
    pL = len(p) & 0xff
    pH = (len(p) >> 8) & 0xff
    return bytes([29, ord('('), ord('k'), pL, pH]) + p

class escpos:
    """The ESC/POS protocol for controlling receipt printers.
    """
    filesuffix = ".dat"
    mimetype = "application/octet-stream"
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
    ep_bitimage_sd = bytes([27, 42, 0]) # follow with 16-bit little-endian data length
    ep_short_feed = bytes([27, 74, 5])
    ep_half_dot_feed = bytes([27, 74, 1])
    def __init__(self, cpl, dpl, coding, has_cutter=False,
                 lines_before_cut=3, default_font=0,
                 native_qrcode_support=False):
        self.f = None
        self.fontcpl = cpl
        self.dpl = dpl
        self.coding = coding
        self.has_cutter = has_cutter
        self.lines_before_cut = lines_before_cut
        self.default_font = default_font
        self.native_qrcode_support = native_qrcode_support
    def start(self, fileobj, interface):
        self.f = fileobj
        self.colour = 0
        self.font = self.default_font
        self.emph = 0
        self.underline = 0
        self.cpl = self.fontcpl[self.font]
        self.f.write(escpos.ep_reset)
        self.f.write(escpos.ep_font[self.font])
        self._printed = False
        return self
    def end(self):
        if self._printed:
            self.f.write(escpos.ep_ff)
            if self.has_cutter:
                self.f.write(b'\n' * self.lines_before_cut + escpos.ep_left)
                self.f.write(escpos.ep_fullcut)
            self.f.flush()
        self.f = None
    def setdefattr(self, colour=None, font=None, emph=None, underline=None):
        if colour is not None:
            if colour != self.colour:
                self.colour = colour
                self.f.write(escpos.ep_colour[colour])
        if font is not None:
            if font != self.font:
                self.font = font
                self.cpl = self.fontcpl[font]
                self.f.write(escpos.ep_font[font])
        if emph is not None:
            if emph != self.emph:
                self.emph = emph
                self.f.write(escpos.ep_emph[emph])
        if underline is not None:
            if underline != self.underline:
                self.underline = underline
                self.f.write(escpos.ep_underline[underline])
    def printline(self, l="",
                  colour=None, font=None, emph=None, underline=None):
        self._printed = True
        cpl = self.cpl
        if font is not None:
            cpl = self.fontcpl[font]
        s = l.split("\t")
        left = s[0] if len(s) > 0 else ""
        center = s[1] if len(s) > 1 else ""
        right = s[2] if len(s) > 2 else ""
        if colour is not None:
            self.f.write(escpos.ep_colour[colour])
        if font is not None:
            self.f.write(escpos.ep_font[font])
        if emph is not None:
            self.f.write(escpos.ep_emph[emph])
        if underline is not None:
            self.f.write(escpos.ep_underline[underline])
        # Possible cases:
        # Center is empty - can use lrwrap()
        # Center is not empty, left and right are empty - can use wrap,
        # and send the "centered text" control code
        # Center is not empty, and left and right are not empty -
        # can't use any wrap.

        if not center:
            ll = lrwrap(left, right, cpl)
            for i in ll:
                self.f.write(("%s\n" % i).encode(self.coding))
        elif not left and not right:
            self.f.write(escpos.ep_center)
            ll = wrap(center, cpl)
            for i in ll:
                self.f.write(("%s\n" % i).encode(self.coding))
            self.f.write(escpos.ep_left)
        else:
            pad = max(cpl - len(left) - len(center) - len(right), 0)
            padl = pad // 2
            padr = pad - padl
            self.f.write(("%s%s%s%s%s\n" % (
                left, ' ' * padl, center, ' ' * padr, right)).
                         encode(self.coding))
        if colour is not None:
            self.f.write(escpos.ep_colour[self.colour])
        if font is not None:
            self.f.write(escpos.ep_font[self.font])
        if emph is not None:
            self.f.write(escpos.ep_emph[self.emph])
        if underline is not None:
            self.f.write(escpos.ep_underline[self.underline])
    def printqrcode_native(self, data):
        log.debug("Native QR code print: %d bytes: %s" % (len(data), repr(data)))
        # Set the size of a "module", in dots.  The default is apparently
        # 3 (which is also the lowest).  The maximum is 16.

        # Experience has shown that scanning QR codes from curved
        # receipt paper with larger module sizes is difficult; it's
        # better to keep the module size low so the camera can be
        # closer to the paper and the paper can be held flat using
        # fingers on the margin.
        ms = 8
        if self.dpl == 420: # 58mm paper width
            #if len(data) > 14: ms = 14
            #if len(data) > 24: ms = 12
            #if len(data) > 34: ms = 11
            #if len(data) > 44: ms = 10
            #if len(data) > 58: ms = 9
            #if len(data) > 64: ms = 8
            if len(data) > 84: ms = 7
            if len(data) > 119: ms = 6
            if len(data) > 177: ms = 5
            if len(data) > 250: ms = 4
            if len(data) > 439: ms = 3
            if len(data) > 742: return # Too big to print
        else: # 80mm paper width
            #if len(data) > 34: ms = 15
            #if len(data) > 44: ms = 14
            #if len(data) > 45: ms = 13
            #if len(data) > 58: ms = 12
            #if len(data) > 64: ms = 11
            #if len(data) > 84: ms = 10
            #if len(data) > 119: ms = 9
            #if len(data) > 137: ms = 8
            if len(data) > 177: ms = 7
            if len(data) > 250: ms = 6
            if len(data) > 338: ms = 5
            if len(data) > 511: ms = 4
            if len(data) > 790: ms = 3
            if len(data) > 1273: return # Too big to print
        self.f.write(ep_2d_cmd(49, 67, ms))

        # Set error correction:
        # 48 = L = 7% recovery
        # 49 = M = 15% recovery
        # 50 = Q = 25% recovery
        # 51 = H = 30% recovery
        self.f.write(ep_2d_cmd(49, 69, 51))

        # Send QR code data
        self.f.write(ep_2d_cmd(49, 80, 48, data))

        # Print the QR code
        self.f.write(escpos.ep_center)
        self.f.write(ep_2d_cmd(49, 81, 48))
        self.f.write(escpos.ep_left)
    def printqrcode(self, data):
        self._printed = True
        if self.native_qrcode_support:
            return self.printqrcode_native(data)
        if not _qrcode_supported:
            self.printline("qrcode library not installed")
            return
        q = qrcode.QRCode(border=2,
                          error_correction=qrcode.constants.ERROR_CORRECT_H)
        q.add_data(data)
        code = q.get_matrix()
        self.f.write(escpos.ep_unidirectional_on)
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
            header = escpos.ep_bitimage_sd + \
                     bytes([width & 0xff, (width >> 8) & 0xff])
            self.f.write(header + padchars + row + b'\r')
            self.f.write(escpos.ep_half_dot_feed)
            self.f.write(header + padchars + row + b'\r')
            self.f.write(escpos.ep_short_feed)
        self.f.write(escpos.ep_unidirectional_off)
    def kickout(self):
        self.f.write(escpos.ep_pulse)
        self.f.flush()

class Epson_TM_U220_driver(escpos):
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
    def __init__(self,paperwidth,coding='iso-8859-1'):
        # Characters per line with fonts 0 and 1
        if paperwidth == 57 or paperwidth == 58:
            cpl = (35, 46)
            dpl = 420
        elif paperwidth == 80:
            cpl = (48, 64)
            dpl = 576
        else:
            raise Exception("Unknown paper width {}".format(paperwidth))
        escpos.__init__(self,cpl,dpl,coding,has_cutter=True,
                        lines_before_cut=0,default_font=0,
                        native_qrcode_support=True)

class pdf_driver:
    """A driver that outputs to PDF and supports the same calls as the
    ESC/POS driver.

    """
    filesuffix = ".pdf"
    mimetype = "application/pdf"
    def __init__(self,width=140,pagesize=A4,
                 fontsizes=[8,10],pitches=[10,12]):
        """
        width is the width of the output in points

        """
        self.width=width
        self.pagesize=pagesize
        self.pagewidth=pagesize[0]
        self.pageheight=pagesize[1]
        self.fontsizes=fontsizes
        self.pitches=pitches
        self.leftmargin=40
    def start(self,fileobj,interface):
        self._f=fileobj
        self.c=canvas.Canvas(self._f,pagesize=self.pagesize)
        self.colour=0
        self.font=0
        self.emph=0
        self.underline=0
        self.fontsize=self.fontsizes[self.font]
        self.pitch=self.pitches[self.font]
        self.y=self.pageheight-self.pitch*4
        self.x=self.leftmargin
        self.column=0
        return self
    def end(self):
        self.c.showPage()
        self.c.save()
        del self.c
    def newcol(self):
        self.y=self.pageheight-self.pitch*4
        self.column=self.column+1
        self.x=self.leftmargin+(self.width+self.leftmargin)*self.column
        if (self.x+self.width+self.leftmargin)>self.pagewidth:
            self.c.showPage()
            self.column=0
            self.x=self.leftmargin
    def setdefattr(self,colour=None,font=None,emph=None,underline=None):
        if colour is not None:
            if colour!=self.colour:
                self.colour=colour
        if font is not None:
            if font!=self.font:
                self.font=font
        if emph is not None:
            if emph!=self.emph:
                self.emph=emph
        if underline is not None:
            if underline!=self.underline:
                self.underline=underline
    def printline(self, l="",
                  colour=None,font=None,emph=None,underline=None):
        if font is not None:
            fontsize=self.fontsizes[font]
            pitch=self.pitches[font]
        else:
            fontsize=self.fontsize
            pitch=self.pitch
        if colour is None: colour=self.colour
        if emph is None: emph=self.emph
        if underline is None: underline=self.underline
        fontname="Courier"
        if emph or colour: fontname="Courier-Bold"
        self.c.setFont(fontname,fontsize)
        s=l.split("\t")
        if len(s)>0: left=s[0]
        else: left=""
        if len(s)>1: center=s[1]
        else: center=""
        if len(s)>2: right=s[2]
        else: right=""
        self.c.drawString(self.x,self.y,left)
        self.c.drawCentredString((self.x+self.width/2),self.y,center)
        self.c.drawRightString(self.x+self.width,self.y,right)
        self.y=self.y-pitch
        if self.y<50:
            self.newcol()
    def printqrcode(self,code):
        pass
    def cancut(self):
        return False
    def kickout(self):
        pass

# XXX this depends on an implementation detail of reportlab.pdfgen
class PageSizeCanvas(canvas.Canvas):
    def getPageSize(self):
        return self._pagesize

class pdf_page:
    """A driver that presents as a PDF canvas, extended to make the page
    size readable via a getPageSize() method.

    """
    filesuffix = ".pdf"
    mimetype = "application/pdf"
    def __init__(self,pagesize=A4):
        self._pagesize=pagesize
    def start(self,fileobj,interface):
        self._canvas=PageSizeCanvas(fileobj,pagesize=self._pagesize)
        self._canvas.setAuthor("quicktill")
        return self._canvas
    def end(self):
        self._canvas.save()
        del self._canvas

    def printline(self, l="",
                  colour=None, font=None, emph=None, underline=None):
        pass

# XXX this depends on an implementation detail of reportlab.pdfgen
class LabelCanvas(canvas.Canvas):
    def __init__(self,labellist,labelsize,*args,**kwargs):
        self._labellist=labellist
        self._labelsize=labelsize
        canvas.Canvas.__init__(self,*args,**kwargs)
        self._startpage()
    def _startpage(self):
        self._cpll=list(self._labellist)
        self.saveState()
        self._nextlabel()
    def _nextlabel(self):
        self.restoreState()
        if self._cpll:
            self.saveState()
            lpos=self._cpll.pop(0)
            self.translate(*lpos)
        else:
            canvas.Canvas.showPage(self)
            self._startpage()
    def getPageSize(self):
        return self._labelsize
    def showPage(self):
        self._nextlabel()
    def _end(self):
        if len(self._cpll)==len(self._labellist):
            # We haven't drawn a label on this page yet - the code
            # will just be the save and transform for the first label.
            # Drop it.
            self._code = []
        else:
            # We need to flush the current page explicitly before
            # saving, because the save() method calls showPage() which
            # we have overridden.
            canvas.Canvas.showPage(self)
        self.save()

class pdf_labelpage:
    """A driver that prints onto laser label paper.  It presents as a PDF
    canvas, extended to make the page size readable via a
    getPageSize() method.  Each individual label is treated as a
    separate page; the canvas overrides the showPage() method such
    that it can be called after each individual label has been output,
    and takes care of changing the origin to enable the next label to
    be output.

    """
    filesuffix = ".pdf"
    mimetype = "application/pdf"
    def __init__(self,labelsacross,labelsdown,
                 labelwidth,labelheight,
                 horizlabelgap,vertlabelgap,
                 pagesize=A4):
        self.width=toLength(labelwidth)
        self.height=toLength(labelheight)
        self._pagesize=pagesize
        horizlabelgap=toLength(horizlabelgap)
        vertlabelgap=toLength(vertlabelgap)
        pagewidth=pagesize[0]
        pageheight=pagesize[1]
        sidemargin=(pagewidth-(self.width*labelsacross)-
                    (horizlabelgap*(labelsacross-1)))/2
        endmargin=(pageheight-(self.height*labelsdown)-
                   (vertlabelgap*(labelsdown-1)))/2
        self.label=0
        self.ll=[]
        for y in range(0,labelsdown):
            for x in range(0,labelsacross):
                # We assume that labels are centered top-to-bottom
                # and left-to-right, and that the gaps between them
                # are consistent.  The page origin is in the bottom-left.
                # We record the bottom-left-hand corner of each label.
                xpos=sidemargin+((self.width+horizlabelgap)*x)
                ypos=(pageheight-endmargin-((self.height+vertlabelgap)*y)
                      -self.height)
                self.ll.append((xpos,ypos))
    def start(self,fileobj,interface):
        self._canvas=LabelCanvas(self.ll,(self.width,self.height),
                                 fileobj,pagesize=self._pagesize)
        self._canvas.setAuthor("quicktill")
        return self._canvas
    def end(self):
        self._canvas._end()
        del self._canvas

    def printline(self, l="",
                  colour=None, font=None, emph=None, underline=None):
        pass
