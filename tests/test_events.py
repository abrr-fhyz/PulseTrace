from lib.events import EventBus, sse_format


def test_bus_publishes_to_subscriber():
    bus = EventBus()
    q = bus.subscribe("r1")
    bus.publish("r1", {"type": "hi"})
    assert q.get_nowait() == {"type": "hi"}


def test_bus_isolates_runs():
    bus = EventBus()
    q1 = bus.subscribe("r1")
    bus.subscribe("r2")
    bus.publish("r2", {"type": "x"})
    assert q1.empty()


def test_close_signals():
    bus = EventBus()
    q = bus.subscribe("r1")
    bus.close("r1")
    assert q.get_nowait() == {"type": "_close"}


def test_sse_format_shape():
    s = sse_format({"a": 1})
    assert s.startswith("data: ") and s.endswith("\n\n")
    assert '"a": 1' in s
