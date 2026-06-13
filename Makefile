.PHONY: setup demo wallet api web up test clean

NPM := npm --cache .npm-cache

setup:
	python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -e ".[dev]"
	$(NPM) install
	cd web && $(NPM) install

wallet:
	$(NPM) run start

api:
	.venv/bin/python -m honeybee.api

demo:
	.venv/bin/python -m honeybee.orchestrator

web:
	cd web && $(NPM) run dev

# Run wallet (8787), orchestrator API (8000), orchestrator loop, and web (3000).
up:
	@echo "Starting all services. Press Ctrl-C to stop."
	@(trap 'kill 0' SIGINT; \
	  $(NPM) run start & \
	  .venv/bin/python -m honeybee.api & \
	  .venv/bin/python -m honeybee.orchestrator & \
	  cd web && $(NPM) run dev & \
	  wait)

test:
	.venv/bin/pytest -q

clean:
	rm -rf var/*.db __pycache__ .pytest_cache dist node_modules web/node_modules web/.next
