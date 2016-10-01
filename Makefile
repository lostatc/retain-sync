VERSION = 0.1
NAME = retain-sync

PREFIX ?= /usr/local
UNITDIR = /usr/lib/systemd/user
BINDIR = $(PREFIX)/bin
MANDIR = $(PREFIX)/share/man
SHAREDIR = $(PREFIX)/share/$(NAME)
LICENSEDIR = $(PREFIX)/share/licenses/$(NAME)

install:
	sed 's/@VERSION@/'$(VERSION)'/' common/$(NAME).in > common/$(NAME)
	sed 's|@DAEMON@|'$(BINDIR)/$(NAME)d'|' unit/$(NAME)@.service.in > unit/$(NAME)@.service
	sed 's|@PROGRAM@|'$(BINDIR)/$(NAME)'|' unit/$(NAME)-age@.service.in > unit/$(NAME)-age@.service
	sed 's|@PROGRAM@|'$(BINDIR)/$(NAME)'|' unit/$(NAME)-resync@.service.in > unit/$(NAME)-resync@.service
	install -Dm755 common/$(NAME) -t "$(BINDIR)"
	install -Dm755 common/$(NAME)d -t "$(BINDIR)"
	install -Dm644 common/config-template -t "$(SHAREDIR)"
	install -Dm644 LICENSE -t "$(LICENSEDIR)"
	install -Dm644 unit/$(NAME)@.service -t "$(UNITDIR)"
	install -Dm644 unit/$(NAME)-age@.service -t "$(UNITDIR)"
	install -Dm644 unit/$(NAME)-age@.timer -t "$(UNITDIR)"
	install -Dm644 unit/$(NAME)-resync@.service -t "$(UNITDIR)"
	install -Dm644 unit/$(NAME)-resync@.timer -t "$(UNITDIR)"
	install -Dm644 doc/$(NAME).1 -t "$(MANDIR)/man1"
	gzip -9 "$(MANDIR)/man1/$(NAME).1"

uninstall:
	rm "$(BINDIR)/$(NAME)"
	rm "$(BINDIR)/$(NAME)d"
	rm "$(UNITDIR)/$(NAME)@.service"
	rm "$(UNITDIR)/$(NAME)-age@.service"
	rm "$(UNITDIR)/$(NAME)-age@.timer"
	rm "$(UNITDIR)/$(NAME)-resync@.service"
	rm "$(UNITDIR)/$(NAME)-resync@.timer"
	rm "$(MANDIR)/man1/$(NAME).1.gz"

clean:
	rm common/$(NAME)
	rm unit/$(NAME)@.service
	rm unit/$(NAME)-age@.service
	rm unit/$(NAME)-resync@.service

.PHONY: install uninstall clean
