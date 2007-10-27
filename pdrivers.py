import string,socket

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
# Furthermore, printline takes an argument "checkfit" which suppresses printing
# and just returns True or False depending on whether the supplied text fits
# without wrapping

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
        pass
    def end(self):
        pass
    def cancut(self):
        return False
    def width(self,font=None):
        return 30
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
    def __init__(self,devicefile,cpl):
        if isinstance(devicefile,str):
            self.f=file(devicefile,'w')
            self.ci=None
        else:
            self.f=None
            self.ci=devicefile
        self.fontcpl=cpl
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
            self.f.write(escpos.ep_center+center+"\n"+escpos.ep_left)
        else:
            pad=cpl-len(left)-len(center)-len(right)
            padl=pad/2
            padr=pad-padl
            self.f.write("%s%s%s%s%s\n"%(
                left,' '*padl,center,' '*padr,right))
        if colour is not None:
            self.f.write(escpos.ep_colour[self.colour])
        if font is not None:
            self.f.write(escpos.ep_font[self.font])
        if emph is not None:
            self.f.write(escpos.ep_emph[self.emph])
        if underline is not None:
            self.f.write(escpos.ep_underline[self.underline])
        return fits
    def cancut(self):
        return False
    def width(self,font=None):
        if font==None: font=self.font
        return self.fontcpl[font]
    def kickout(self):
        self.f.write(escpos.ep_pulse)
        self.f.flush()


class Epson_TM_U220(escpos):
    def __init__(self,devicefile,paperwidth):
        # Characters per line with fonts 0 and 1
        if paperwidth==57:
            cpl=(25,30)
        elif paperwidth==76:
            cpl=(33,40)
        else:
            raise "Unknown paper width"
        escpos.__init__(self,devicefile,cpl)
