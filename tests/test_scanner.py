from core.scanner import Scanner


def test_scanner_uses_the_given_directory_and_ignores_known_system_files(tmp_path) -> None:
    (tmp_path / "document.txt").write_text("CarvEx", encoding="utf-8")
    (tmp_path / "Thumbs.db").write_bytes(b"ignored")

    files = Scanner(str(tmp_path)).scan()

    assert [file.filename for file in files] == ["document.txt"]
    assert files[0].mime == "text/plain"
