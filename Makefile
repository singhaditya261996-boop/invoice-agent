# Quick start:  make setup && make demo
.PHONY: setup demo api web test eval data clean

VENV := .venv
PY := $(VENV)/bin/python

setup:  ## install Python and frontend dependencies
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q -e ".[dev]"
	cd app/frontend && npm install --silent
	@echo "Ready. Run 'make demo'."

demo: ## run the API and UI together (demo mode: recorded model responses, no API key)
	@echo "API  -> http://localhost:8000"
	@echo "UI   -> http://localhost:5173   (choose Demo + Documents, 16 invoices)"
	@trap 'kill 0' EXIT; \
	$(VENV)/bin/uvicorn app.api.main:app --port 8000 & \
	cd app/frontend && npm run dev -- --port 5173; \
	wait

api: ## API only
	$(VENV)/bin/uvicorn app.api.main:app --reload --port 8000

web: ## UI only
	cd app/frontend && npm run dev

test: ## run the test suite
	$(VENV)/bin/pytest -q

eval: ## rules-only evaluation over all 500 invoices (free, no API key)
	$(PY) -m eval.run_eval --mode offline

data: ## regenerate the synthetic dataset (deterministic)
	$(PY) -m data.generator.generate

clean:
	rm -rf $(VENV) app/frontend/node_modules app/frontend/dist .pytest_cache
