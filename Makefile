# Makefile for quicktill
# Copyright (C) 2004 Stephen Early <steve@greenend.org.uk>

.PHONY:	all clean realclean distclean dist install

PACKAGE:=quicktill
VERSION:=0.5.4
DATE:=2004-11-12

SHELL:=/bin/sh
RM:=/bin/rm

TARGETS:=version.py caps.pdf

DISTFILES:=Makefile INSTALL createdb \
	quicktill.py event.py keyboard.py keycaps.py \
	manage.py plu.py priceguess.py printer.py recordwaste.py \
	register.py stock.py td.py ui.py usestock.py version.py

all:	$(TARGETS)

version.py: Makefile
	echo "version=\"$(VERSION) ($(DATE))\"" >version.py

caps.pdf: keycaps.py
	python keycaps.py

clean:
	$(RM) -f *.pyc $(TARGETS)

realclean:	clean
	$(RM) -f *~

distclean:	realclean

pfname:=$(PACKAGE)-$(VERSION)
dist:	version.py
	$(RM) -rf $(pfname)
	mkdir $(pfname)
	for i in $(DISTFILES) ; do ln -s ../$(srcdir)/$$i $(pfname)/ ; done
	tar hcf ../$(pfname).tar --exclude=CVS --exclude=.cvsignore $(pfname)
	gzip -9f ../$(pfname).tar
	$(RM) -rf $(pfname)
