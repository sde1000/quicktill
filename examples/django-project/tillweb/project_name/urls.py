try:
    from django.conf.urls import patterns, include, url
except ImportError:
    from django.conf.urls.defaults import *

import quicktill.tillweb.urls

from django.contrib import admin
admin.autodiscover()

urlpatterns = patterns(
    '',
    # Examples:
    # url(r'^$', '{{ project_name }}.views.home', name='home'),
    # url(r'^{{ project_name }}/', include('{{ project_name }}.foo.urls')),

    url(r'^admin/doc/', include('django.contrib.admindocs.urls')),
    url(r'^admin/', include(admin.site.urls)),
    url(r'^(?P<pubname>)', include(quicktill.tillweb.urls.tillurls)),
)
