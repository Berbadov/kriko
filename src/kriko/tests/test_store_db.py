import kriko.store.db as db_mod


def _fresh_home(tmp_path, monkeypatch):
    """Point DEFAULT_HOME/DEFAULT_STORE at an isolated tmp_path and reset
    the module's one-time warning flag, so each test starts clean and never
    touches the real `~/.kriko/`.
    """
    home = tmp_path / ".kriko"
    monkeypatch.setattr(db_mod, "DEFAULT_HOME", home)
    monkeypatch.setattr(db_mod, "DEFAULT_STORE", home / "knowledge.sqlite")
    monkeypatch.setattr(db_mod, "_warned_other_store_present", False)
    return home


def test_connect_default_warns_once_when_another_store_present(tmp_path, monkeypatch, capsys):
    home = _fresh_home(tmp_path, monkeypatch)
    home.mkdir(parents=True)
    (home / "packs.cars.pipeline.sqlite").write_bytes(b"")

    db_mod.connect().close()
    err = capsys.readouterr().err
    assert "knowledge.sqlite" in err
    assert "packs.cars.pipeline.sqlite" in err
    assert str(home / "knowledge.sqlite") in err
    assert str(home / "packs.cars.pipeline.sqlite") in err

    # Second default-path connect: no repeat warning.
    db_mod.connect().close()
    assert capsys.readouterr().err == ""


def test_connect_default_silent_when_no_other_store(tmp_path, monkeypatch, capsys):
    _fresh_home(tmp_path, monkeypatch)

    db_mod.connect().close()
    assert capsys.readouterr().err == ""


def test_connect_explicit_path_never_warns(tmp_path, monkeypatch, capsys):
    home = _fresh_home(tmp_path, monkeypatch)
    home.mkdir(parents=True)
    (home / "packs.cars.pipeline.sqlite").write_bytes(b"")

    db_mod.connect(tmp_path / "elsewhere.sqlite").close()
    assert capsys.readouterr().err == ""


def test_connect_does_not_touch_other_store_file(tmp_path, monkeypatch):
    home = _fresh_home(tmp_path, monkeypatch)
    home.mkdir(parents=True)
    legacy = home / "packs.cars.pipeline.sqlite"
    legacy.write_bytes(b"not-really-sqlite-but-untouched")
    before = legacy.read_bytes()

    db_mod.connect().close()

    assert legacy.read_bytes() == before
