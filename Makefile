PREFIX ?= /usr

BIN_DIR = $(PREFIX)/bin
UNIT_DIR = $(PREFIX)/lib/systemd/user
MAN_DIR = $(PREFIX)/share/man
LICENSE_DIR = $(PREFIX)/share/licenses/zielen
SHARE_DIR = $(PREFIX)/share/zielen

INSTALL_DATA = install -m 644 -D
INSTALL_BIN = install -m 755 -D

build:
	make -C "docs" man
	sed "s|@bindir@|$(BIN_DIR)|" "docs/unit/zielen@.service.in" > "docs/unit/zielen@.service"
	python3 setup.py build
	python3 setup.py egg_info

install:
	python3 setup.py install \
		--prefix "$(PREFIX)" \
		--single-version-externally-managed \
		--record "installed_files.txt"
	$(INSTALL_BIN) "scripts/zielen" -t "$(BIN_DIR)"
	$(INSTALL_BIN) "scripts/zielend" -t "$(BIN_DIR)"
	$(INSTALL_DATA) "LICENSE" -t "$(LICENSE_DIR)"
	$(INSTALL_DATA) "docs/templates/config-template" -t "$(SHARE_DIR)"
	$(INSTALL_DATA) "docs/unit/zielen@.service" -t "$(UNIT_DIR)"
	$(INSTALL_DATA) "docs/_build/man/zielen.1" -t "$(MAN_DIR)/man1"
	gzip -9f "$(MAN_DIR)/man1/zielen.1"

uninstall:
	cat "installed_files.txt" | xargs rm -rf
	rm -f "installed_files.txt"
	rm -f "$(BIN_DIR)/zielen"
	rm -f "$(BIN_DIR)/zielend"
	rm -f "$(MAN_DIR)/man1/zielen.1.gz"
	rm -f "$(UNIT_DIR)/zielen@.service"
	rm -rf "$(LICENSE_DIR)"
	rm -rf "$(SHARE_DIR)"

clean:
	rm -rf "build"
	rm -rf "docs/_build"
	rm -f "docs/unit/zielen@.service"
	find "zielen" -depth -name "__pycache__" -type d | xargs rm -rf

develop:
	python3 setup.py develop \
		--prefix "$(PREFIX)" \
		--user

help:
	@echo "make:            Build the program."
	@echo "make install:    Install the program normally."
	@echo "make uninstall:  Uninstall the program."
	@echo "make clean:      Remove generated files."
	@echo "make develop:	Install the program in development mode."
	@echo "make help:       Show this help message."

.PHONY: build install uninstall clean develop help
