import ui,keyboard,printer,tillconfig,event
import HTMLParser
import urllib
import traceback,sys,os,time,datetime

### Train departures

# How to parse the live departure boards page:
#
# 1) Watch for the start of a table with attr class='arrivaltable'
# 2) Watch for the start of a tbody tag
# 3) For each tr tag, store the td tag contents
# 4) Stop when we get to the end of the tbody tag

class LDBParser(HTMLParser.HTMLParser):
    """Parse the UK National Rail Live Departure Boards web page
    to extract the table of destinations and departure times.

    """
    # Possible states:
    # 0 - waiting for start of table of class 'arrivaltable'
    # 1 - waiting for a tbody tag start
    # 2 - waiting for a tr tag start or a tbody tag end
    # 3 - waiting for a td tag start or a tr tag end
    # 4 - collecting data, waiting for a td tag end
    # 5 - finished
    def __init__(self):
        HTMLParser.HTMLParser.__init__(self)
        self.state=0
        self.tablelines=[]
        self.currentline=None
        self.currentdata=None
    def handle_starttag(self,tag,attrs):
        if self.state==0 and tag=='table' and ('class','arrivaltable') in attrs:
            self.state=1
        elif self.state==1 and tag=='tbody':
            self.state=2
        elif self.state==2 and tag=='tr':
            self.state=3
            self.currentline=[]
        elif self.state==3 and tag=='td':
            self.state=4
            self.currentdata=""
    def handle_endtag(self,tag):
        if self.state==4 and tag=='td':
            self.state=3
            self.currentline.append(self.currentdata)
        elif self.state==3 and tag=='tr':
            self.state=2
            self.tablelines.append(self.currentline)
        elif self.state==2 and tag=='tbody':
            self.state=5
    def handle_data(self,data):
        if self.state==4:
            self.currentdata=self.currentdata+data

class departurelist:
    def __init__(self,name,code):
        # Retrieve the departure boards page
        try:
            f=urllib.urlopen("http://www.livedepartureboards.co.uk/ldb/sumdep.aspx?T=%s&A=1"%code)
            l=f.read()
            f.close()
        except:
            ui.infopopup(["Departure information could not be retrieved."],
                         title="Error")
            return
        # Parse it
        p=LDBParser()
        try:
            p.feed(l)
            p.close()
        except:
            e=traceback.format_exception(sys.exc_type,sys.exc_value,
                                         sys.exc_traceback)
            ui.infopopup(e,title="There is a problem with the web page")
        # Now p.tablelines contains the data!  Format and display it.
        self.tablelines=[x for x in p.tablelines if len(x)>=3]
        self.station=name
        t=ui.table(self.tablelines)
        ll=t.format('l l l')
        if ll==[]: ll=["No train information available."]
        ui.linepopup(ll,name,colour=ui.colour_info,dismiss=keyboard.K_CASH,
                     keymap={keyboard.K_PRINT:(self.printout,None,False)})
    def printout(self):
        p=printer.driver
        destinations={}
        for i in self.tablelines:
            if i[0] not in destinations:
                destinations[i[0]]=[]
            destinations[i[0]].append((i[1],i[2]))
        p.start()
        p.setdefattr(font=1)
        p.printline("\t%s"%tillconfig.pubname,emph=1)
        for i in tillconfig.pubaddr:
            p.printline("\t%s"%i,colour=1)
        p.printline("\tTel. %s"%tillconfig.pubnumber)
        p.printline()
        if not p.printline("Departures from %s"%self.station,
                           colour=1,emph=1,allowwrap=False):
            p.printline("Departures from",colour=1,emph=1)
            p.printline("  %s"%self.station,colour=1,emph=1)
        p.printline("Printed %s"%ui.formattime(ui.now()))
        p.printline()
        d=destinations.keys()
        d.sort()
        for i in d:
            p.printline(i,colour=1)
            for j in destinations[i]:
                p.printline("  %s %s"%j)
        p.end()
    

### Bar Billiards checker

class bbcheck(ui.dismisspopup):
    """Given the amount of money taken by a machine and the share of it
    retained by the supplier, print out the appropriate figures for
    the collection receipt.

    """
    def __init__(self,share=25.0):
        ui.dismisspopup.__init__(self,6,20,title="Bar Billiards check",
                                 dismiss=keyboard.K_CLEAR,
                                 colour=ui.colour_input)
        self.addstr(2,2,"   Total gross:")
        self.addstr(3,2,"Supplier share:")
        self.grossfield=ui.editfield(
            2,18,5,validate=ui.validate_float,keymap={
                keyboard.K_CLEAR: (self.dismiss,None)})
        self.sharefield=ui.editfield(
            3,18,5,validate=ui.validate_float,keymap={
                keyboard.K_CASH: (self.enter,None,False)})
        self.sharefield.set(str(share))
        ui.map_fieldlist([self.grossfield,self.sharefield])
        self.grossfield.focus()
    def enter(self):
        pdriver=printer.driver
        try:
            grossamount=float(self.grossfield.f)
        except:
            grossamount=None
        try:
            sharepct=float(self.sharefield.f)
        except:
            sharepct=None
        if grossamount is None or sharepct is None:
            return ui.infopopup(["You must fill in both fields."],
                                title="You Muppet")
        if sharepct>=100.0 or sharepct<0.0:
            return ui.infopopup(["The supplier share is a percentage, "
                                 "and must be between 0 and 100."],
                                title="You Muppet")
        balancea=grossamount/(tillconfig.vatrate+1.0)
        vat_on_nett_take=grossamount-balancea
        supplier_share=balancea*sharepct/100.0
        brewery_share=balancea-supplier_share
        vat_on_rent=supplier_share*tillconfig.vatrate
        left_on_site=brewery_share+vat_on_nett_take-vat_on_rent
        banked=supplier_share+vat_on_rent
        pdriver.start()
        pdriver.setdefattr(font=1)
        pdriver.printline("Nett take:\t\t%s"%tillconfig.fc(grossamount))
        pdriver.printline("VAT on nett take:\t\t%s"%tillconfig.fc(vat_on_nett_take))
        pdriver.printline("Balance A/B:\t\t%s"%tillconfig.fc(balancea))
        pdriver.printline("Supplier share:\t\t%s"%tillconfig.fc(supplier_share))
        pdriver.printline("Licensee share:\t\t%s"%tillconfig.fc(brewery_share))
        pdriver.printline("VAT on rent:\t\t%s"%tillconfig.fc(vat_on_rent))
        pdriver.printline("(VAT on rent is added to")
        pdriver.printline("'banked' column and subtracted")
        pdriver.printline("from 'left on site' column.)")
        pdriver.printline("Left on site:\t\t%s"%tillconfig.fc(left_on_site))
        pdriver.printline("Banked:\t\t%s"%tillconfig.fc(banked))
        pdriver.end()
        self.dismiss()

### Coffee pot timer

class coffeealarm:
    def __init__(self,timestampfilename):
        self.tsf=timestampfilename
        self.update()
        event.eventlist.append(self)
    def update(self):
        try:
            sd=os.stat(self.tsf)
            self.nexttime=float(sd.st_mtime)
        except:
            self.nexttime=None
    def setalarm(self,timeout):
        "timeout is in seconds"
        now=time.time()
        self.nexttime=now+timeout
        f=file(self.tsf,'w')
        f.close()
        os.utime(self.tsf,(now,self.nexttime))
    def clearalarm(self):
        self.nexttime=None
        os.remove(self.tsf)
    def alarm(self):
        if self.nexttime==None: return
        self.clearalarm()
        ui.alarmpopup(title="Coffee pot alarm",
                      text=["Please empty out and clean the coffee pot - the "
                      "coffee in it is now too old."],
                      colour=ui.colour_info,dismiss=keyboard.K_DEPT11)

class managecoffeealarm(ui.dismisspopup):
    def __init__(self,alarminstance):
        self.ai=alarminstance
        remaining=None if self.ai.nexttime is None else self.ai.nexttime-time.time()
        ui.dismisspopup.__init__(self,8,40,title="Coffee pot alarm",
                                 dismiss=keyboard.K_CLEAR,
                                 colour=ui.colour_input)
        if remaining is None:
            self.addstr(2,2,"No alarm is currently set.")
        else:
            self.addstr(2,2,"Remaining time: %d minutes %d seconds"%(
                    remaining/60,remaining%60))
        self.addstr(3,2,"      New time:")
        self.addstr(3,22,"minutes")
        if remaining is not None:
            self.addstr(5,2,"Press Cancel to clear the alarm.")
        self.timefield=ui.editfield(
            3,18,3,validate=ui.validate_int,keymap={
                keyboard.K_CASH: (self.enter,None,False),
                keyboard.K_CANCEL: (self.clearalarm,None,False)})
        self.timefield.set("60") # Default time
        self.timefield.focus()
    def enter(self):
        try:
            timeout=int(self.timefield.f)*60
        except:
            return
        self.ai.setalarm(timeout)
        self.dismiss()
    def clearalarm(self):
        self.ai.clearalarm()
        self.dismiss()

### Reminders at particular times of day
class reminderpopup:
    def __init__(self,alarmtime,title,text,colour=ui.colour_info,
                 dismiss=keyboard.K_CANCEL):
        """

        Alarmtime is a tuple of (hour,minute).  It will be interpreted
        as being in local time; each time the alarm goes off it will
        be reinterpreted.

        """
        self.alarmtime=alarmtime
        self.title=title
        self.text=text
        self.colour=colour
        self.dismisskey=dismiss
        self.setalarm()
        event.eventlist.append(self)
    def setalarm(self):
        # If the alarm time has already passed today, we set the alarm for
        # the same time tomorrow
        atime=datetime.time(*self.alarmtime)
        candidate=datetime.datetime.combine(datetime.date.today(),atime)
        if time.mktime(candidate.timetuple())<=time.time():
            candidate=candidate+datetime.timedelta(1,0,0)
        self.nexttime=time.mktime(candidate.timetuple())
    def alarm(self):
        ui.alarmpopup(title=self.title,text=self.text,
                      colour=self.colour,dismiss=self.dismisskey)
        self.setalarm()
