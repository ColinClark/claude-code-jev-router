"""Persistence across independent Store instances."""

from pathlib import Path

from tinykv.store import Store

from .conftest import FakeClock


def test_new_instance_sees_data_written_by_another(db_path: Path) -> None:
    writer = Store(db_path)
    writer.set("s", "text")
    writer.set("n", 7)
    writer.set("d", {"x": [1, 2, {"y": None}]})

    reader = Store(db_path)
    assert reader.get("s") == "text"
    assert reader.get("n") == 7
    assert reader.get("d") == {"x": [1, 2, {"y": None}]}
    assert sorted(reader.keys()) == ["d", "n", "s"]


def test_delete_persists_across_instances(db_path: Path) -> None:
    Store(db_path).set("a", 1)
    Store(db_path).set("b", 2)
    Store(db_path).delete("a")
    assert Store(db_path).keys() == ["b"]


def test_instances_have_no_stale_cache(db_path: Path) -> None:
    first = Store(db_path)
    second = Store(db_path)
    first.set("k", "from-first")
    assert second.get("k") == "from-first"
    second.set("k", "from-second")
    assert first.get("k") == "from-second"


def test_ttl_persists_across_instances(db_path: Path, clock: FakeClock) -> None:
    Store(db_path).set("k", "v", ttl=10)
    assert Store(db_path).get("k") == "v"
    clock.advance(11)
    assert Store(db_path).get("k") is None


def test_fresh_store_on_nonexistent_path_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "does-not-exist.json"
    store = Store(path)
    assert store.keys() == []
    assert store.get("anything") is None
    assert not path.exists()  # reads must not create the file


def test_first_write_creates_file(tmp_path: Path) -> None:
    path = tmp_path / "new.json"
    assert not path.exists()
    Store(path).set("k", "v")
    assert path.is_file()
    assert Store(path).get("k") == "v"


def test_first_write_creates_missing_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "db.json"
    Store(str(path)).set("k", "v")
    assert path.is_file()
    assert Store(path).get("k") == "v"


def test_delete_on_nonexistent_path_does_not_raise(tmp_path: Path) -> None:
    path = tmp_path / "absent.json"
    Store(path).delete("k")
    assert Store(path).keys() == []


def test_no_temp_files_left_behind(tmp_path: Path) -> None:
    path = tmp_path / "db.json"
    store = Store(path)
    for i in range(5):
        store.set(f"k{i}", i)
    store.delete("k0")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
