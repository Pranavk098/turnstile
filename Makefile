.PHONY: contract-test
contract-test:
	uv run pytest packages/schema -q
