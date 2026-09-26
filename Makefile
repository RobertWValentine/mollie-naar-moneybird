.PHONY: test lint dry run status

test:
	python3 -m pytest tests/ -q && touch .last-test-run

lint:
	ruff check mollie_moneybird_sync tests

dry:
	./bin/run.sh --dry-run

run:
	./bin/run.sh

status:
	@echo "verwerkte transacties: $$(sqlite3 $${STATE_PATH:-$$HOME/.mollie-moneybird-sync/state.db} 'SELECT COUNT(*) FROM verwerkt' 2>/dev/null || echo onbekend)"
