from core.exporter import Exporter
from models.models import RecoveredFile


def test_exporter_copies_file_and_records_hash(tmp_path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("CarvEx", encoding="utf-8")
    recovered = RecoveredFile(
        path=source,
        filename=source.name,
        extension=".txt",
        mime="text/plain",
        size=source.stat().st_size,
    )

    target = Exporter(tmp_path / "output").export(recovered)

    assert target.read_text(encoding="utf-8") == "CarvEx"
    assert recovered.output_path == target
    assert recovered.sha256
