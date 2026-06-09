PY ?= .venv/bin/python

# mypy is scoped to lib/orchestration: the rest of lib/ predates type-checking
# and is not yet clean. Widen this target as more modules get annotated.
.PHONY: verify
verify:
	$(PY) -m ruff check lib/orchestration tests/orchestration
	$(PY) -m mypy lib/orchestration
	$(PY) -m pytest tests/orchestration -x -q --tb=short

.PHONY: test
test:
	$(PY) -m pytest tests/orchestration -q
