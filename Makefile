SHELL := /bin/bash

.PHONY: install reinstall uninstall dev help completions

help:
	@echo "Targets:"
	@echo "  make install     Install kgtool using scripts/install.sh"
	@echo "  make reinstall   Re-run install"
	@echo "  make uninstall   Remove installed kgtool"
	@echo "  make dev         Create .venv and install editable package"
	@echo "  make completions Run kgtool completions"

install:
	bash scripts/install.sh

reinstall:
	bash scripts/install.sh

uninstall:
	bash scripts/uninstall.sh

dev:
	python3 -m venv .venv
	. .venv/bin/activate && pip install -e .

completions:
	kgtool completions
