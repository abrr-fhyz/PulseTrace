from __future__ import annotations

import pytest

from lib.orchestration.state import initial_state

pytestmark = pytest.mark.unit


def test_initial_state_zeroes_loop_fields() -> None:
    st = initial_state("electric cars", ["reddit", "hn"], run_id="run-1")
    assert st["topic"] == "electric cars"
    assert st["sources"] == ["reddit", "hn"]
    assert st["run_id"] == "run-1"
    assert st["items"] == []
    assert st["scores"] == {}
    assert st["retry_count"] == 0
    assert st["should_alert"] is False
    assert st["error"] is None


def test_initial_state_run_id_optional() -> None:
    st = initial_state("topic", ["reddit"])
    assert st["run_id"] is None
