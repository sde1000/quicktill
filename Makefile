# Makefile for quicktill
# Copyright (C) 2004 Stephen Early <steve@greenend.org.uk>

.PHONY:	all clean realclean distclean dist install

PACKAGE:=quicktill
VERSION:=0.7.1
DATE:=2005-11-02

SHELL:=/bin/sh
RM:=/bin/rm

TARGETS:=version.py caps.pdf

DISTFILES:=Makefile INSTALL createdb \
	magcard.py managetill.py plu.py recordwaste.py \
	stock.py till.py version.py delivery.py keyboard.py \
	managekeyboard.py printer.py register.py td.py ui.py \
	event.py keycaps.py managestock.py pdrivers.py \
	stocklines.py tillconfig.py usestock.py department.py \
	stockterminal.py kbdrivers.py

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
