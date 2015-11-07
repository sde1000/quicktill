try:
    from django.conf.urls import patterns, include, url
except ImportError:
    from django.conf.urls.defaults import *

tillurls=patterns(
    'quicktill.tillweb.views',

    url(r'^$','pubroot'),
    url(r'^session/$','sessionfinder'),
    url(r'^session/(?P<sessionid>\d+)/$','session'),
    url(r'^session/(?P<sessionid>\d+)/sales-pie-chart.svg$','session_sales_pie_chart'),
    url(r'^session/(?P<sessionid>\d+)/users-pie-chart.svg$','session_users_pie_chart'),
    url(r'^session/(?P<sessionid>\d+)/dept(?P<dept>\d+)/$','sessiondept',
        name="sessiondept"),
    url(r'^transaction/(?P<transid>\d+)/$','transaction'),
    url(r'^supplier/$','supplierlist'),
    url(r'^supplier/(?P<supplierid>\d+)/$','supplier'),
    url(r'^delivery/$','deliverylist'),
    url(r'^delivery/(?P<deliveryid>\d+)/$','delivery'),
    url(r'^stocktype/$','stocktypesearch'),
    url(r'^stocktype/(?P<stocktype_id>\d+)/$','stocktype'),
    url(r'^stock/$','stocksearch'),
    url(r'^stock/(?P<stockid>\d+)/$','stock'),
    url(r'^stockline/$','stocklinelist'),
    url(r'^stockline/(?P<stocklineid>\d+)/$','stockline'),
    url(r'^plu/$','plulist'),
    url(r'^plu/(?P<pluid>\d+)/$','plu'),
    url(r'^location/$','locationlist'),
    url(r'^location/(?P<location>[\w\- ]+)/$','location'),
    url(r'^department/$','departmentlist'),
    url(r'^department/(?P<departmentid>\d+)/$','department'),
    url(r'^stockcheck/$','stockcheck'),
    url(r'^user/$','userlist'),
    url(r'^user/(?P<userid>\d+)/$','user'),
)

urls=patterns(
    'quicktill.tillweb.views',
    # Index page
    url(r'^$','publist',name="publist"),
    url(r'^(?P<pubname>[\w\-]+)/',include(tillurls)),
)
