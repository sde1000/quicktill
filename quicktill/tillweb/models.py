from django.db import models
from django.contrib.auth.models import User

from django.urls import reverse


class Till(models.Model):
    """An available till database

    A till database that we want to refer to.  NB the database
    connection must also be defined in the Django settings as a
    SQLAlchemy Session constructor.
    """
    slug = models.SlugField()
    name = models.TextField()
    database = models.TextField()
    money_symbol = models.CharField(max_length=10)

    def get_absolute_url(self):
        return reverse('tillweb-pubroot', args=[self.slug])

    def __str__(self):
        return self.name


PERMISSIONS = (
    ('R', 'Read-only'),
    ('M', 'Read/write, following till permissions'),
    ('F', 'Full access, ignoring till permissions'),
)


class Access(models.Model):
    """Access to a till by a particular user

    Access to a till database by a particular user.  Also encodes the
    type of access they have if they don't exist in the till's user
    database.
    """
    till = models.ForeignKey(Till, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE,
                             related_name="till_access")
    permission = models.CharField(max_length=1, choices=PERMISSIONS)

    class Meta(object):
        unique_together = (("till", "user"),)

    def __str__(self):
        return "%s can access %s %s" % (
            self.user.username, self.till, self.get_permission_display())
