from django.conf.urls import include, url
from quicktill.tillweb.views import *

tillurls = [
    url(r'^$', pubroot, name="tillweb-pubroot"),
    url(r'^session/$', sessionfinder),
    url(r'^session/(?P<sessionid>\d+)/', include([
        url(r'^$', session),
        url(r'^spreadsheet.ods$', session_spreadsheet),
        url(r'^takings-by-dept.html$', session_takings_by_dept),
        url(r'^takings-by-user.html$', session_takings_by_user),
        url(r'^stock-sold.html$', session_stock_sold),
        url(r'^transactions.html$', session_transactions),
        url(r'^sales-pie-chart.svg$', session_sales_pie_chart),
        url(r'^users-pie-chart.svg$', session_users_pie_chart),
        url(r'^dept(?P<dept>\d+)/$', sessiondept, name="sessiondept"),
        ])),
    url(r'^transaction/(?P<transid>\d+)/$', transaction),
    url(r'^transline/(?P<translineid>\d+)/$', transline),
    url(r'^supplier/$', supplierlist),
    url(r'^supplier/(?P<supplierid>\d+)/$', supplier),
    url(r'^delivery/$', deliverylist),
    url(r'^delivery/(?P<deliveryid>\d+)/$', delivery),
    url(r'^stocktype/$', stocktypesearch),
    url(r'^stocktype/(?P<stocktype_id>\d+)/$', stocktype),
    url(r'^stock/$', stocksearch),
    url(r'^stock/(?P<stockid>\d+)/$', stock),
    url(r'^stockline/$', stocklinelist),
    url(r'^stockline/(?P<stocklineid>\d+)/$', stockline),
    url(r'^plu/$', plulist),
    url(r'^plu/(?P<pluid>\d+)/$', plu),
    url(r'^location/$', locationlist),
    url(r'^location/(?P<location>[\w\- ]+)/$', location),
    url(r'^department/$', departmentlist),
    url(r'^department/(?P<departmentid>\d+)/$', department),
    url(r'^stockcheck/$', stockcheck),
    url(r'^user/$', userlist),
    url(r'^user/(?P<userid>\d+)/$', user),
]

urls = [
    # Index page
    url(r'^$', publist, name="tillweb-publist"),
    url(r'^(?P<pubname>[\w\-]+)/', include(tillurls)),
]
