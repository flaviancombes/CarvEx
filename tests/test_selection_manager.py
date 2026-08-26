from selection.context import SelectionContext
from selection.manager import SelectionManager


def test_selection_history_is_bounded_and_navigable():
    manager = SelectionManager(history_limit=2)
    first = SelectionContext("file", "first", "files_view")
    second = SelectionContext("file", "second", "files_view")
    third = SelectionContext("file", "third", "files_view")

    manager.publish(first)
    manager.publish(second)
    manager.publish(third)

    assert manager.current is not None
    assert manager.current.subject_id == "third"
    assert manager.go_back() is not None
    assert manager.current is not None
    assert manager.current.subject_id == "second"
    assert not manager.can_go_back


def test_context_relations_are_not_mutable_after_publication():
    related = {"file_id": "file-1"}
    context = SelectionContext("timeline_event", "event-1", "timeline_view", related)
    related["file_id"] = "changed"

    assert context.related_ids["file_id"] == "file-1"


def test_reselecting_the_current_target_notifies_consumers_without_duplicating_history():
    manager = SelectionManager()
    received = []
    manager.selection_changed.connect(received.append)
    context = SelectionContext("file", "file-1", "files_view")

    manager.publish(context)
    manager.publish(context)

    assert len(received) == 2
    assert received[0].selection_id != received[1].selection_id
    assert not manager.can_go_back
