# Gateway toolchain. Every target lists its Windows equivalent for teammates
# running native Windows Python (no make): run those in PowerShell instead.
#
# One-time: install uv (macOS: brew install uv | Windows: winget install astral-sh.uv)

UV      ?= uv
RUN     := $(UV) run
DATA    ?= data
OUT     ?= out/windows.jsonl
SYNTH   ?= synth_data
SIM     ?= sim_data
LAYOUT  ?= layouts/techhub_default.yaml
SIM_MIN_STABILITY ?= 0
SESSION_SRC ?= data/4-sniffer-1-beacon-mode-irl/compiled_data
REAL    ?= out/techhub
FAULTS  ?= --fault A1:p28,p47,p53,p57,p61
PORT    ?= /dev/ttyUSB0
BIND_IP ?= 0.0.0.0
UDP_PORT ?= 5555
ANCHOR  ?= A1
FILE    ?= $(lastword $(sort $(wildcard $(DATA)/$(ANCHOR)_*.csv)))

.PHONY: help setup test synth sim import-session calibration-report trim-ablation eval eval-baseline eval-scout preprocess listen capture dashboard replay thesis clean

help:
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

setup: ## Create .venv with dev+capture+viz+scout extras | win: uv sync --extra dev --extra capture --extra viz --extra scout
	$(UV) sync --extra dev --extra capture --extra viz --extra scout

test: ## Run the pytest suite                      | win: uv run --extra dev --extra scout pytest
	$(RUN) --extra dev --extra scout pytest

synth: ## Generate a synthetic Trial's Captures      | win: uv run python -m gateway.synth --out synth_data
	$(RUN) python -m gateway.synth --out $(SYNTH)

sim: ## Simulated calibration + test sessions      | win: uv run python -m gateway.sim --layout layouts/techhub_default.yaml --out sim_data
	$(RUN) python -m gateway.sim --layout $(LAYOUT) --out $(SIM)

import-session: ## Real per-point zips in SESSION_SRC -> REAL | win: uv run python -m gateway.session_import --src data/4-sniffer-1-beacon-mode-irl/compiled_data --out out/techhub
	$(RUN) python -m gateway.session_import --src $(SESSION_SRC) --out $(REAL) --layout $(LAYOUT)

calibration-report: ## Radio map + quality report for REAL | win: uv run python -m gateway.calibration_report --session out/techhub/calibration --out out/techhub/report --fault A1:p28,p47,p53,p57,p61
	$(RUN) python -m gateway.calibration_report --session $(REAL)/calibration --out $(REAL)/report $(FAULTS)

trim-ablation: ## Trimmed vs untrimmed Radio map for REAL  | win: run the import-session line with --untrimmed --out out/techhub_untrimmed, then uv run python -m gateway.trim_ablation --trimmed out/techhub --untrimmed out/techhub_untrimmed --out out/techhub/trim_ablation
	$(RUN) python -m gateway.session_import --src $(SESSION_SRC) --out $(REAL)_untrimmed --layout $(LAYOUT) --untrimmed
	$(RUN) python -m gateway.trim_ablation --trimmed $(REAL) --untrimmed $(REAL)_untrimmed --out $(REAL)/trim_ablation

eval: sim ## k-NN, Scout and proposed side by side   | win: run the sim line, then uv run --extra scout python -m gateway.sniper --sim sim_data --layout layouts/techhub_default.yaml --out out/eval --min-stability 0
	$(RUN) --extra scout python -m gateway.sniper --sim $(SIM) --layout $(LAYOUT) --out out/eval --min-stability $(SIM_MIN_STABILITY)

eval-baseline: sim ## k-NN baseline on simulated data            | win: run the sim line, then uv run python -m gateway.evaluate --sim sim_data --layout layouts/techhub_default.yaml --out out/eval
	$(RUN) python -m gateway.evaluate --sim $(SIM) --layout $(LAYOUT) --out out/eval

eval-scout: sim ## MDN Scout next to the k-NN baseline      | win: run the sim line, then uv run --extra scout python -m gateway.scout --sim sim_data --layout layouts/techhub_default.yaml --out out/eval
	$(RUN) --extra scout python -m gateway.scout --sim $(SIM) --layout $(LAYOUT) --out out/eval

preprocess: ## Windows+features from captures in DATA  | win: uv run python -m gateway --in data --out out/windows.jsonl --summary
	$(RUN) python -m gateway --in $(DATA) --out $(OUT) --summary

listen: ## Wireless: land the Relay's UDP stream   | win: uv run python scripts/relay_udp_listener.py --outdir data
	$(RUN) python scripts/relay_udp_listener.py --bind-ip $(BIND_IP) --port $(UDP_PORT) --outdir $(DATA)

capture: ## Serial fallback: PORT=/dev/cu.usbserial-XXXX | win: uv run python scripts/uart_listener_2.py --port COM3 --outdir data
	$(RUN) python scripts/uart_listener_2.py --port $(PORT) --outdir $(DATA)

dashboard: ## Live plots of the newest ANCHOR Capture   | win: uv run python scripts/live_csi_dashboard.py --data data --anchor A1
	$(RUN) python scripts/live_csi_dashboard.py --data $(DATA) --anchor $(ANCHOR)

replay: ## Play back FILE=data/A1_x.csv offline       | win: uv run python scripts/live_csi_dashboard.py --file data/A1_x.csv --from-start --replay-rate 6
	$(RUN) python scripts/live_csi_dashboard.py --file $(FILE) --from-start --replay-rate 6

thesis: ## Build thesis/main.pdf with latexmk       | win: cd thesis; latexmk -pdf main.tex
	cd thesis && latexmk -pdf main.tex

clean: ## Remove build outputs and caches          | win: remove .venv, out/, synth_data/, sim_data/, thesis build files by hand
	rm -rf .venv out $(SYNTH) $(SIM) .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	-cd thesis 2>/dev/null && latexmk -C main.tex
