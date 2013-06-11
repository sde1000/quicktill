from . import td,ui
from .models import Department

def menu(func,title,allowall=False):
    depts=td.s.query(Department).all()
    lines=ui.table([("%d"%d.id,d.description) for d in depts]).format(' r l ')
    sl=[(x,func,(y.id,)) for x,y in zip(lines,depts)]
    if allowall:
        sl=[("All departments",func,(None,))]+sl
    ui.menu(sl,title=title,blurb="Choose a department and press Cash/Enter.")
