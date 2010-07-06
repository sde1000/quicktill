import string,socket,os,tempfile
from reportlab.pdfgen import canvas
from reportlab.lib.units import toLength
from reportlab.lib.pagesizes import A4

# Methods a printer class should implement:
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

def l2s(l):
    return string.join([chr(x) for x in l],"")

def lr(l,r,w):
    w=w-len(l)-len(r)
    return "%s%s%s\n"%(l,' '*w,r)

def r(r,w):
    return "%s%s\n"%(" "*(w-len(r)),r)

class nullprinter:
    def start(self):
        pass
    def setdefattr(self,colour=None,font=None,emph=None,underline=None):
        pass
    def printline(self,l="",justcheckfit=False,allowwrap=True,
                  colour=None,font=None,emph=None,underline=None):
        return True
    def end(self):
        pass
    def cancut(self):
        return False
    def fullcut(self):
        pass
    def checkwidth(self,line):
        return self.printline(l,justcheckfit=True)
    def kickout(self):
        pass

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
    def __init__(self,devicefile,cpl,coding,has_cutter=False):
        if isinstance(devicefile,str):
            self.f=file(devicefile,'w')
            self.ci=None
        else:
            self.f=None
            self.ci=devicefile
        self.fontcpl=cpl
        self.coding=coding
        self.has_cutter=has_cutter
    def start(self):
        if self.f is None:
            self.s=socket.socket(socket.AF_INET)
            self.s.connect(self.ci)
            self.f=self.s.makefile('w')
        self.colour=0
        self.font=0
        self.emph=0
        self.underline=0
        self.cpl=self.fontcpl[0]
        self.f.write(escpos.ep_reset)
        self.f.write(escpos.ep_font[0])
    def end(self):
        self.f.write(escpos.ep_ff)
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
        fits=(len(l)<=cpl)
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
        s=l.split("\t")
        if len(s)>0: left=s[0]
        else: left=""
        if len(s)>1: center=s[1]
        else: center=""
        if len(s)>2: right=s[2]
        else: right=""
        # Special case: if there's only centered text, send the control code
        # for centering.  Otherwise line up with spaces.
        if left=="" and center!="" and right=="":
            self.f.write(escpos.ep_center)
            self.f.write(center.encode(self.coding))
            self.f.write("\n"+escpos.ep_left)
        else:
            pad=cpl-len(left)-len(center)-len(right)
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
    def fullcut(self):
        if self.has_cutter:
            self.f.write('\n'*7+escpos.ep_left)
            self.f.write(escpos.ep_fullcut)
            self.f.flush()
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
        if paperwidth==57:
            cpl=(25,30)
        elif paperwidth==76:
            cpl=(33,40)
        else:
            raise "Unknown paper width"
        escpos.__init__(self,devicefile,cpl,coding,has_cutter)

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
