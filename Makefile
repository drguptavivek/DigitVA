COMPOSE      = docker compose
COMPOSE_PROD = docker compose -f docker-compose.yml
APP_SERVICE  = minerva_app_service

.PHONY: dev dev-build dev-rebuild dev-down dev-restart \
        prod prod-build prod-rebuild prod-down \
        logs logs-app ps shell \
        migrate db-head test \
        restart-celery backup-db help

.DEFAULT_GOAL := help

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

help:
	@echo "Dev"
	@echo "  make dev             Start dev stack (with override)"
	@echo "  make dev-build       Build (cached) then start dev"
	@echo "  make dev-rebuild     Force full rebuild then start dev"
	@echo "  make dev-down        Stop dev stack"
	@echo "  make dev-restart     Restart app service only"
	@echo ""
	@echo "Prod"
	@echo "  make prod            Start prod stack (no override)"
	@echo "  make prod-build      Build (cached) then start prod"
	@echo "  make prod-rebuild    Force full rebuild then start prod"
	@echo "  make prod-down       Stop prod stack"
	@echo ""
	@echo "Logs"
	@echo "  make logs            Tail all container logs"
	@echo "  make logs-app        Tail app logs only"
	@echo ""
	@echo "Operations"
	@echo "  make ps              Show running containers"
	@echo "  make shell           Shell into app container"
	@echo "  make migrate         Run flask db upgrade"
	@echo "  make db-head         Show current and head migration revision"
	@echo "  make test            Run pytest"
	@echo "  make restart-celery  Restart celery worker and beat"
	@echo ""
	@echo "Database"
	@echo "  make backup-db       Dump DB to ~/dailybackups/"

# ---------------------------------------------------------------------------
# Dev (uses docker-compose.yml + docker-compose.override.yml)
# ---------------------------------------------------------------------------

dev:
	$(COMPOSE) up -d

dev-build:
	$(COMPOSE) build && $(COMPOSE) up -d

dev-rebuild:
	$(COMPOSE) build --no-cache && $(COMPOSE) up -d

dev-down:
	$(COMPOSE) down

dev-restart:
	$(COMPOSE) restart $(APP_SERVICE)

# ---------------------------------------------------------------------------
# Prod (uses docker-compose.yml only, no override)
# ---------------------------------------------------------------------------

prod:
	$(COMPOSE_PROD) up -d

prod-build:
	$(COMPOSE_PROD) build && $(COMPOSE_PROD) up -d

prod-rebuild:
	$(COMPOSE_PROD) build --no-cache && $(COMPOSE_PROD) up -d

prod-down:
	$(COMPOSE_PROD) down

# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

logs:
	$(COMPOSE) logs -f

logs-app:
	$(COMPOSE) logs -f $(APP_SERVICE)

# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

ps:
	$(COMPOSE) ps

shell:
	$(COMPOSE) exec $(APP_SERVICE) bash

migrate:
	$(COMPOSE) exec $(APP_SERVICE) uv run flask db upgrade

db-head:
	$(COMPOSE) exec $(APP_SERVICE) uv run flask db current
	$(COMPOSE) exec $(APP_SERVICE) uv run flask db heads

test:
	$(COMPOSE) exec $(APP_SERVICE) uv run pytest

restart-celery:
	$(COMPOSE) restart minerva_celery_worker minerva_celery_beat

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

backup-db:
	./scripts/manual-db-dump.sh
