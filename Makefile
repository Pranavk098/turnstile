.PHONY: contract-test
contract-test:
	uv run pytest packages/schema -q

.PHONY: report
report:
	uv run python packages/dashboard/build_data.py

.PHONY: demo
demo: report
	@echo ""
	@echo "Dashboard built. Serving at http://localhost:8000"
	@echo "Open http://localhost:8000/home.html for the guided tour (home -> fleet -> call -> ingest)."
	@echo "Press Ctrl+C to stop."
	cd packages/dashboard && uv run python -m http.server 8000

.PHONY: serve
serve:
	@echo "Turnstile demo service at http://localhost:8000 (fleet + POST /api/evaluate)."
	@echo "Press Ctrl+C to stop."
	uv run uvicorn turnstile_service.app:app --host 127.0.0.1 --port 8000
