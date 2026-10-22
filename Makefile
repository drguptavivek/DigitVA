COMPOSE      = docker compose
# Split production (database on its own host): the credentials file exists only
# there, so its presence selects the external-database overlay.
PROD_DB_ENV ?= /data/digitva-db.env
ifneq ($(wildcard $(PROD_DB_ENV)),)
COMPOSE_PROD = docker compose --env-file .env --env-file $(PROD_DB_ENV) -f docker-compose.yml -f docker-compose.external-db.yml
else
COMPOSE_PROD = docker compose -f docker-compose.yml
endif
# Production keeps the PII KEM private key OUTSIDE the checkout (owner
# decision 13): the checkout is bind-mounted into every app container. .env
# or the shell may name another absolute path outside the checkout.
PROD_PII_KEM_PRIVATE_KEY_PATH ?= /data/digitva-secrets/pii_kem_private_key
PROD_PII_KEY_PATH = $(or $(PII_KEM_PRIVATE_KEY_PATH),$(shell sed -n 's/^PII_KEM_PRIVATE_KEY_PATH=//p' .env 2>/dev/null | tail -n1),$(PROD_PII_KEM_PRIVATE_KEY_PATH))
COMPOSE_PROD := PII_KEM_PRIVATE_KEY_PATH=$(PROD_PII_KEY_PATH) $(COMPOSE_PROD)
# The server Ed25519 key that signs station configs (and later receipts):
# outside the checkout in production too, same rules as the PII key.
PROD_BUNDLE_SERVER_SIGNING_KEY_PATH ?= /data/digitva-secrets/bundle_server_signing_key
PROD_BUNDLE_KEY_PATH = $(or $(BUNDLE_SERVER_SIGNING_KEY_PATH),$(shell sed -n 's/^BUNDLE_SERVER_SIGNING_KEY_PATH=//p' .env 2>/dev/null | tail -n1),$(PROD_BUNDLE_SERVER_SIGNING_KEY_PATH))
COMPOSE_PROD := BUNDLE_SERVER_SIGNING_KEY_PATH=$(PROD_BUNDLE_KEY_PATH) $(COMPOSE_PROD)
APP_SERVICE  = minerva_app_service

.PHONY: dev dev-build dev-rebuild dev-down dev-restart \
        prod prod-build prod-rebuild prod-down \
        logs logs-app ps shell \
        migrate db-head test test-parallel test-projects \
        restart-celery backup-db ensure-secrets ensure-secrets-prod help

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
	@echo "  make test-parallel   Full suite on 4 xdist workers (TEST_DATABASE_URL=... to pick the DB)"
	@echo "  make check-web       Build the Expo web export into a temp dir (fails if the web bundle breaks)"
	@echo "  make restart-celery  Restart celery worker and beat"
	@echo ""
	@echo "  make ensure-secrets  Add missing CAPTCHA/TOTP/PII keys to .env; DEVELOPMENT key in private/ (dev targets)"
	@echo "  make ensure-secrets-prod  The same for production; private key outside the checkout (prod targets)"
	@echo ""
	@echo "Test data (dev/staging only)"
	@echo "  make test-projects   Seed test projects and accounts, print who sees what"
	@echo ""
	@echo "Database"
	@echo "  make backup-db       Dump DB and .env to ~/dailybackups/"

# ---------------------------------------------------------------------------
# Secrets: append missing login-factor keys to .env; never overwrite existing
# ones. AUTH_FACTOR_ENCRYPTION_KEY encrypts TOTP secrets: back it up with
# .env, since a new key makes every enrolled TOTP unreadable. The PII_* keys
# encrypt personal data: back up .env and the private key file apart from
# the database; losing the private key loses the values.
#
# ensure-secrets (dev targets): the private key is the DEVELOPMENT one, in
# the checkout's git-ignored private/ (every container bind-mounts the
# checkout; beat masks private/). ensure-secrets-prod (prod targets): the key
# lives at PROD_PII_KEY_PATH, an absolute path outside the checkout, owned by
# the deploy user, mode 0600; it refuses a path under the checkout and a key
# file still in private/.
# ---------------------------------------------------------------------------

ensure-secrets: PII_KEY_MODE := dev
ensure-secrets: PII_KEY_FILE := private/pii_kem_private_key
ensure-secrets: BUNDLE_KEY_FILE := $(or $(BUNDLE_SERVER_SIGNING_KEY_PATH),$(shell sed -n 's/^BUNDLE_SERVER_SIGNING_KEY_PATH=//p' .env 2>/dev/null | tail -n1),private/bundle_server_signing_key)
ensure-secrets-prod: PII_KEY_MODE := prod
ensure-secrets-prod: PII_KEY_FILE := $(PROD_PII_KEY_PATH)
ensure-secrets-prod: BUNDLE_KEY_FILE := $(PROD_BUNDLE_KEY_PATH)

ensure-secrets ensure-secrets-prod:
	@test -f .env || { echo "ensure-secrets: .env not found; copy .env.example first" >&2; exit 1; }
	@[ -z "$$(tail -c1 .env)" ] || echo >> .env
	@# Station-config signing key: a base64url 32-byte Ed25519 seed, made once, never overwritten.
	@if [ "$(PII_KEY_MODE)" = prod ]; then \
		case "$(BUNDLE_KEY_FILE)" in */../*|*/./*|*//*) echo "ensure-secrets-prod: BUNDLE_SERVER_SIGNING_KEY_PATH must be a normalised path" >&2; exit 1;; /*) ;; *) echo "ensure-secrets-prod: BUNDLE_SERVER_SIGNING_KEY_PATH must be an absolute path outside the checkout" >&2; exit 1;; esac; \
		case "$(BUNDLE_KEY_FILE)" in "$(CURDIR)"/*) echo "ensure-secrets-prod: $(BUNDLE_KEY_FILE) is inside the checkout; keep the key outside it" >&2; exit 1;; esac; \
	fi; \
	test -f "$(BUNDLE_KEY_FILE)" || { \
		key_dir="$$(dirname "$(BUNDLE_KEY_FILE)")"; mkdir -p "$$key_dir" && \
		{ [ "$(PII_KEY_MODE)" != prod ] || chmod 700 "$$key_dir"; } && (umask 077; openssl rand 32 | openssl base64 -A | tr '+/' '-_' | tr -d '=' > "$(BUNDLE_KEY_FILE)") && \
		echo "ensure-secrets: generated the station-config signing key $(BUNDLE_KEY_FILE) -- back it up; stations pin its public key"; }
	@grep -q '^CAPTCHA_HMAC_KEY=.' .env || { \
		echo "CAPTCHA_HMAC_KEY=$$(openssl rand -hex 32)" >> .env; \
		echo "ensure-secrets: generated CAPTCHA_HMAC_KEY in .env"; }
	@grep -q '^AUTH_FACTOR_ENCRYPTION_KEY=.' .env || { \
		echo "AUTH_FACTOR_ENCRYPTION_KEY=$$(openssl rand -base64 32 | tr '+/' '-_')" >> .env; \
		echo "ensure-secrets: generated AUTH_FACTOR_ENCRYPTION_KEY in .env -- back up .env"; }
	@if [ "$(PII_KEY_MODE)" = prod ]; then \
		case "$(PII_KEY_FILE)" in */../*|*/./*|*//*) echo "ensure-secrets-prod: PII_KEM_PRIVATE_KEY_PATH must be a normalised path (no . or .. parts)" >&2; exit 1;; /*) ;; *) echo "ensure-secrets-prod: PII_KEM_PRIVATE_KEY_PATH must be an absolute path outside the checkout" >&2; exit 1;; esac; \
		case "$(PII_KEY_FILE)" in "$(CURDIR)"/*) echo "ensure-secrets-prod: $(PII_KEY_FILE) is inside the checkout, which every container mounts; keep the key outside it" >&2; exit 1;; esac; \
		test ! -e private/pii_kem_private_key || { echo "ensure-secrets-prod: private/pii_kem_private_key is still in the checkout; move it to $(PII_KEY_FILE) (mode 0600) and delete the copy" >&2; exit 1; }; \
	else \
		key_path="$${PII_KEM_PRIVATE_KEY_PATH:-$$(sed -n 's/^PII_KEM_PRIVATE_KEY_PATH=//p' .env | tail -n1)}"; \
		echo "ensure-secrets: DEVELOPMENT key file $${key_path:-$(PII_KEY_FILE)} (production uses make ensure-secrets-prod, key outside the checkout)"; \
	fi
	@key_file="$(PII_KEY_FILE)"; \
	if [ "$(PII_KEY_MODE)" = dev ]; then key_file="$${PII_KEM_PRIVATE_KEY_PATH:-$$(sed -n 's/^PII_KEM_PRIVATE_KEY_PATH=//p' .env | tail -n1)}"; key_file="$${key_file:-$(PII_KEY_FILE)}"; fi; \
	if grep -q '^PII_KEM_PUBLIC_KEY=.' .env; then \
		test -f "$$key_file" || { echo "ensure-secrets: PII_KEM_PUBLIC_KEY is set in .env but the private key file $$key_file is missing; restore it (a key pair is never regenerated)" >&2; exit 1; }; \
		grep -q '^PII_BLIND_INDEX_KEY=.' .env || { \
			echo "PII_BLIND_INDEX_KEY=$$(openssl rand -hex 32)" >> .env; \
			echo "ensure-secrets: generated PII_BLIND_INDEX_KEY in .env -- back up .env"; }; \
	elif [ "$(PII_KEY_MODE)" = prod ]; then \
		test ! -e "$$key_file" || { echo "ensure-secrets-prod: $$key_file exists but .env has no PII_KEM_PUBLIC_KEY; restore .env or remove the file" >&2; exit 1; }; \
		key_dir="$$(dirname "$$key_file")"; mkdir -p "$$key_dir" && chmod 700 "$$key_dir" && \
		PII_KEM_PRIVATE_KEY_PATH=./Makefile BUNDLE_SERVER_SIGNING_KEY_PATH=./Makefile $(COMPOSE) run --rm --no-deps --user "$$(id -u):$$(id -g)" \
			-v "$$key_dir:/pii-secret" --entrypoint python minerva_app_service \
			scripts/generate_pii_keys.py --private-file "/pii-secret/$$(basename "$$key_file")" --env-file .env; \
	else \
		test ! -e private/pii_kem_private_key || { echo "ensure-secrets: private/pii_kem_private_key exists but .env has no PII_KEM_PUBLIC_KEY; restore .env or remove the file" >&2; exit 1; }; \
		mkdir -p private && PII_KEM_PRIVATE_KEY_PATH=./Makefile BUNDLE_SERVER_SIGNING_KEY_PATH=./Makefile $(COMPOSE) run --rm --no-deps --entrypoint python minerva_app_service \
			scripts/generate_pii_keys.py --private-file private/pii_kem_private_key --env-file .env; \
	fi

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
# Prod (docker-compose.yml, no dev override; + external-db overlay on split hosts)
# ---------------------------------------------------------------------------

prod: ensure-secrets-prod
	$(COMPOSE_PROD) up -d

prod-build: ensure-secrets-prod
	$(COMPOSE_PROD) build && $(COMPOSE_PROD) up -d

prod-rebuild: ensure-secrets-prod
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

# Each worker uses <test db>_gw0.. (docs/policy/test-harness.md).
test-parallel:
	$(COMPOSE) exec -T $(if $(TEST_DATABASE_URL),-e TEST_DATABASE_URL=$(TEST_DATABASE_URL)) $(APP_SERVICE) \
		uv run --no-sync python -m pytest tests -q -p no:cacheprovider -n 4

# Jest mocks native-only modules, so only a real export proves the web bundle
# still builds (a phone-only import once broke it). Writes to a temp dir, never
# to dist/, which dev serves. The pre-commit hook runs it for mobile/vendor changes.
.PHONY: check-web
check-web:
	@out=$$(mktemp -d); cd mobile/digitva-collect && npx expo export --platform web --output-dir "$$out" >"$$out.log" 2>&1; \
	status=$$?; if [ $$status -ne 0 ]; then grep -E "rror|Unable to resolve" "$$out.log" | head -20; fi; \
	rm -rf "$$out" "$$out.log"; exit $$status

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
