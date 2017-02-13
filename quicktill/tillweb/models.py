from __future__ import unicode_literals
from django.utils.encoding import python_2_unicode_compatible

from django.db import models
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse

def get_app_details(user):
    tills = Till.objects.filter(access__user=user)
    if len(tills) > 0:
        return [{'name': "Till access",
                 'url': reverse('quicktill.tillweb.views.publist'),
                 'objects': tills}]
    return []

@python_2_unicode_compatible
class Till(models.Model):
    """An available till database

    A till database that we want to refer to.  NB the database
    connection must also be defined in the Django settings as a
    SQLAlchemy Session constructor.
    """
    slug = models.SlugField()
    name = models.TextField()
    database = models.TextField()

    def get_absolute_url(self):
        return reverse('quicktill.tillweb.views.pubroot', args=[self.slug])

    def __str__(self):
        return self.name

    def nav(self):
        return [self]

    def navtext(self):
        return "%s till" % (self.name,)

PERMISSIONS = (
    ('R', 'Read-only'),
    ('M', 'Pub manager'),
    ('F', 'Full access'),
)

@python_2_unicode_compatible
class Access(models.Model):
    """Access to a till by a particular user

    Access to a till database by a particular user.  Also encodes the
    type of access they have if they don't exist in the till's user
    database.
    """
    till = models.ForeignKey(Till)
    user = models.ForeignKey(User, related_name="till_access")
    permission = models.CharField(max_length=1, choices=PERMISSIONS)

    class Meta(object):
        unique_together = ( ("till", "user"), )

    def __str__(self):
        return "%s can access %s %s" % (
            self.user.username, self.till, self.get_permission_display())
