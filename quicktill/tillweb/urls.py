from django.conf.urls.defaults import *
from django.views.generic.simple import direct_to_template
from django.views.generic import list_detail

tillurls=patterns(
    'quicktill.tillweb.views',

    # Root pub page
    (r'^$','pubroot'),

    # Item detail pages
    (r'^session/(?P<sessionid>\d+)/$','session'),
    (r'^session/(?P<sessionid>\d+)/dept(?P<dept>\d+)/$','sessiondept'),
    (r'^transaction/(?P<transid>\d+)/$','transaction'),
    (r'^supplier/(?P<supplierid>\d+)/$','supplier'),
    (r'^delivery/(?P<deliveryid>\d+)/$','delivery'),
    (r'^stocktype/(?P<stocktype_id>\d+)/$','stocktype'),
    (r'^stock/(?P<stockid>\d+)/$','stock'),
    (r'^stockline/(?P<stocklineid>\d+)/$','stockline'),

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
    (r'^$','publist'),
    (r'^(?P<pubname>[\w\-]+)/',
     include(tillurls)),
)
