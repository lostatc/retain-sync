PREFIX ?= /usr
BINDIR = $(PREFIX)/bin
MANDIR = $(PREFIX)/share/man

build:
	make -C "docs" man
	sed "s|@bindir@|$(BINDIR)|" "docs/unit/zielen@.service.in" > "docs/unit/zielen@.service"
	python3 setup.py build
	python3 setup.py egg_info

install:
	python3 setup.py install \
		--prefix "$(PREFIX)" \
		--single-version-externally-managed \
		--record "installed_files.txt"
	gzip -9f "$(MANDIR)/man1/zielen.1"

uninstall:
	cat "installed_files.txt" | xargs rm -rf
	rm -f "installed_files.txt"

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
