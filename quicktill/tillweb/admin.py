from .models import *
from django.contrib import admin

class AccessAdmin(admin.ModelAdmin):
    list_filter=('till',)
    list_display=('user','till')

admin.site.register(Till)
admin.site.register(Access,AccessAdmin)
