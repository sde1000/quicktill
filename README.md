quicktill — cash register software
==================================

Copying
-------

quicktill is Copyright (C) 2004–2016 Stephen Early <sde@individualpubs.co.uk>

It is distributed under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see [this
link](http://www.gnu.org/licenses/).

A big warning
-------------

This software is not very easy to configure.  Once it's configured,
though, it's generally quite easy for staff to use.  It's currently in
use by [Individual Pubs Ltd](https://www.individualpubs.co.uk/) in all
their pubs.  It's occasionally used by
[EMFcamp](https://www.emfcamp.org/) and [London
Hackspace](https://london.hackspace.org.uk/).

At the moment I'm not guaranteeing that changes from one release to
the next won't break existing configuration files, although I aim to
avoid this where possible.  The database schema can also change; SQL
commands to update existing databases are shown in commit messages.
Generally schema changes can be made before installing the updated
release, and won't affect older versions of the software; config file
changes must be made after installing newer versions of the software
and aren't backward-compatible.  (So, to upgrade smoothly: make
database schema changes, install the new version, then update the
config file to enable any new features you need.)

Getting started
---------------

The first hurdle is finding a suitable keyboard!  I generally use 16x8
matrix keyboards from Preh (MCI128), configured so that on each
keypress they output a sequence of keystrokes giving the coordinates
of the key that was pressed, for example [A01] for the bottom-left and
[H16] for the top-right.  If you have a different type of keyboard, or
it is set up differently, it's fairly easy to write a new keyboard
driver: see quicktill/kbdrivers.py

quicktill is quite a complicated program to configure.  You should
start with an example configuration file, examples/haymakers.py, and
edit it according to your needs.

You must create a postgresql database and make it accessible to
whichever user is running the till software.  Name this database in
the configuration file.

Put a URL pointing at the config file in /etc/quicktill/configurl
(eg. file:///home/till/configweb/haymakers.py)

Create database tables:

    runtill syncdb

Get a draft database setup file and edit it:

    runtill dbsetup >database-config
    (edit database-config)
    runtill dbsetup database-config

Create initial users; these will be superusers that can do anything,
you can use the user management interface once the till is running to
restrict them once you have other users set up:

    runtill adduser "Built-in Alice" Alice builtin:alice
    runtill adduser "Built-in Bob" Bob builtin:bob

Run in "stock control terminal" mode and enter your initial stock
(this mode doesn't require a special keyboard)

    runtill start

Run in "cash register" mode, create stocklines, bind them to keys, put
your stock on sale, and sell it:

    runtill -c mainbar start

Set up the built-in web server: install nginx and uwsgi, then create
the django project:

    apt-get install nginx-full uwsgi-plugin-python python-django
    django-admin startproject --template=quicktill/examples/django-project tillweb

Edit the created tillweb/tillweb/tillweb/settings.py file for your
pubname and database, then start the server:

    tillweb/start-daemon

Put tillweb/start-daemon in crontab to start on reboot.

Startup procedure
-----------------

 - runtill script calls quicktill.till.main()
 - main() reads /etc/quicktill/configurl if possible to find default config file location
 - main() parses command line options (overriding config file location if necessary)
 - main() reads config file and executes it as a python module "globalconfig", with
   globalconfig.configname set from the command line (or "default" if not supplied)
 - main() looks for globalconfig.configurations[configname] and bails if not found
 - main() sets up logging based on command line options
 - main() looks for keys in globalconfig.configurations[configname] and sets parameters
   throughout the library (mostly in tillconfig, but some in eg. printer)
 - main() runs the command that was specified on the command line

Assuming the command was "start":

 - quicktill.till.runtill() initialises the database engine
 - runtill() invokes quicktill.run(), which invokes
   quicktill.ui._init() via the curses wrapper that catches exceptions
   and returns the display to a sane state on exit
 - quicktill.ui._init() enters the main event loop

Another useful command is "dbshell", which starts an interactive
python interpreter with a database connection already set up, a
session started, and the td module and models.* already imported.  So
for example, to get a list of departments:

    >>> td.s.query(Department).all()

A list of transactions in the current session:

    >>> Session.current(td.s).transactions

A list of sessions and their totals (in a single round-trip to the
database):

    >>> from sqlalchemy.orm import undefer
    >>> [(x,x.total) for x in td.s.query(Session).options(undefer('total')).all()]
