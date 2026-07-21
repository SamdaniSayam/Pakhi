.PHONY: help install install-dev lint fmt test test-cov docker-build docker-run clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install:  ## Install pakhi (stable)
	pip install .

install-dev:  ## Install pakhi in editable mode with all extras
	pip install -e ".[all]"

lint:  ## Run ruff linter
	ruff check pakhi/ tests/ examples/

fmt:  ## Format code with ruff
	ruff format pakhi/ tests/ examples/

fmt-check:  ## Check formatting without changing files
	ruff format --check pakhi/ tests/ examples/

test:  ## Run test suite
	pytest tests/ -v --tb=short

test-cov:  ## Run tests with coverage report
	pytest tests/ -v --tb=short --cov=pakhi --cov-report=term-missing --cov-report=html

test-fast:  ## Run tests excluding slow/network tests
	pytest tests/ -v --tb=short -m "not slow and not network"

typecheck:  ## Run type checking (if mypy installed)
	@command -v mypy >/dev/null 2>&1 && mypy pakhi/ --ignore-missing-imports || echo "Install mypy: pip install mypy"

docker-build:  ## Build Docker image
	docker build -t pakhi:latest .

docker-run:  ## Run pakhi in Docker (interactive)
	docker run --rm -it pakhi:latest

docker-dashboard:  ## Run pakhi status dashboard in Docker
	docker run --rm pakhi:latest status

docker-compose-up:  ## Start services via docker-compose
	docker compose up -d

docker-compose-down:  ## Stop docker-compose services
	docker compose down

clean:  ## Remove build artifacts
	rm -rf dist/ build/ *.egg-info .pytest_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

all: lint test  ## Run lint + tests
