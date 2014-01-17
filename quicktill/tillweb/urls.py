try:
    from django.conf.urls import patterns, include, url
except ImportError:
    from django.conf.urls.defaults import *

tillurls=patterns(
    'quicktill.tillweb.views',

    # Root pub page
    url(r'^$','pubroot'),

    # Item detail pages
    url(r'^session/$','sessionfinder'),
    url(r'^session/(?P<sessionid>\d+)/$','session'),
    url(r'^session/(?P<sessionid>\d+)/dept(?P<dept>\d+)/$','sessiondept',
        name="sessiondept"),
    url(r'^transaction/(?P<transid>\d+)/$','transaction'),
    url(r'^supplier/(?P<supplierid>\d+)/$','supplier'),
    url(r'^delivery/(?P<deliveryid>\d+)/$','delivery'),
    url(r'^stocktype/(?P<stocktype_id>\d+)/$','stocktype'),
    url(r'^stock/(?P<stockid>\d+)/$','stock'),
    url(r'^stockline/(?P<stocklineid>\d+)/$','stockline'),
    url(r'^location/$','locationlist'),
    url(r'^location/(?P<location>[\w\- ]+)/$','location'),
    url(r'^department/$','departmentlist'),
    url(r'^department/(?P<departmentid>\d+)/$','department'),

    # Search pages
    # location (location summary page)
    # sessions (start,end)
    # transactions (search by sessionid,open)
    # deliveries (search by supplier)
    # stocktypes (search by manufacturer,name,dept)
    # stock (search by delivery, dept, etc.)
    # stocklines (search by location, dept, capacity)

    # Fridge summary page?  Possibly stocklines search w/capacity
    # Statistics page?
)

urls=patterns(
    'quicktill.tillweb.views',
    # Index page
    url(r'^$','publist',name="publist"),
    url(r'^(?P<pubname>[\w\-]+)/',include(tillurls)),
)
