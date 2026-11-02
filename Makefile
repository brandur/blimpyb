PYTHON ?= python3
VENV_PYTHON = .venv/bin/python
PORT ?= 8000

.PHONY: setup build serve recover check
setup:
	$(PYTHON) -m venv .venv
	$(VENV_PYTHON) -m pip install -r requirements.txt

build:
	$(VENV_PYTHON) scripts/build.py

serve: build
	$(VENV_PYTHON) -m http.server $(PORT) --bind 127.0.0.1 --directory dist

recover:
	$(VENV_PYTHON) scripts/recover.py index
	$(VENV_PYTHON) scripts/recover.py pages --retry-failed
	$(VENV_PYTHON) scripts/recover.py feeds --retry-failed
	$(VENV_PYTHON) scripts/recover.py linked-pages --retry-failed
	$(VENV_PYTHON) scripts/recover.py images --retry-failed
	$(VENV_PYTHON) scripts/recover.py external-images --retry-failed

check: build
	$(VENV_PYTHON) -m unittest discover -s tests -v
	$(VENV_PYTHON) scripts/check.py
