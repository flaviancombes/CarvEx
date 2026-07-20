from pathlib import Path
from models.models import RecoveredFile

file = RecoveredFile(
    path=Path("photo.jpg"),
    filename="photo.jpg",
    extension=".jpg",
    mime="image/jpeg",
    size=1548756
)

print(file)
print(file.size_mb)