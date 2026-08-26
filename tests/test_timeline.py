from datetime import UTC, datetime, timedelta

from timeline.event import TimelineEvent
from timeline.manager import TimelineManager
from timeline.source import EXIF, EXIF_CAPTURED, FILE_MODIFIED, FILESYSTEM


class StaticExtractor:
    def __init__(self, events):
        self.events = events
        self.calls = 0

    def extract(self, _record):
        self.calls += 1
        return self.events


def test_events_are_sorted_and_cached():
    later = datetime(2025, 3, 20, 17, 52, 11, tzinfo=UTC)
    earlier = datetime(2025, 3, 15, 14, 18, 22, tzinfo=UTC)
    extractor = StaticExtractor(
        (TimelineEvent(FILE_MODIFIED, later, FILESYSTEM), TimelineEvent(EXIF_CAPTURED, earlier, EXIF))
    )
    manager = TimelineManager((extractor,))
    record = {"file_id": "f4eaa4d1-cf9b-4884-b05b-5c53750636f5", "name": "photo.jpg", "output": "photo.jpg"}

    events = manager.events_for(record)

    assert [event.date for event in events] == [earlier, later]
    assert manager.events_for(record) is events
    assert extractor.calls == 1


def test_exif_after_filesystem_modification_is_marked():
    modified = datetime(2025, 3, 20, tzinfo=UTC)
    captured = modified + timedelta(days=1)
    manager = TimelineManager(
        (
            StaticExtractor(
                (TimelineEvent(FILE_MODIFIED, modified, FILESYSTEM), TimelineEvent(EXIF_CAPTURED, captured, EXIF))
            ),
        )
    )

    events = manager.events_for({"file_id": "591f7211-a4e1-44f2-b88c-b09f9f052454", "name": "photo.jpg"})

    captured_event = next(event for event in events if event.event_type == EXIF_CAPTURED)
    assert captured_event.is_anomaly
    assert "postérieure" in str(captured_event.comment)
