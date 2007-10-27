import td,ui

def menu(func,title,allowall=False):
    # Obtain list of (department,description)
    depts=td.department_list()
    lines=ui.table([("%d"%num,desc) for num,desc in depts]).format(' r l ')
    sl=[(x,func,(y[0],)) for x,y in zip(lines,depts)]
    if allowall:
        sl=[("All departments",func,(None,))]+sl
    ui.menu(sl,title=title,blurb="Choose a department and press Cash/Enter.")
