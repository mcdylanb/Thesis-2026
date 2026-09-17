# Gateway toolchain. Every target lists its Windows equivalent for teammates
# running native Windows Python (no make): run those in PowerShell instead.
#
# One-time: install uv (macOS: brew install uv | Windows: winget install astral-sh.uv)

UV      ?= uv
RUN     := $(UV) run
DATA    ?= data
OUT     ?= out/windows.jsonl
SYNTH   ?= synth_data
PORT    ?= /dev/ttyUSB0
BIND_IP ?= 0.0.0.0
UDP_PORT ?= 5555

.PHONY: help setup test synth preprocess listen capture thesis clean

help:
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

setup: ## Create .venv with dev + capture extras   | win: uv sync --extra dev --extra capture
	$(UV) sync --extra dev --extra capture

test: ## Run the pytest suite                      | win: uv run pytest
	$(RUN) pytest

synth: ## Generate a synthetic Trial's Captures      | win: uv run python -m gateway.synth --out synth_data
	$(RUN) python -m gateway.synth --out $(SYNTH)

preprocess: ## Windows+features from captures in DATA  | win: uv run python -m gateway --in data --out out/windows.jsonl --summary
	$(RUN) python -m gateway --in $(DATA) --out $(OUT) --summary

listen: ## Wireless: land the Relay's UDP stream   | win: uv run python scripts/relay_udp_listener.py --outdir data
	$(RUN) python scripts/relay_udp_listener.py --bind-ip $(BIND_IP) --port $(UDP_PORT) --outdir $(DATA)

capture: ## Serial fallback: PORT=/dev/cu.usbserial-XXXX | win: uv run python scripts/uart_listener_2.py --port COM3 --outdir data
	$(RUN) python scripts/uart_listener_2.py --port $(PORT) --outdir $(DATA)

thesis: ## Build thesis/main.pdf with latexmk       | win: cd thesis; latexmk -pdf main.tex
	cd thesis && latexmk -pdf main.tex

clean: ## Remove build outputs and caches          | win: remove .venv, out/, synth_data/, thesis build files by hand
	rm -rf .venv out $(SYNTH) .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	-cd thesis 2>/dev/null && latexmk -C main.tex
