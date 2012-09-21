import string
import ui

class magstripe:
    def __init__(self):
        self.t=[[],[],[]]
        self.i=None
    def start_track(self,track):
        self.i=self.t[track-1]
    def end_track(self,track):
        self.i=None
    def handle_input(self,c):
        if self.i is None: return
        self.i.append(c)
    def track(self,t):
        if t<1 or t>3: raise "Bad track"
        return string.join([chr(x) for x in self.t[t-1]],"")
    def __str__(self):
        return "magstripe(%s)"%','.join(
            [self.track(1),self.track(2),self.track(3)])

def infopopup(card):
    l=[]
    l.append("Track 1: %s"%card.track(1))
    l.append("Track 2: %s"%card.track(2))
    l.append("Track 3: %s"%card.track(3))
    ui.linepopup(l,title="Magnetic card info",colour=ui.colour_info)
