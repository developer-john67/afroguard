.PHONY: dev test lint typecheck reset-demo install

# Default target
dev:
	@echo "Starting AgroGuard dev server..."
	@cd agroguard && python -m server.main

install:
	@echo "Installing dependencies..."
	@cd agroguard && pip install -r requirements.txt

test:
	@echo "Running tests..."
	@cd agroguard && python -m pytest tests/ -v

lint:
	@echo "Running lint..."
	@cd agroguard && python -m ruff check .

typecheck:
	@echo "Running typecheck..."
	@cd agroguard && python -m mypy .

reset-demo:
	@echo "Resetting demo state..."
	@cd agroguard && python -m tools.reset_demo

# Docker targets
docker-build:
	docker build -t agroguard .

docker-run:
	docker run -p 8000:8000 --env-file agroguard/.env agroguard