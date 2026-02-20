.PHONY: help build test unit-test run clean scrape scrape-hf scrape-mittwald push lint fmt check test-full
IMAGE_REPO ?= ghcr.io/mittwald/openwebui

help: ## Show this help message
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

build: ## Build Docker image
	docker build -t openwebui-mittwald:local .

test: build ## Run tests on the image
	chmod +x scripts/test_image.sh
	./scripts/test_image.sh openwebui-mittwald:local

unit-test: ## Run Python unit tests
	python3 -m pytest -q tests

run: ## Run the container locally
	docker run -d -p 3000:8080 \
		-v open-webui-data:/app/backend/data \
		-e OWUI_BOOTSTRAP_TEMPERATURE=0.1 \
		-e OWUI_BOOTSTRAP_TOP_P=0.5 \
		-e OWUI_BOOTSTRAP_TOP_K=10 \
		-e OWUI_BOOTSTRAP_REPETITION_PENALTY=1.0 \
		-e OWUI_BOOTSTRAP_MAX_TOKENS=4096 \
		--name openwebui-test \
		openwebui-mittwald:local

logs: ## Show container logs
	docker logs -f openwebui-test

stop: ## Stop and remove the test container
	docker stop openwebui-test || true
	docker rm openwebui-test || true

clean: ## Clean up Docker resources
	docker stop openwebui-test || true
	docker rm openwebui-test || true
	docker volume rm open-webui-data || true
	docker rmi openwebui-mittwald:local || true

scrape-hf: ## Scrape Hugging Face for settings
	python3 scripts/scrape_huggingface.py

scrape-mittwald: ## Scrape Mittwald portal for models (requires MITTWALD_API_TOKEN)
	python3 scripts/scrape_mittwald_portal.py https://dev.mittwald.ai -o models.json

scrape: scrape-hf scrape-mittwald ## Run all scrapers

push: ## Push image to GHCR (requires GHCR_USERNAME and GHCR_TOKEN)
	@if [ -z "$(GHCR_USERNAME)" ]; then \
		echo "Error: GHCR_USERNAME not set"; \
		exit 1; \
	fi
	@if [ -z "$(GHCR_TOKEN)" ]; then \
		echo "Error: GHCR_TOKEN not set"; \
		exit 1; \
	fi
	@echo "Logging in to GHCR..."
	@echo $(GHCR_TOKEN) | docker login ghcr.io -u $(GHCR_USERNAME) --password-stdin
	@echo "Pushing image..."
	docker tag openwebui-mittwald:local $(IMAGE_REPO):local
	docker push $(IMAGE_REPO):local

lint: ## Lint Python scripts
	@python3 -m py_compile scripts/*.py bootstrap/*.py
	@echo "✓ All Python files compiled successfully"

fmt: ## Format Python scripts
	@python3 -m black scripts/*.py bootstrap/*.py 2>/dev/null || echo "black not installed, skipping"
	@python3 -m isort scripts/*.py bootstrap/*.py 2>/dev/null || echo "isort not installed, skipping"

install-deps: ## Install Python dependencies
	@echo "Installing dependencies..."
	pip3 install requests beautifulsoup4 black isort --quiet
	@echo "✓ Dependencies installed"

check: lint ## Run all checks
	@echo "Running all checks..."
	@$(MAKE) unit-test
	@echo "✓ Lint and unit tests passed"

test-full: check build test ## Run full lint, unit, and container test cycle

dev: build ## Build and run for development
	docker run -it -p 3000:8080 \
		-v open-webui-data:/app/backend/data \
		-e OWUI_BOOTSTRAP_TEMPERATURE=0.1 \
		-e OWUI_BOOTSTRAP_TOP_P=0.5 \
		-e OWUI_BOOTSTRAP_TOP_K=10 \
		-e OWUI_BOOTSTRAP_REPETITION_PENALTY=1.0 \
		-e OWUI_BOOTSTRAP_MAX_TOKENS=4096 \
		--entrypoint bash \
		openwebui-mittwald:local

update-submodules: ## Update Open WebUI reference (if using git submodule)
	git submodule update --remote

version: ## Show version info
	@echo "Mittwald Open WebUI Build System"
	@echo "================================="
	@echo ""
	@echo "Docker version:"
	@docker --version
	@echo ""
	@echo "Python version:"
	@python3 --version
	@echo ""
	@echo "Available make targets:"
	@make help
