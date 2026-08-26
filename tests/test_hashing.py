from core.hashing import Hasher


def test_sha256_is_deterministic_for_a_local_fixture(tmp_path) -> None:
    source = tmp_path / "evidence.bin"
    source.write_bytes(b"CarvEx")

    assert Hasher.sha256(source) == "6a8674efee7638a4766a32995d485bb5b540735d167cbdca026d003c9790049d"
