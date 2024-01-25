quicktill — cash register software
==================================

Copying
-------

quicktill is Copyright (C) 2004–2024 Stephen Early <steve@assorted.org.uk>

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

Features
--------

 * Any number of departments, products, price lookups, users, etc.

 * Products sold can be entered through keys on a keyboard, on-screen
   buttons, or barcode scans

 * Works on multiple terminals at once; transactions follow users
   between terminals

 * Web interface for reporting and management

 * Flexible discount policies, and reporting on discounts given

 * [Xero](https://www.xero.com/) integration

 * [Square Terminal](https://developer.squareup.com/docs/terminal-api/overview) integration

It should be possible to run this software on any system that supports
Python 3.8.  Usually it runs on Debian-derived Linux systems.

Misfeatures
-----------

 * Lack of documentation — you're reading it now!

 * Only one developer at the moment

 * Arguably: Configuration is written in python (although there is an
   ongoing effort to move configuration into the database)

Quick start
-----------

The till software includes an anonymised copy of the database from
[EMFcamp 2022](https://www.emfcamp.org/) which can be used for
testing.  This guide assumes you have a fresh installation of Ubuntu
20.04 Desktop.  (You will need a graphical user interface for the
on-screen keyboard, and the Desktop version has the "universe"
component enabled by default.)

### Installing needed packages ###

In a terminal window, run the following to install packages the till
software needs:

    sudo apt install git postgresql python3-sqlalchemy
    sudo apt install python3-dateutil python3-psycopg2

### Configuring postgres ###

We need to set up postgres to allow your user account to create new
databases.  This procedure may vary from system to system, but on
Debian-derived Linux systems will go something like this:

    sudo -u postgres createuser -d your-username

You will need to substitute your own username for "your-username".

If you don't want to give your user account permission to create new
databases, you could [use the instructions
here](https://wiki.debian.org/PostgreSql) to do something more
restricted.

### Obtaining the till software and test data ###

We will create a clone of the till software from github:

    git clone https://github.com/sde1000/quicktill.git

This puts the till software in a directory called "quicktill".  From
now on we'll assume that this is your current working directory:

    cd quicktill

To create a database and install the test data in it:

    createdb emfcamp
    psql emfcamp <examples/data/emfcamp2022-anonymised.sql

If in the future you need to go back to the original version of the
test data, you can delete the database using "dropdb emfcamp" and
repeat the above two commands.

### Running the till software ###

Check that the till software runs:

    ./runtill --help

The software can run in a number of different modes, defined in the
configuration file.  We're going to be using the configuration file
`examples/emfcamp.py`.  The commands shown here will specify this on
the command line using the `-u` option.

The till software can also run both in its own window or in the
terminal window you're using to start it.  For a separate window give
the `--gtk` option after the word `start` on the command line; to run
in the terminal, leave it out.

To run the till software in "Stock Terminal" mode:

    ./runtill -u file:examples/emfcamp.py start --gtk

To run the till software in "Main bar" mode:

    ./runtill -u file:examples/emfcamp.py -c mainbar start --gtk --keyboard

At some sites the till software is used with a matrix keyboard, but
these are pricey and hard to get hold of.  The `--keyboard` option
makes the till software display an on-screen keyboard instead.

Once the till software is running, you can exit it by pressing the
"Manage Till" button (or 'M' if there's no on-screen keyboard) and
picking option 8.


Using the till software for your own site
-----------------------------------------

To use this software for your own site, you will have to write a new
configuration file.  It's easiest to do this by copying one of the
example configuration files (eg. `examples/emfcamp.py`) and changing
it.  Once the software is configured, it's generally quite easy for
staff to use.  It's currently in use by [Individual Pubs
Ltd](https://www.individualpubs.co.uk/) in all their pubs.  It's
occasionally used by [EMFcamp](https://www.emfcamp.org/) and [London
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

Hardware
--------

You can use a physical matrix keyboard, or an on-screen keyboard with
a touchscreen.  I generally use 16x8 matrix keyboards from Preh
(MCI128), configured so that on each keypress they output a sequence
of keystrokes giving the coordinates of the key that was pressed, for
example [A01] for the bottom-left and [H16] for the top-right.  If you
have a different type of keyboard, or it is set up differently, it's
fairly easy to write a new keyboard driver: see
`quicktill/kbdrivers.py`

The software needs some way of identifying users.  By default, there
are three buttons at the top-left of the keyboard that can be used to
log users in.  If you have a keyboard with a magstripe reader, you can
use magstripe cards to enable users to log in.  At my sites we use
ACR122U NFC readers along with [some simple driver
software](https://github.com/sde1000/quicktill-nfc-bridge) (which
should be able to support any CCID compatible NFC reader).

Receipt printers are supported (and required, if you want to use a
cash drawer).  The software has generic support for all ESC/POS
receipt printers, and explicit support for the Epson TM-T20 (thermal),
TM-U220 (dot-matrix), and Aures ODP 333.  Label printers are supported
for stock label printing.  I use the DYMO LabelWriter-450 (cheap,
works well) but anything with [CUPS](https://www.cups.org/) support
will work.

Barcode scanners can be used to identify products as they are sold.
You need [some simple driver
software](https://github.com/sde1000/quicktill-serial-barcode-bridge)
to drive USB serial barcode scanners.  Other types of scanner, for
example Bluetooth cordless, are not yet supported but should be simple
to add if required.

Setup
-----

You must create a postgresql database and make it accessible to
whichever user is running the till software.  Name this database in
the configuration file.

Put a URL pointing at the config file in /etc/quicktill/configurl
(eg. file:///home/till/configweb/haymakers.py)

Create database tables:

    runtill syncdb

Copy the example database setup file and edit it:

    cp examples/dbsetup.toml my-database-config.toml
    (edit my-database-config.toml)
    runtill dbsetup my-database-config.toml

(There's an example edited database setup file at
`examples/data/emfcamp2022-dbsetup.toml`)

Create an initial user; this will be a superuser that can do anything,
you can use the user management interface once the till is running to
set up other users:

    runtill adduser "Built-in Alice" Alice builtin:alice

Run in "stock control terminal" mode and enter your initial stock
(this mode doesn't require a special keyboard)

    runtill start --gtk

Run in "cash register" mode, create stocklines, bind them to keys, put
your stock on sale, and sell it:

    runtill -c mainbar start --gtk --keyboard

A simple wrapper for the web interface can be found [in this
project](https://github.com/sde1000/quicktill-tillweb).

Useful subcommands
------------------

The till software is invoked as `runtill [options] subcommand
[subcommand options]`.  Usually the subcommand is "start", to run the
till interactively.  You can get a list of all the subcommands with
`runtill --help`.

Another useful subcommand is "dbshell", which starts an interactive
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

Credits
-------

This software incorporates code from the following projects, which may
be under a different licence:

* [jQuery](https://jquery.com/) (MIT licence)
* [TableSorter](https://plugins.jquery.com/tablesorter/) (MIT/GPL dual licence)
* [MultiSelect](https://plugins.jquery.com/multi-select/) ([DWTFYWT](http://www.wtfpl.net/txt/copying/) licence)
* [Select2](https://select2.org/) (MIT licence)
* [Chart.js](https://www.chartjs.org/) (MIT licence)
* [Sortable](https://github.com/SortableJS/Sortable) (MIT licence)
* [json-viewer](https://github.com/LorDOniX/json-viewer) (MIT licence)
* [DataTables](https://datatables.net/) (MIT licence)
