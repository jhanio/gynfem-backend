"""Verifica que data/raw/Mathernal_Risk.csv no ha sido alterado."""

import hashlib
import re
from pathlib import Path

RAW_CSV = Path(__file__).resolve().parent.parent / "data" / "raw" / "Mathernal_Risk.csv"
RAW_README = Path(__file__).resolve().parent.parent / "data" / "raw" / "README.md"


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _recorded_sha256() -> str:
    text = RAW_README.read_text(encoding="utf-8")
    match = re.search(r"SHA-256:\*\*\s*`([0-9a-f]{64})`", text)
    assert match, "No se encontró el SHA-256 registrado en data/raw/README.md"
    return match.group(1)


def test_raw_csv_sha256_matches_readme():
    assert _sha256_of_file(RAW_CSV) == _recorded_sha256()
