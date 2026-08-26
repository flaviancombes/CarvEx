from datetime import UTC, datetime

from timeline.event import TimelineEvent
from timeline.manager import TimelineManager
from timeline.service import TimelineService
from timeline.source import EXIF, EXIF_CAPTURED


class EventExtractor:
    def __init__(self):
        self.calls = 0

    def extract(self, _record):
        self.calls += 1
        return (TimelineEvent(EXIF_CAPTURED, datetime(2025, 1, 1, tzinfo=UTC), EXIF),)


def test_service_reuses_same_event_objects_for_detail_and_global_index():
    extractor = EventExtractor()
    service = TimelineService(TimelineManager((extractor,)))
    record = {
        "file_id": "f4eaa4d1-cf9b-4884-b05b-5c53750636f5",
        "name": "photo.jpg",
        "output": "photo.jpg",
        "category": "Images",
    }
    service.set_records((record,))

    detail_event = service.events_for(record)[0]
    indexed_event = service.all_events()[0]

    assert detail_event is indexed_event
    assert indexed_event.file_record is record
    assert extractor.calls == 1
