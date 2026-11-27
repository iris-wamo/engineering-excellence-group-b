# Build once, deploy many: these targets run an image that CI already built and pushed
# (.github/workflows/release.yml) on the local release stack. Production is deployed by CI
# only, after approval. See docs/session-06/ci-cd.md (Release).
RELEASE_REPO ?= ghcr.io/iris-wamo/taskflow-api

.PHONY: image
image: ## Build the API image locally, labelled like CI does (taskflow-api:sha-<HEAD>)
	docker build --build-arg GIT_SHA=$$(git rev-parse HEAD) --build-arg APP_VERSION=sha-$$(git rev-parse HEAD) -t taskflow-api:sha-$$(git rev-parse HEAD) .

.PHONY: release-deploy
release-deploy: ## Run an image on the local release stack, migrate and smoke test (TAG=sha-<sha>|v1.2.3, or IMAGE=<full ref>)
	@if [ -z "$(TAG)$(IMAGE)" ]; then echo "Usage: make release-deploy TAG=sha-<git sha>  (or IMAGE=<ref>)"; exit 1; fi
	scripts/release.sh deploy local $(or $(IMAGE),$(RELEASE_REPO):$(TAG))

.PHONY: rollback
rollback: ## Redeploy the previous good image locally without migrating (optional REV= to downgrade first)
	scripts/release.sh rollback local $(if $(REV),--downgrade-to $(REV))

.PHONY: release-status
release-status: ## Show the local release stack's running and last good image, and what /version reports
	scripts/release.sh status local

.PHONY: release-down
release-down: ## Stop the local release stack, keeping its data
	scripts/release.sh down local
