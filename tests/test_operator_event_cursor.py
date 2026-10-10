"""Pure fixtures only: no API, BUS, SDK, network or hardware initialization."""

from collections import deque

from services.api_core.event_stream import EventCursor


def test_new_events_continue_after_bounded_buffer_is_full():
    events = deque(maxlen=2)
    cursor = EventCursor()
    first, second, third = ({"ts": 10, "topic": f"fixture.{i}"} for i in range(3))
    events.extend([first, second])
    assert cursor.drain(list(events)) == [first, second]
    assert cursor.drain(list(events)) == []
    events.append(third)
    assert cursor.drain(list(events)) == [third]


def test_evicted_marker_delivers_remaining_buffer_without_changing_timestamps():
    events = deque(maxlen=2)
    cursor = EventCursor()
    events.append({"ts": 10})
    cursor.drain(list(events))
    events.extend([{"ts": 8}, {"ts": 8}])
    assert cursor.drain(list(events)) == [{"ts": 8}, {"ts": 8}]
    assert cursor.drain(list(events)) == []


def test_empty_and_same_timestamp_are_not_fabricated_events():
    cursor = EventCursor()
    assert cursor.drain([]) == []
    first, second = {"ts": 1}, {"ts": 1}
    assert cursor.drain([first]) == [first]
    assert cursor.drain([first, second]) == [second]
