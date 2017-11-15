# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Access',
            fields=[
                ('id', models.AutoField(serialize=False, verbose_name='ID', primary_key=True, auto_created=True)),
                ('permission', models.CharField(max_length=1, choices=[('R', 'Read-only'), ('M', 'Pub manager'), ('F', 'Full access')])),
            ],
        ),
        migrations.CreateModel(
            name='Till',
            fields=[
                ('id', models.AutoField(serialize=False, verbose_name='ID', primary_key=True, auto_created=True)),
                ('slug', models.SlugField()),
                ('name', models.TextField()),
                ('database', models.TextField()),
            ],
        ),
        migrations.AddField(
            model_name='access',
            name='till',
            field=models.ForeignKey(to='tillweb.Till', on_delete=models.CASCADE),
        ),
        migrations.AddField(
            model_name='access',
            name='user',
            field=models.ForeignKey(related_name='till_access', to=settings.AUTH_USER_MODEL, on_delete=models.CASCADE),
        ),
        migrations.AlterUniqueTogether(
            name='access',
            unique_together=set([('till', 'user')]),
        ),
    ]
