"""A notification that fails to deliver goes back on the queue, with a cap."""

from app.config import settings
from app.notify import dispatcher
from app.runtime import bus


async def test_a_failed_delivery_is_requeued_with_an_attempt_counter(monkeypatch):
    monkeypatch.setattr(dispatcher, "REQUEUE_DELAY_SECONDS", 0)
    event = {"user_id": 1, "kind": "success", "title": "t"}
    assert await dispatcher.requeue(event) is True
    back = await bus.pop(settings.NOTIFY_QUEUE, timeout=1)
    assert back == {**event, "_attempts": 1}


async def test_a_poison_event_is_dropped_after_the_cap(monkeypatch):
    monkeypatch.setattr(dispatcher, "REQUEUE_DELAY_SECONDS", 0)
    event = {"user_id": 1, "kind": "success", "title": "t", "_attempts": dispatcher.MAX_DELIVERY_ATTEMPTS - 1}
    assert await dispatcher.requeue(event) is False
    assert await bus.pop(settings.NOTIFY_QUEUE, timeout=1) is None
