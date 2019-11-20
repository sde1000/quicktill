from .models import *
from django.contrib import admin

def user_full_name(access):
    return access.user.get_full_name()
user_full_name.short_description = "Name"

class AccessAdmin(admin.ModelAdmin):
    list_filter = ('till',)
    list_display = ('user', user_full_name, 'till', 'permission')

admin.site.register(Till)
admin.site.register(Access, AccessAdmin)
