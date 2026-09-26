"""Data written by one Store instance is visible to another on the same path."""

from __future__ import annotations

from tinykv.store import Store


def test_second_instance_sees_data(tmp_path):
    path = tmp_path / "db.json"
    writer = Store(path)
    writer.set("s", "text")
    writer.set("n", 12)
    writer.set("d", {"x": [1, 2, 3]})

    reader = Store(path)
    assert reader.get("s") == "text"
    assert reader.get("n") == 12
    assert reader.get("d") == {"x": [1, 2, 3]}
    assert sorted(reader.keys()) == ["d", "n", "s"]


def test_deletes_and_updates_visible_across_instances(tmp_path):
    path = tmp_path / "db.json"
    a = Store(path)
    b = Store(path)
    a.set("k", 1)
    assert b.get("k") == 1
    b.set("k", 2)
    assert a.get("k") == 2
    a.delete("k")
    assert b.get("k") is None
    assert b.keys() == []


def test_str_path_and_pathlike_equivalent(tmp_path):
    path = tmp_path / "db.json"
    Store(str(path)).set("k", "v")
    assert Store(path).get("k") == "v"


def test_missing_file_is_empty_store(tmp_path):
    store = Store(tmp_path / "nothing.json")
    assert store.keys() == []
    assert store.get("k") is None
    assert not (tmp_path / "nothing.json").exists()
