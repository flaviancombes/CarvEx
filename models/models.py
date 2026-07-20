"""
CarvEx
Models

Toutes les structures de données utilisées
par l'application.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class RecoveredFile:
    """
    Représente un fichier récupéré par PhotoRec.
    """

    # Emplacement du fichier PhotoRec
    path: Path

    # Nom du fichier
    filename: str

    # Extension (.jpg, .pdf...)
    extension: str

    # Type MIME réel
    mime: str

    # Taille en octets
    size: int

    # Catégorie (Images, PDF...)
    category: str = "Unknown"

    # Empreinte SHA256
    sha256: str = ""

    # Doublon ?
    duplicate: bool = False

    # Chemin de sortie après classement
    output_path: Path | None = None

    # Emplacement d'origine dans l'arborescence PhotoRec
    # Conservé séparément de ``path`` pour l'export et l'interface du rapport.
    source_path: Path | None = None

    # Dossier PhotoRec d'origine (par exemple : recup_dir.3)
    source_directory: str = ""

    @property
    def size_mb(self) -> float:
        """
        Taille en Mo.
        """
        return round(self.size / 1024 / 1024, 2)

    def __str__(self):

        return (
            f"{self.filename} | "
            f"{self.mime} | "
            f"{self.size_mb} MB"
        )
