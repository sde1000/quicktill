import ui

def infopopup(card):
    l=[]
    l.append("Track 1: %s"%card.track(1))
    l.append("Track 2: %s"%card.track(2))
    l.append("Track 3: %s"%card.track(3))
    ui.linepopup(l,title="Magnetic card info",colour=ui.colour_info)
