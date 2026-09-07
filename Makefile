.PHONY: contract-test
contract-test:
	uv run pytest packages/schema -q

.PHONY: demo
demo:
	uv run python packages/dashboard/build_data.py
	@echo ""
	@echo "Dashboard built. Serving at http://localhost:8000"
	@echo "Open http://localhost:8000/home.html for the guided tour (home -> fleet -> call -> ingest)."
	@echo "Press Ctrl+C to stop."
	cd packages/dashboard && uv run python -m http.server 8000
