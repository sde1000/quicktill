quicktill - cash register software
==================================

Copying
-------

quicktill is Copyright (C) 2004-2013 Stephen Early <sde@individualpubs.co.uk>

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

Parts of this program were written by other people and are distributed
under different licences; see the individual source files for details:
 - quicktill/twitter.py - Apache License, version 2.0
 - quicktill/oauth2.py - MIT License

A big warning
-------------

This software is in the middle of being rewritten; it isn't finished,
it isn't tested and it isn't easy to use.  This is the development
branch and isn't being used regularly in live situations!

The stable branch has been in use in a few pubs since 2004 without any
problems, but is becoming difficult to maintain.  The rewrite has
replaced lots of embedded SQL with the sqlalchemy ORM; this enables
the code be rather more readable!  There is also a django-based
reporting interface to the till database that makes use of the ORM
models defined here in quicktill/models.py; it's included in
quicktill/tillweb/ but is out of date.

I intend to start using this branch in one of my pubs (probably the
Pembury) in early 2014, once the "members of staff have NFC ID cards
to bring up their personal page on the register" feature has been
implemented and I'm happy the whole thing is stable.

Getting started
---------------

The first hurdle is finding a suitable keyboard!  I generally use 16x8
matrix keyboards from Preh (MCI128), configured so that on each
keypress they output a sequence of keystrokes giving the coordinates
of the key that was pressed, for example [A01] for the bottom-left and
[G16] for the top-right.  If you have a different type of keyboard, or
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
 - runtill() invokes quicktill.till.start() via the curses wrapper that catches exceptions
   and returns the display to a sane state on exit
 - start() invokes ui.init() with the root window, which sets up colours and the clock/header
 - start() invokes whatever callable was defined as the 'firstpage' config option
 - start() enters the main event loop

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
