import itertools

import pytest

from clipboard_history.storage import Storage, content_hash


@pytest.fixture
def store(tmp_path):
    counter = itertools.count(1000)
    s = Storage(tmp_path / "history.db", tmp_path / "images", clock=lambda: float(next(counter)))
    yield s
    s.close()


def texts(items):
    return [i.text for i in items]


def test_add_text_and_list_newest_first(store):
    store.add_text("uno")
    store.add_text("due")
    store.add_text("tre")
    assert texts(store.list()) == ["tre", "due", "uno"]


def test_empty_text_is_ignored(store):
    assert store.add_text("") is None
    assert store.list() == []


def test_dedup_moves_to_top_without_duplicating(store):
    first = store.add_text("uno")
    store.add_text("due")
    again = store.add_text("uno")
    assert again == first
    assert texts(store.list()) == ["uno", "due"]


def test_dedup_preserves_pin(store):
    a = store.add_text("uno")
    store.pin(a, True)
    store.add_text("due")
    store.add_text("uno")
    item = store.get(a)
    assert item.pinned
    assert len(store.list()) == 2


def test_pinned_items_come_first(store):
    a = store.add_text("vecchio")
    store.add_text("nuovo")
    store.pin(a, True)
    assert texts(store.list()) == ["vecchio", "nuovo"]
    store.pin(a, False)
    assert texts(store.list()) == ["nuovo", "vecchio"]


def test_prune_keeps_25_unpinned_and_all_pinned(store):
    pinned = store.add_text("pinnato")
    store.pin(pinned, True)
    for n in range(30):
        store.add_text(f"t{n}")
    items = store.list()
    unpinned = [i for i in items if not i.pinned]
    assert len(unpinned) == 25
    # the oldest five are gone, the newest kept
    assert "t0" not in texts(items) and "t4" not in texts(items)
    assert "t5" in texts(items) and "t29" in texts(items)
    assert store.get(pinned).pinned


def test_prune_with_custom_limit(store):
    for n in range(5):
        store.add_text(f"t{n}")
    store.prune(limit=2)
    assert texts(store.list()) == ["t4", "t3"]


def test_clear_unpinned_keeps_pinned(store):
    a = store.add_text("tienimi")
    store.pin(a, True)
    store.add_text("via1")
    store.add_text("via2")
    store.clear_unpinned()
    assert texts(store.list()) == ["tienimi"]


def test_delete(store):
    a = store.add_text("uno")
    store.add_text("due")
    store.delete(a)
    assert texts(store.list()) == ["due"]
    assert store.get(a) is None


def test_touch_moves_to_top(store):
    a = store.add_text("uno")
    store.add_text("due")
    store.touch(a)
    assert texts(store.list()) == ["uno", "due"]


def test_list_filter_is_case_insensitive_and_hides_images(store):
    store.add_text("Ciao Mondo")
    store.add_text("altro")
    store.add_image(b"\x89PNGfake")
    assert texts(store.list("mondo")) == ["Ciao Mondo"]
    assert len(store.list("")) == 3
    assert len(store.list(None)) == 3


def test_filter_escapes_like_wildcards(store):
    store.add_text("100%")
    store.add_text("1000")
    assert texts(store.list("%")) == ["100%"]


def test_add_image_writes_png_and_dedups(store, tmp_path):
    data = b"\x89PNGfake-bytes"
    a = store.add_image(data)
    item = store.get(a)
    assert item.kind == "image"
    assert item.image_path.endswith(f"{content_hash(data)}.png")
    with open(item.image_path, "rb") as f:
        assert f.read() == data
    assert store.add_image(data) == a
    assert len(store.list()) == 1


def test_delete_and_prune_remove_image_files(store):
    import os
    a = store.add_image(b"img-a")
    path = store.get(a).image_path
    store.delete(a)
    assert not os.path.exists(path)

    b = store.add_image(b"img-b")
    path_b = store.get(b).image_path
    store.clear_unpinned()
    assert not os.path.exists(path_b)


def test_persistence_across_reopen(tmp_path):
    s = Storage(tmp_path / "h.db", tmp_path / "images")
    a = s.add_text("persistente")
    s.pin(a, True)
    s.close()
    s2 = Storage(tmp_path / "h.db", tmp_path / "images")
    assert s2.get(a).pinned
    assert s2.list()[0].text == "persistente"
    s2.close()


def test_find_by_hash(store):
    a = store.add_text("uno")
    assert store.find_by_hash(content_hash("uno".encode())).id == a
    assert store.find_by_hash("nope") is None
