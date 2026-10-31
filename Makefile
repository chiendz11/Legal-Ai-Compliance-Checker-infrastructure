PYTHON ?= .venv/bin/python
.PHONY: init up secrets argocd attach status
init:
	$(PYTHON) -m legal_infra init
up:
	$(PYTHON) -m legal_infra up
secrets:
	$(PYTHON) -m legal_infra secrets
argocd:
	$(PYTHON) -m legal_infra install-argocd
attach:
	$(PYTHON) -m legal_infra attach-gitops
status:
	$(PYTHON) -m legal_infra status
