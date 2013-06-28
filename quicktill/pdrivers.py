import string,socket,os,tempfile,textwrap,subprocess
from reportlab.pdfgen import canvas
from reportlab.lib.units import toLength
from reportlab.lib.pagesizes import A4
import qrcode
import logging
log=logging.getLogger()

# Methods a printer class should implement:
# available - returns True if start/print/end is likely to succeed
#  (eg. checks network connection on network printers)
# start - set up for printing; might do nothing
# setdefattr - set default attributes for subsequent lines
# printline - print a line.  Text up to first \t is left-justified;
#  text up to second \t is centered; text after that is right-aligned
# end - form feed, cut if hardware supports it
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

# Might implement kickout() if kickout goes through printer

def test_ping(host):
    """
    Check whether a host is alive using ping; returns True if it is alive.

    """
    null=open('/dev/null','w')
    r=subprocess.call("ping -q -w 2 -c 1 %s"%host,
                      shell=True,stdout=null,stderr=null)
    null.close()
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

class nullprinter:
    def available(self):
        return True
    def start(self):
        pass
    def setdefattr(self,colour=None,font=None,emph=None,underline=None):
        pass
    def printline(self,l="",justcheckfit=False,allowwrap=True,
                  colour=None,font=None,emph=None,underline=None):
        return True
    def printqrcode(self,code):
        pass
    def end(self):
        pass
    def cancut(self):
        return False
    def checkwidth(self,line):
        return self.printline(l,justcheckfit=True)
    def kickout(self):
        pass

def ep_2d_cmd(*params):
    """
    Assemble a 2d barcode command.  params are either 8-bit integers
    or strings, which will be concatenated.  Strings are assumed to be
    sequences of bytes here!

    """
    p=string.join([chr(x) if isinstance(x,int) else x for x in params],"")
    pL=len(p)&0xff
    pH=(len(p)>>8)&0xff
    return string.join([chr(29),'(','k',chr(pL),chr(pH),p],"")

class escpos:
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
    def __init__(self,devicefile,cpl,dpl,coding,has_cutter=False,
                 lines_before_cut=3,default_font=0):
        if isinstance(devicefile,str):
            self.f=file(devicefile,'w')
            self.ci=None
        else:
            self.f=None
            self.ci=devicefile
        self.fontcpl=cpl
        self.dpl=dpl
        self.coding=coding
        self.has_cutter=has_cutter
        self.lines_before_cut=lines_before_cut
        self.default_font=default_font
    def available(self):
        if self.f: return True
        host=self.ci[0]
        return test_ping(host)
    def start(self):
        if self.f is None:
            self.s=socket.socket(socket.AF_INET)
            self.s.connect(self.ci)
            self.f=self.s.makefile('w')
        self.colour=0
        self.font=self.default_font
        self.emph=0
        self.underline=0
        self.cpl=self.fontcpl[0]
        self.f.write(escpos.ep_reset)
        self.f.write(escpos.ep_font[self.font])
    def end(self):
        self.f.write(escpos.ep_ff)
        if self.has_cutter:
            self.f.write('\n'*self.lines_before_cut+escpos.ep_left)
            self.f.write(escpos.ep_fullcut)
        self.f.flush()
        if self.ci is not None:
            self.f.close()
            self.s.close()
            self.f=None
            self.s=None
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
    def printqrcode(self,data):
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
                row=zip(code[0],code[1])
            else:
                row=zip(code[0],[False]*len(code[0]))
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
        if self.f is None:
            self.s=socket.socket(socket.AF_INET)
            self.s.connect(self.ci)
            self.f=self.s.makefile('w')
        self.f.write(escpos.ep_pulse)
        self.f.flush()
        if self.ci is not None:
            self.f.close()
            self.s.close()
            self.f=None
            self.s=None

class Epson_TM_U220(escpos):
    def __init__(self,devicefile,paperwidth,coding='iso-8859-1',
                 has_cutter=False):
        # Characters per line with fonts 0 and 1
        if paperwidth==57 or paperwidth==58:
            cpl=(25,30)
            dpl=148
        elif paperwidth==76:
            cpl=(33,40)
            dpl=192
        else:
            raise Exception("Unknown paper width")
        escpos.__init__(self,devicefile,cpl,dpl,coding,has_cutter,
                        default_font=1)

class Epson_TM_T20(escpos):
    def __init__(self,devicefile,paperwidth,coding='iso-8859-1'):
        # Characters per line with fonts 0 and 1
        if paperwidth==57 or paperwidth==58:
            cpl=(35,46)
            dpl=420
        elif paperwidth==80:
            cpl=(48,64)
            dpl=576
        else:
            raise Exception("Unknown paper width")
        escpos.__init__(self,devicefile,cpl,dpl,coding,has_cutter=True,
                        lines_before_cut=0,default_font=0)
    def printqrcode(self,data):
        log.debug("QR code print: %d bytes: %s"%(len(data),repr(data)))
        # Set the size of a "module", in dots.  The default is apparently
        # 3 (which is also the lowest).  The maximum is 16.
        
        # Note that these figures are for 58mm paper width.  I have
        # not yet had a chance to calibrate for 80mm paper width.
        ms=16
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

class pdf:
    def __init__(self,printcmd,width=140,pagesize=A4,
                 fontsizes=[8,10],pitches=[10,12]):
        """
        printcmd is the name of the shell command that will be invoked
        with the filename of the PDF

        width is the width of the output in points

        """
        
        self.printcmd=printcmd
        self.width=width
        self.pagesize=pagesize
        self.pagewidth=pagesize[0]
        self.pageheight=pagesize[1]
        self.fontsizes=fontsizes
        self.pitches=pitches
        self.leftmargin=40
    def available(self):
        return True
    def start(self):
        self.tmpfile=tempfile.NamedTemporaryFile(suffix='.pdf')
        self.tmpfilename=self.tmpfile.name
        self.c=canvas.Canvas(self.tmpfilename,pagesize=self.pagesize)
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
        os.system(self.printcmd%self.tmpfilename)
        self.tmpfile.close()
        del self.tmpfilename
        del self.tmpfile
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

class pdfpage:
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
