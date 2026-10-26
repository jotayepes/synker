from synker.manifest.index import ManifestIndex, normalize_title


def test_index_drops_stubs_and_resolves_aliases(index):
    assert "Stub" not in index.games
    assert index.by_name("Old Name").title == "Native Game"
    assert index.by_steam_id(1000).title == "Proton Game"
    assert index.by_install_dir("protongame").title == "Proton Game"
    assert index.by_steam_id(4000).has_registry


def test_index_roundtrip(index, tmp_path):
    path = tmp_path / "idx.json.gz"
    index.save(path)
    loaded = ManifestIndex.load(path)
    assert set(loaded.games) == set(index.games)
    assert loaded.get("Cloud Game").cloud == {"steam": True}
    assert loaded.get("Proton Game").files[0].when == [{"os": "windows"}]


def test_normalize_title():
    assert normalize_title("Hollow Knight™") == normalize_title("hollow knight")
