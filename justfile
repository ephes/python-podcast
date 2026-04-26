# Justfile for python-podcast project development

# ========= Deploy Config (override via .envrc or environment) =========
# Path to your local ops-control clone
OPS_CONTROL := env_var_or_default("OPS_CONTROL", "/Users/jochen/projects/ops-control")
PROJECTS_ROOT := env_var_or_default("PROJECTS_ROOT", "/Users/jochen/projects")
OPS_LIBRARY_PATH := env_var_or_default("OPS_LIBRARY_PATH", PROJECTS_ROOT + "/ops-library")
SOPS_AGE_KEY_FILE := env_var_or_default("SOPS_AGE_KEY_FILE", "~/.config/sops/age/keys.txt")
ANSIBLE_PLAYBOOK_CMD := env_var_or_default("ANSIBLE_PLAYBOOK_CMD", "uvx --from ansible-core ansible-playbook")
ANSIBLE_GALAXY_CMD := env_var_or_default("ANSIBLE_GALAXY_CMD", "uvx --from ansible-core ansible-galaxy")

# Default recipe - show available commands
default:
    @just --list

# Check if services are already running
check-services:
    @echo "Checking for running services..."
    @if lsof -n -P -iTCP:8000 -sTCP:LISTEN > /dev/null 2>&1; then \
        echo "❌ Port 8000 already in use (Django)"; \
        echo "   PID: $(lsof -tiTCP:8000 -sTCP:LISTEN)"; \
        exit 1; \
    fi
    @if lsof -n -P -iTCP:5432 -sTCP:LISTEN > /dev/null 2>&1; then \
        echo "⚠️  Port 5432 already in use (PostgreSQL)"; \
        echo "   This might be your system PostgreSQL - checking..."; \
        if pgrep -f "postgres -D databases/postgres" > /dev/null; then \
            echo "   ❌ Local dev PostgreSQL already running"; \
            echo "   PID: $(pgrep -f 'postgres -D databases/postgres')"; \
            exit 1; \
        else \
            echo "   ✓ System PostgreSQL detected, will use different port"; \
        fi; \
    fi
    @echo "✓ All clear to start services"

# Kill any leftover processes from previous runs
cleanup:
    @echo "Cleaning up any leftover processes..."
    @-pkill -f "postgres -D databases/postgres" 2>/dev/null || true
    @-pkill -f "manage.py runserver" 2>/dev/null || true
    @-pkill -f "jupyterlab" 2>/dev/null || true
    @if [ -f logs/dev.pid ]; then \
        kill $(cat logs/dev.pid) 2>/dev/null || true; \
        rm logs/dev.pid; \
    fi
    @echo "✓ Cleanup complete"

# Start development server with logging (postgres + django only)
dev: check-services
    @mkdir -p logs
    @echo "Starting development services (postgres + django)..."
    @# Save process group ID for cleanup
    @echo $$ > logs/dev.pid
    @# Use honcho with specific processes
    @bash -c 'uvx honcho start postgres django 2>&1 | tee >(sed "s/\x1b\[[0-9;]*m//g" > logs/dev.log)' || (rm -f logs/dev.pid; exit 1)
    @rm -f logs/dev.pid

# Start all services from Procfile
dev-all: check-services
    @mkdir -p logs
    @echo "Starting all development services..."
    @echo $$ > logs/dev.pid
    @# Run all services defined in Procfile
    @bash -c 'uvx honcho start 2>&1 | tee >(sed "s/\x1b\[[0-9;]*m//g" > logs/dev.log)' || (rm -f logs/dev.pid; exit 1)
    @rm -f logs/dev.pid

# Start dev server without checks (force start)
dev-force: cleanup
    @just dev

# Start individual services
postgres:
    @echo "Starting PostgreSQL..."
    postgres -D databases/postgres

django:
    @echo "Starting Django development server..."
    PYTHONUNBUFFERED=true uv run python manage.py runserver 0.0.0.0:8000

jupyter:
    @echo "Starting JupyterLab..."
    uv run python commands.py jupyterlab

# View logs
logs *ARGS:
    @if [ -f logs/dev.log ]; then \
        python view_logs.py {{ARGS}}; \
    else \
        echo "No log file found. Run 'just dev' first."; \
    fi

# Follow logs in real-time
logs-follow:
    @just logs -f

# Filter logs
logs-grep PATTERN:
    @just logs -g "{{PATTERN}}"

# Run Django management commands
manage *ARGS:
    uv run python manage.py {{ARGS}}

# Run tests
test *ARGS:
    uv run python commands.py test {{ARGS}}

# Run coverage
coverage:
    uv run python commands.py coverage

# Database operations
db-migrate:
    @just manage makemigrations
    @just manage migrate

db-shell:
    @just manage dbshell

# Shell access
shell:
    @just manage shell_plus

# Install dependencies
install:
    uv sync

# Update prek hook revisions
update-hooks:
    env -u VIRTUAL_ENV uv run prek auto-update

# Build documentation
docs:
    uv run python commands.py docs

# Install ops-control Ansible dependencies via uvx
deploy-bootstrap:
    #!/usr/bin/env bash
    set -euo pipefail
    test -d "{{OPS_CONTROL}}" || (echo "ops-control not found at {{OPS_CONTROL}}"; exit 1)
    test -d "{{OPS_LIBRARY_PATH}}" || (echo "ops-library not found at {{OPS_LIBRARY_PATH}}"; exit 1)
    cd "{{OPS_CONTROL}}"
    {{ANSIBLE_GALAXY_CMD}} collection install -r collections/requirements.yml -p ./collections
    # ops-control roles also use community.postgresql, but it is not currently listed in collections/requirements.yml.
    {{ANSIBLE_GALAXY_CMD}} collection install community.postgresql -p ./collections
    rm -f ./local-ops_library-*.tar.gz
    {{ANSIBLE_GALAXY_CMD}} collection build "{{OPS_LIBRARY_PATH}}" --force
    {{ANSIBLE_GALAXY_CMD}} collection install ./local-ops_library-*.tar.gz -p ./collections --force
    rm -f ./local-ops_library-*.tar.gz

# Production deployment
deploy-staging: deploy-bootstrap
    @test -d "{{OPS_CONTROL}}" || (echo "ops-control not found at {{OPS_CONTROL}}"; exit 1)
    @test -f "{{OPS_CONTROL}}/inventories/prod/hosts.yml" || (echo "Missing ops-control inventory at {{OPS_CONTROL}}/inventories/prod/hosts.yml"; exit 1)
    @test -f "{{OPS_CONTROL}}/playbooks/deploy-python-podcast.yml" || (echo "Missing ops-control playbook at {{OPS_CONTROL}}/playbooks/deploy-python-podcast.yml"; exit 1)
    cd "{{OPS_CONTROL}}" && \
    PROJECTS_ROOT={{PROJECTS_ROOT}} \
    SOPS_AGE_KEY_FILE={{SOPS_AGE_KEY_FILE}} \
    {{ANSIBLE_PLAYBOOK_CMD}} -i inventories/prod/hosts.yml playbooks/deploy-python-podcast.yml -l staging -e target_host=staging -e service_secrets_env=staging

deploy-production: deploy-bootstrap
    @test -d "{{OPS_CONTROL}}" || (echo "ops-control not found at {{OPS_CONTROL}}"; exit 1)
    @test -f "{{OPS_CONTROL}}/inventories/prod/hosts.yml" || (echo "Missing ops-control inventory at {{OPS_CONTROL}}/inventories/prod/hosts.yml"; exit 1)
    @test -f "{{OPS_CONTROL}}/playbooks/deploy-python-podcast.yml" || (echo "Missing ops-control playbook at {{OPS_CONTROL}}/playbooks/deploy-python-podcast.yml"; exit 1)
    cd "{{OPS_CONTROL}}" && \
    PROJECTS_ROOT={{PROJECTS_ROOT}} \
    SOPS_AGE_KEY_FILE={{SOPS_AGE_KEY_FILE}} \
    {{ANSIBLE_PLAYBOOK_CMD}} -i inventories/prod/hosts.yml playbooks/deploy-python-podcast.yml

# Help for common issues
troubleshoot:
    @echo "Common issues and solutions:"
    @echo ""
    @echo "1. Port already in use:"
    @echo "   just cleanup  # Kill leftover processes"
    @echo "   just dev      # Try again"
    @echo ""
    @echo "2. Force restart everything:"
    @echo "   just dev-force"
    @echo ""
    @echo "3. Check what's using a port:"
    @echo "   lsof -i :8000  # Django"
    @echo "   lsof -i :5432  # PostgreSQL"
    @echo ""
    @echo "4. View logs:"
    @echo "   just logs          # Last 50 lines"
    @echo "   just logs-follow   # Real-time"
    @echo "   just logs-grep ERROR"
