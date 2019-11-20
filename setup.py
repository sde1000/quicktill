#!/usr/bin/env python3

from distutils.core import setup

setup(name='quicktill16',
      version='16.2',
      description='Quick till and stock control library',
      author='Stephen Early',
      author_email='steve@assorted.org.uk',
      url='https://github.com/sde1000/quicktill',
      packages=['quicktill', 'quicktill.tillweb',
                'quicktill.tillweb.migrations'],
      package_data={'quicktill.tillweb':
                    ['static/tillweb/*.js', 'templates/tillweb/*.html',
                     'templates/tillweb/*.ajax',
                     'static/tillweb/*.css', 'static/tillweb/images/*']},
      scripts=['runtill'],
)
