from __future__ import unicode_literals
from . import td,ui
from .models import Department

def menu(func,title,allowall=False):
    depts=td.s.query(Department).order_by(Department.id).all()
    f=ui.tableformatter(' r l ')
    lines=[(f(d.id,d.description),func,(d.id,)) for d in depts]
    if allowall:
        lines.insert(0,("All departments",func,(None,)))
    ui.menu(lines,title=title,blurb="Choose a department and press Cash/Enter.")
