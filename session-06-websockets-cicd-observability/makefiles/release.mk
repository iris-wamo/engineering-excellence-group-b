# Build once, deploy many: these targets run an image that CI already built and pushed
# (.github/workflows/release.yml). See docs/session-06/ci-cd.md (Release).
RELEASE_REPO ?= ghcr.io/iris-wamo/taskflow-api

.PHONY: image
image: ## Build the API image locally, labelled like CI does (taskflow-api:sha-<HEAD>)
	docker build --build-arg GIT_SHA=$$(git rev-parse HEAD) --build-arg APP_VERSION=sha-$$(git rev-parse --short HEAD) -t taskflow-api:sha-$$(git rev-parse HEAD) .

.PHONY: staging-deploy
staging-deploy: ## Deploy an image to staging, migrate and smoke test (TAG=sha-<sha>|v1.2.3, or IMAGE=<full ref>)
	@if [ -z "$(TAG)$(IMAGE)" ]; then echo "Usage: make staging-deploy TAG=sha-<git sha>  (or IMAGE=<ref>)"; exit 1; fi
	scripts/release.sh deploy staging $(or $(IMAGE),$(RELEASE_REPO):$(TAG))

.PHONY: promote
promote: ## Deploy staging's last smoke-tested image (same digest) to production
	scripts/release.sh promote

.PHONY: rollback
rollback: ## Redeploy the previous good image without migrating (ENV=staging|production, optional REV= to downgrade first)
	@if [ -z "$(ENV)" ]; then echo "Usage: make rollback ENV=staging|production [REV=<alembic revision>]"; exit 1; fi
	scripts/release.sh rollback $(ENV) $(if $(REV),--downgrade-to $(REV))

.PHONY: release-status
release-status: ## Show the running and last good image of each release stack, and what /version reports
	scripts/release.sh status

.PHONY: release-down
release-down: ## Stop a release stack, keeping its data (ENV=staging|production)
	@if [ -z "$(ENV)" ]; then echo "Usage: make release-down ENV=staging|production"; exit 1; fi
	scripts/release.sh down $(ENV)
