from pathlib import Path

from models.models import RecoveredFile


def test_recovered_file_exposes_a_human_readable_size() -> None:
    recovered = RecoveredFile(
        path=Path("photo.jpg"),
        filename="photo.jpg",
        extension=".jpg",
        mime="image/jpeg",
        size=1_548_756,
    )

    assert recovered.size_mb == 1.48
    assert "photo.jpg" in str(recovered)
