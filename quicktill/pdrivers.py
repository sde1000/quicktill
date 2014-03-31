from __future__ import unicode_literals
import string,socket,os,tempfile,textwrap,subprocess,fcntl,array,sys
from reportlab.pdfgen import canvas
from reportlab.lib.units import toLength
from reportlab.lib.pagesizes import A4
import qrcode
import logging
log=logging.getLogger(__name__)

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
# Furthermore, printline takes an argument "justcheckfit" which suppresses
# printing and just returns True or False depending on whether the supplied
# text fits without wrapping
# The method 'checkwidth()' invokes printline with justcheckfit=True
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

def l2s(l):
    return string.join([chr(x) for x in l],"")

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

class nullprinter(object):
    """
    A "dummy" printer that just writes to the log.

    """
    def __init__(self,name=None):
        if name: self._name="nullprinter {}".format(name)
        else: self._name="nullprinter"
        self._started=False
    def __str__(self):
        return "{}(name='{}')".format(self.__class__.__name__,self._name)
    def __enter__(self):
        if self._started: raise PrinterError(self,"Nested call to start()")
        log.info("%s: start",self._name)
        self._started=True
        return self
    def __exit__(self,type,value,tb):
        log.info("%s: end",self._name)
        if not self._started:
            raise PrinterError(self,"end() called without start()")
        self._started=False
    def offline(self):
        return
    def setdefattr(self,colour=None,font=None,emph=None,underline=None):
        pass
    def printline(self,l="",justcheckfit=False,allowwrap=True,
                  colour=None,font=None,emph=None,underline=None):
        if not justcheckfit:
            log.info("%s: printline: %s",self._name,l)
        return True
    def printqrcode(self,code):
        log.info("%s: printqrcode: %s",self._name,code)
    def cancut(self):
        return False
    def checkwidth(self,line):
        return self.printline(l,justcheckfit=True)
    def kickout(self):
        log.info("%s: kickout",self._name)

class badprinter(nullprinter):
    """
    A null printer that always reports it is offline, for testing.

    """
    def offline(self):
        return "badprinter is always offline!"
    def __enter__(self):
        raise PrinterError(self,"badprinter is always offline!")

class fileprinter(object):
    """
    Print to a file.  The file may be a device file!

    """
    def __init__(self,filename,driver):
        self._filename=filename
        self._driver=driver
        self._file=None
    def __str__(self):
        return "{}({},{})".format(self.__class__.__name__,
                                  self._filename,self._driver)
    def offline(self):
        """
        If the printer is unavailable for any reason, return a description
        of that reason; otherwise return None.

        """
        if self._file: return 
        try:
            f=file(self._filename,'a')
            f.close()
        except IOError as e:
            return str(e)
    def __enter__(self):
        if self._file:
            raise PrinterError(self,"Already started in start()")
        self._file=file(self._filename,'a')
        self._driver.start(self._file)
        return self._driver
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
        if sys.platform!="linux2":
            raise PrinterError(
                self,"linux_lpprinter: wrong platform '{}' "
                "(expected 'linux2')".format(sys.platform))
        fileprinter.__init__(self,*args,**kwargs)
    def offline(self):
        if self._file: return 
        try:
            f=file(self._filename,'a')
            buf=array.array(str('b'),[0])
            fcntl.ioctl(f,self.LPGETSTATUS,buf)
            f.close()
            return self._decode_status(buf[0])
        except IOError as e:
            return str(e)

class netprinter(object):
    """
    Print to a network socket.  connection is a (hostname,port) tuple.

    """
    def __init__(self,connection,driver):
        self._connection=connection
        self._driver=driver
        self._socket=None
        self._file=None
    def __str__(self):
        return "netprinter({},{})".format(self._filename,self._driver)
    def offline(self):
        """
        If the printer is unavailable for any reason, return a description
        of that reason; otherwise return None.

        """
        if self._file: return
        host=self._connection[0]
        if not test_ping(host):
            return "Printer {} did not respond to ping".format(host)
    def __enter__(self):
        if self._file:
            raise PrinterError(self,"Already started in start()")
        self._socket=socket.socket(socket.AF_INET)
        self._socket.connect(self._connection)
        self._file=self._socket.makefile('w')
        self._driver.start(self._file)
        return self._driver
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

class tmpfileprinter(object):
    """
    Print to a temporary file.  Call the "finish" method with the
    filename before the file is deleted.  This method does nothing in
    this class: it expected that subclasses will override it.

    """
    def __init__(self,driver):
        self._driver=driver
        self._file=None
    def __str__(self):
        return "tmpfileprinter({})".format(self._driver)
    def offline(self):
        return
    def __enter__(self):
        if self._file:
            raise PrinterError(self,"Already started in start()")
        self._file=tempfile.NamedTemporaryFile(suffix=self._driver.filesuffix)
        self._driver.start(self._file)
        return self._driver
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
    def __init__(self,printcmd,driver):
        tmpfileprinter.__init__(self,driver)
        self._printcmd=printcmd
    def __str__(self):
        return "commandprinter({},{})".format(self._printcmd,self._driver)
    def finish(self,filename):
        with open('/dev/null','w') as null:
            r=subprocess.call(self._printcmd%filename,
                              shell=True,stdout=null,stderr=null)

class cupsprinter(tmpfileprinter):
    """
    Print to a CUPS printer.

    """
    def __init__(self,printername,driver):
        tmpfileprinter.__init__(self,driver)
        self._printername=printername
    def __str__(self):
        return "cupsprinter({},{})".format(self._printername,self._driver)
    def finish(self,filename):
        # XXX it might be a better idea to use python-cups here to
        # submit the job; it could also provide more information for
        # the offline() method.  Using lpr for now provides maximum
        # compatibility.
        with open('/dev/null','w') as null:
            r=subprocess.call("lpr -P {} {}".format(self._printername,filename),
                              shell=True,stdout=null,stderr=null)

def ep_2d_cmd(*params):
    """
    Assemble an ESC/POS 2d barcode command.  params are either 8-bit
    integers or strings, which will be concatenated.  Strings are
    assumed to be sequences of bytes here!

    """
    p=string.join([chr(x) if isinstance(x,int) else x for x in params],"")
    pL=len(p)&0xff
    pH=(len(p)>>8)&0xff
    return string.join([chr(29),'(','k',chr(pL),chr(pH),p],"")

class escpos(object):
    """
    The ESC/POS protocol for controlling receipt printers.

    """
    filesuffix=".dat"
    ep_reset=l2s([27,64,27,116,16])
    ep_pulse=l2s([27,ord('p'),0,50,50])
    ep_underline=(l2s([27,45,0]),l2s([27,45,1]),l2s([27,45,2]))
    ep_emph=(l2s([27,69,0]),l2s([27,69,1]))
    ep_colour=(l2s([27,114,0]),l2s([27,114,1]))
    ep_font=(l2s([27,77,0]),l2s([27,77,1]))
    ep_left=l2s([27,97,0])
    ep_center=l2s([27,97,1])
    ep_right=l2s([27,97,2])
    ep_ff=l2s([27,100,7])
    ep_fullcut=l2s([27,105])
    ep_unidirectional_on=l2s([27,85,1])
    ep_unidirectional_off=l2s([27,85,0])
    ep_bitimage_sd=l2s([27,42,0]) # follow with 16-bit little-endian data length
    ep_short_feed=l2s([27,74,5])
    ep_half_dot_feed=l2s([27,74,1])
    def __init__(self,cpl,dpl,coding,has_cutter=False,
                 lines_before_cut=3,default_font=0,
                 native_qrcode_support=False):
        self.f=None
        self.fontcpl=cpl
        self.dpl=dpl
        self.coding=coding
        self.has_cutter=has_cutter
        self.lines_before_cut=lines_before_cut
        self.default_font=default_font
        self.native_qrcode_support=native_qrcode_support
    def start(self,fileobj):
        self.f=fileobj
        self.colour=0
        self.font=self.default_font
        self.emph=0
        self.underline=0
        self.cpl=self.fontcpl[0]
        self.f.write(escpos.ep_reset)
        self.f.write(escpos.ep_font[self.font])
        self._printed=False
    def end(self):
        if self._printed:
            self.f.write(escpos.ep_ff)
            if self.has_cutter:
                self.f.write('\n'*self.lines_before_cut+escpos.ep_left)
                self.f.write(escpos.ep_fullcut)
            self.f.flush()
        self.f=None
        self._printed=False
    def setdefattr(self,colour=None,font=None,emph=None,underline=None):
        if colour is not None:
            if colour!=self.colour:
                self.colour=colour
                self.f.write(escpos.ep_colour[colour])
        if font is not None:
            if font!=self.font:
                self.font=font
                self.cpl=self.fontcpl[font]
                self.f.write(escpos.ep_font[font])
        if emph is not None:
            if emph!=self.emph:
                self.emph=emph
                self.f.write(escpos.ep_emph[emph])
        if underline is not None:
            if underline!=self.underline:
                self.underline=underline
                self.f.write(escpos.ep_underline[underline])
    def printline(self,l="",justcheckfit=False,allowwrap=True,
                  colour=None,font=None,emph=None,underline=None):
        self._printed=True
        cpl=self.cpl
        if font is not None:
            cpl=self.fontcpl[font]
        s=l.split("\t")
        if len(s)>0: left=s[0]
        else: left=""
        if len(s)>1: center=s[1]
        else: center=""
        if len(s)>2: right=s[2]
        else: right=""
        fits=(len(left)+len(center)+len(right)<=cpl)
        if justcheckfit: return fits
        if not allowwrap and not fits: return False
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

        if center=="":
            ll=lrwrap(left,right,cpl)
            for i in ll:
                self.f.write(("%s\n"%i).encode(self.coding))
        elif left=="" and right=="":
            self.f.write(escpos.ep_center)
            ll=wrap(center,cpl)
            for i in ll:
                self.f.write(("%s\n"%i).encode(self.coding))
            self.f.write(escpos.ep_left)
        else:
            pad=max(cpl-len(left)-len(center)-len(right),0)
            padl=pad/2
            padr=pad-padl
            self.f.write(("%s%s%s%s%s\n"%(
                        left,' '*padl,center,' '*padr,right)).
                         encode(self.coding))
        if colour is not None:
            self.f.write(escpos.ep_colour[self.colour])
        if font is not None:
            self.f.write(escpos.ep_font[self.font])
        if emph is not None:
            self.f.write(escpos.ep_emph[self.emph])
        if underline is not None:
            self.f.write(escpos.ep_underline[self.underline])
        return fits
    def checkwidth(self,line):
        return self.printline(line,justcheckfit=True)
    def printqrcode_native(self,data):
        log.debug("Native QR code print: %d bytes: %s"%(len(data),repr(data)))
        # Set the size of a "module", in dots.  The default is apparently
        # 3 (which is also the lowest).  The maximum is 16.
        
        ms=16
        if self.dpl==420: # 58mm paper width
            if len(data)>14: ms=14
            if len(data)>24: ms=12
            if len(data)>34: ms=11
            if len(data)>44: ms=10
            if len(data)>58: ms=9
            if len(data)>64: ms=8
            if len(data)>84: ms=7
            if len(data)>119: ms=6
            if len(data)>177: ms=5
            if len(data)>250: ms=4
            if len(data)>439: ms=3
            if len(data)>742: return # Too big to print
        else: # 80mm paper width
            if len(data)>34: ms=15
            if len(data)>44: ms=14
            if len(data)>45: ms=13
            if len(data)>58: ms=12
            if len(data)>64: ms=11
            if len(data)>84: ms=10
            if len(data)>119: ms=9
            if len(data)>137: ms=8
            if len(data)>177: ms=7
            if len(data)>250: ms=6
            if len(data)>338: ms=5
            if len(data)>511: ms=4
            if len(data)>790: ms=3
            if len(data)>1273: return # Too big to print
        self.f.write(ep_2d_cmd(49,67,ms))

        # Set error correction:
        # 48 = L = 7% recovery
        # 49 = M = 15% recovery
        # 50 = Q = 25% recovery
        # 51 = H = 30% recovery
        self.f.write(ep_2d_cmd(49,69,51))

        # Send QR code data
        self.f.write(ep_2d_cmd(49,80,48,data))

        # Print the QR code
        self.f.write(ep_2d_cmd(49,81,48))
    def printqrcode(self,data):
        self._printed=True
        if self.native_qrcode_support:
            return self.printqrcode_native(data)
        q=qrcode.QRCode(border=2)
        q.add_data(data)
        code=q.get_matrix()
        self.f.write(escpos.ep_unidirectional_on)
        # To get a good print, we print two rows at a time - but only
        # feed the paper through by one row.  This means that each
        # part of the code should be printed twice.  We're also
        # printing each pair of rows twice, advancing the paper by
        # half a dot inbetween.  We only use 6 of the 8 pins of the
        # printer to keep this code simple.
        lt={
            (False,False): chr(0x00),
            (False,True): chr(0x1c),
            (True,False): chr(0xe0),
            (True,True): chr(0xfc),
            }
        while len(code)>0:
            if len(code)>1:
                row=list(zip(code[0],code[1]))
            else:
                row=list(zip(code[0],[False]*len(code[0])))
            code=code[1:]
            width=len(row)*3
            if width>self.dpl: break # Code too wide for paper
            padding=(self.dpl-width)/2
            width=width+padding
            padchars=chr(0)*padding
            header=escpos.ep_bitimage_sd+chr(width&0xff)+chr((width>>8)&0xff)
            self.f.write(header+padchars+''.join(lt[x]+lt[x]+lt[x] for x in row)
                         +"\r".encode(self.coding))
            self.f.write(escpos.ep_half_dot_feed)
            self.f.write(header+padchars+''.join(lt[x]+lt[x]+lt[x] for x in row)
                         +"\r".encode(self.coding))
            self.f.write(escpos.ep_short_feed)
        self.f.write(escpos.ep_unidirectional_off)
    def kickout(self):
        self.f.write(escpos.ep_pulse)
        self.f.flush()

class Epson_TM_U220_driver(escpos):
    def __init__(self,paperwidth,coding='iso-8859-1',has_cutter=False):
        # Characters per line with fonts 0 and 1
        if paperwidth==57 or paperwidth==58:
            cpl=(25,30)
            dpl=148
        elif paperwidth==76:
            cpl=(33,40)
            dpl=192
        else:
            raise Exception("Unknown paper width")
        escpos.__init__(self,cpl,dpl,coding,has_cutter,
                        default_font=1)

class Epson_TM_T20_driver(escpos):
    def __init__(self,paperwidth,coding='iso-8859-1'):
        # Characters per line with fonts 0 and 1
        if paperwidth==57 or paperwidth==58:
            cpl=(35,46)
            dpl=420
        elif paperwidth==80:
            cpl=(48,64)
            dpl=576
        else:
            raise Exception("Unknown paper width {}".format(paperwidth))
        escpos.__init__(self,cpl,dpl,coding,has_cutter=True,
                        lines_before_cut=0,default_font=0,
                        native_qrcode_support=True)

class pdf_driver(object):
    filesuffix=".pdf"
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
    def start(self,fileobj):
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
    def printline(self,l="",justcheckfit=False,allowwrap=True,
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
        fits=(self.c.stringWidth(l,fontname,fontsize)<self.width)
        if justcheckfit: return fits
        if not allowwrap and not fits: return False
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
        return fits
    def printqrcode(self,code):
        pass
    def cancut(self):
        return False
    def checkwidth(self,line):
        return self.printline(line,justcheckfit=True)
    def kickout(self):
        pass

class pdfpage(object):
    def __init__(self,printcmd,pagesize):
        self.printcmd=printcmd
        self.pagesize=pagesize
    def available(self):
        return True
    def start(self,title="Page"):
        self.tmpfile=tempfile.NamedTemporaryFile(suffix='.pdf')
        self.tmpfilename=self.tmpfile.name
        self.f=canvas.Canvas(self.tmpfilename,pagesize=self.pagesize)
        self.f.setAuthor("quicktill")
        self.f.setTitle(title)
    def newpage(self):
        self.f.showPage()
    def getCanvas(self):
        return self.f
    def end(self):
        self.f.showPage()
        self.f.save()
        del self.f
        os.system(self.printcmd%self.tmpfilename)
        self.tmpfile.close()
        del self.tmpfilename
        del self.tmpfile

class pdflabel(pdfpage):
    def __init__(self,printcmd,labelsacross,labelsdown,
                 labelwidth,labelheight,
                 horizlabelgap,vertlabelgap,
                 pagesize):
        pdfpage.__init__(self,printcmd,pagesize)
        self.width=toLength(labelwidth)
        self.height=toLength(labelheight)
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
    def labels_per_page(self):
        return len(self.ll)
    def start(self,title="Labels"):
        pdfpage.start(self,title)
        self.label=0
    def newpage(self):
        pdfpage.newpage(self)
        self.label=0
    def addlabel(self,function,data):
        # Save the graphics state, move the origin to the bottom-left-hand
        # corner of the label, call the function, then restore.
        if self.label>=len(self.ll): self.newpage()
        pos=self.ll[self.label]
        self.f.saveState()
        self.f.translate(pos[0],pos[1])
        function(self.f,self.width,self.height,data)
        self.f.restoreState()
        self.label=self.label+1


# The remainder of the functions in this file are for compatibility
# with old till config files and should be removed once they have all
# been updated.

def _pick_connection(devicefile):
    if isinstance(devicefile,unicode):
        devicefile=devicefile.encode('ascii')
    if isinstance(devicefile,str):
        return linux_lpprinter
    return netprinter

def Epson_TM_U220(devicefile,paperwidth,coding='iso-8859-1',has_cutter=False):
    return _pick_connection(devicefile)(
        devicefile,Epson_TM_U220_driver(paperwidth,coding,has_cutter=False))

def Epson_TM_T20(devicefile,paperwidth,coding='iso-8859-1'):
    return _pick_connection(devicefile)(
        devicefile,Epson_TM_T20_driver(paperwidth,coding))

def pdf(printcmd,width=140,pagesize=A4,
        fontsizes=[8,10],pitches=[10,12]):
    return commandprinter(printcmd,pdf_driver(width,pagesize,fontsizes,pitches))
