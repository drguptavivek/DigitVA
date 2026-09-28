COMPOSE      = docker compose
COMPOSE_PROD = docker compose -f docker-compose.yml
APP_SERVICE  = minerva_app_service

.PHONY: dev dev-build dev-rebuild dev-down dev-restart \
        prod prod-build prod-rebuild prod-down \
        logs logs-app ps shell \
        migrate db-head test \
        restart-celery backup-db ensure-secrets help

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
	@echo "  make ensure-secrets  Add missing CAPTCHA/TOTP keys to .env (run by dev/prod targets)"
	@echo ""
	@echo "Database"
	@echo "  make backup-db       Dump DB and .env to ~/dailybackups/"

# ---------------------------------------------------------------------------
# Secrets: append missing login-factor keys to .env; never overwrite existing
# ones. AUTH_FACTOR_ENCRYPTION_KEY encrypts TOTP secrets: back it up with
# .env, since a new key makes every enrolled TOTP unreadable.
# ---------------------------------------------------------------------------

ensure-secrets:
	@test -f .env || { echo "ensure-secrets: .env not found; copy .env.example first" >&2; exit 1; }
	@[ -z "$$(tail -c1 .env)" ] || echo >> .env
	@grep -q '^CAPTCHA_HMAC_KEY=.' .env || { \
		echo "CAPTCHA_HMAC_KEY=$$(openssl rand -hex 32)" >> .env; \
		echo "ensure-secrets: generated CAPTCHA_HMAC_KEY in .env"; }
	@grep -q '^AUTH_FACTOR_ENCRYPTION_KEY=.' .env || { \
		echo "AUTH_FACTOR_ENCRYPTION_KEY=$$(openssl rand -base64 32 | tr '+/' '-_')" >> .env; \
		echo "ensure-secrets: generated AUTH_FACTOR_ENCRYPTION_KEY in .env -- back up .env"; }

# ---------------------------------------------------------------------------
# Dev (uses docker-compose.yml + docker-compose.override.yml)
# ---------------------------------------------------------------------------

dev: ensure-secrets
	$(COMPOSE) up -d

dev-build: ensure-secrets
	$(COMPOSE) build && $(COMPOSE) up -d

dev-rebuild: ensure-secrets
	$(COMPOSE) build --no-cache && $(COMPOSE) up -d

dev-down:
	$(COMPOSE) down

dev-restart:
	$(COMPOSE) restart $(APP_SERVICE)

# ---------------------------------------------------------------------------
# Prod (uses docker-compose.yml only, no override)
# ---------------------------------------------------------------------------

prod: ensure-secrets
	$(COMPOSE_PROD) up -d

prod-build: ensure-secrets
	$(COMPOSE_PROD) build && $(COMPOSE_PROD) up -d

prod-rebuild: ensure-secrets
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
