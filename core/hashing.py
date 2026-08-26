"""
CarvEx
SHA256 Hashing
"""

import hashlib
from pathlib import Path

BUFFER_SIZE = 1024 * 1024  # 1 Mo


class Hasher:

    @staticmethod
    def sha256(path: Path) -> str:

        digest = hashlib.sha256()

        with open(path, "rb") as f:

            while True:

                chunk = f.read(BUFFER_SIZE)

                if not chunk:
                    break

                digest.update(chunk)

        return digest.hexdigest()
