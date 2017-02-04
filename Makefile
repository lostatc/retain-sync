PREFIX ?= /usr
MANDIR = $(PREFIX)/share/man

build:
	make -C "docs" man
	python setup.py build
	python setup.py egg_info

install:
	python setup.py install \
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
	find "zielen" -depth -name "__pycache__" -type d | xargs rm -rf

help:
	@echo "make:            Build the program."
	@echo "make install:    Install the program."
	@echo "make uninstall:  Uninstall the program."
	@echo "make clean:      Remove generated files."
	@echo "make help:       Show this help message."

.PHONY: build install uninstall clean help
