# python_manager Makefile
#
# Build a standalone single-file binary using PyInstaller.
# Run this on the target machine (x86-64 PC or Raspberry Pi ARM).
#
# Targets:
#   make              - build binary for the current machine
#   make install      - copy binary to /usr/local/bin
#   make install-deps - install python3-tk and pyinstaller (Debian/Ubuntu)
#   make clean        - remove build artefacts
#   make dist         - build + package into a tar.gz

SCRIPT  := python_manager.py
TARGET  := python_manager
PYTHON  ?= python3
SPEC    := $(TARGET).spec
DISTDIR := dist
PKGDIR  := package

VERSION ?= 1.0.1
# x86_64, aarch64 or armv7l
ARCH    := $(shell uname -m)
TARBALL := $(TARGET)-$(VERSION)-linux-$(ARCH).tar.gz

PREFIX  ?= /usr/local
BINDIR  := $(PREFIX)/bin

.PHONY: all install install-deps dist clean

all: $(DISTDIR)/$(TARGET)

# Install build dependencies (Debian/Ubuntu)
install-deps:
	sudo apt-get update
	sudo apt-get install -y python3 python3-tk python3-pip
	$(PYTHON) -m pip install --upgrade pyinstaller

# Build the binary
$(DISTDIR)/$(TARGET): $(SCRIPT)
	$(PYTHON) -m PyInstaller \
	    --onefile \
	    --windowed \
	    --name $(TARGET) \
	    --clean \
	    $(SCRIPT)

install: $(DISTDIR)/$(TARGET)
	install -d $(DESTDIR)$(BINDIR)
	install -m 0755 $(DISTDIR)/$(TARGET) $(DESTDIR)$(BINDIR)/$(TARGET)

# Package: binary + README + LICENSE -> tar.gz in package/
dist: $(DISTDIR)/$(TARGET)
	mkdir -p $(PKGDIR)/$(TARGET)-$(VERSION)-linux-$(ARCH)
	cp $(DISTDIR)/$(TARGET) $(PKGDIR)/$(TARGET)-$(VERSION)-linux-$(ARCH)/
	cp README.md LICENSE $(PKGDIR)/$(TARGET)-$(VERSION)-linux-$(ARCH)/ 2>/dev/null || true
	tar -C $(PKGDIR) -czf $(PKGDIR)/$(TARBALL) $(TARGET)-$(VERSION)-linux-$(ARCH)
	sha256sum $(PKGDIR)/$(TARBALL) > $(PKGDIR)/$(TARBALL).sha256
	@echo "Package: $(PKGDIR)/$(TARBALL)"
	@cat $(PKGDIR)/$(TARBALL).sha256

clean:
	rm -rf build $(DISTDIR) __pycache__ *.spec $(PKGDIR)
