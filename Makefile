COMPOSE      = docker compose
COMPOSE_PROD = docker compose -f docker-compose.yml
APP_SERVICE  = minerva_app_service

.PHONY: dev dev-build dev-rebuild dev-down dev-restart \
        prod prod-build prod-rebuild prod-down \
        logs logs-app ps shell \
        migrate db-head test test-projects \
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
	@echo "Test data (dev/staging only)"
	@echo "  make test-projects   Seed test projects and accounts, print who sees what"
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

# Seeds TST001 (organization, pick-and-choose) and its accounts, then lists the
# classical (sites) projects already in the DB. Idempotent. The seed itself
# refuses a non-debug app; this target does not weaken that guard. It never
# resets the schema: scripts/restore-test-db.sh does, so run it by hand for
# the classical test dataset (private/test_data.sql).
test-projects:
	$(COMPOSE) exec -T $(APP_SERVICE) uv run --no-sync flask db upgrade
	$(COMPOSE) exec -T $(APP_SERVICE) uv run --no-sync flask seed test-project
	@echo ""
	@echo "Login http://localhost:8051/   password Aiims@123 (dev only)"
	@echo "  test.all@digitva.com       ONE login: report deaths, review, code, supervise"
	@echo "                             TST001 organization + pick_and_choose; SADEMO classical + random allocation"
	@echo "  testadmin@digitva.com      Admin@123, admin and project PI"
	@echo "  test.mo.dh01@digitva.com   coder, TST001 (pick_and_choose)"
	@echo "  test.rev.dh01@digitva.com  reviewer, TST001"
	@echo "  test.anm.sc01@digitva.com  death reporter, TST001"
	@echo "  test.cho.sc01@digitva.com  interviewer, TST001 (more: docs/current-state/test-project-tst001.md)"
	@echo ""
	@echo "Classical (sites) projects with active coders in this DB (project, intake mode, coders):"
	@$(COMPOSE) exec -T minerva_db_service sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -At -F "  " -c "select p.project_id, p.coding_intake_mode, count(distinct g.user_id) from va_user_access_grants g left join va_project_sites s on s.project_site_id = g.project_site_id join va_project_master p on p.project_id = coalesce(g.project_id, s.project_id) where g.role = '"'"'coder'"'"' and g.grant_status = '"'"'active'"'"' and p.project_structure_mode = '"'"'sites'"'"' group by 1, 2 order by 1"'
	@echo "No classical coders? ./scripts/restore-test-db.sh loads the classical dataset (resets the schema)."

restart-celery:
	$(COMPOSE) restart minerva_celery_worker minerva_celery_beat

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

backup-db:
	./scripts/manual-db-dump.sh
