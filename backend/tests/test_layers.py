def test_put_and_get_layers(client, project):
    layers = [
        {
            "id": "l_1", "project_id": project["id"], "type": "image",
            "name": "口红-抠图", "z": 0, "x": 10, "y": 20, "w": 512, "h": 512,
            "opacity": 1.0, "visible": True, "locked": False, "blend": "normal",
            "content": {"asset_id": "a_1"},
        },
        {
            "id": "l_2", "project_id": project["id"], "type": "text",
            "name": "促销文案", "z": 1, "content": {"text": "限时5折"},
        },
    ]
    r = client.put(f"/api/projects/{project['id']}/layers", json={"layers": layers})
    assert r.status_code == 204

    r = client.get(f"/api/projects/{project['id']}/layers")
    assert r.status_code == 200
    got = r.json()
    assert len(got) == 2
    assert got[0]["content"]["asset_id"] == "a_1"
    assert got[1]["content"]["text"] == "限时5折"


def test_rotation_persists_in_layers_and_snapshot(client, project):
    layer = {
        "id": "l_rotated",
        "project_id": project["id"],
        "type": "text",
        "name": "旋转文字",
        "rotation": 45,
        "content": {"text": "旋转"},
    }
    response = client.put(f"/api/projects/{project['id']}/layers", json={"layers": [layer]})
    assert response.status_code == 204

    layers = client.get(f"/api/projects/{project['id']}/layers").json()
    snapshot = client.get(f"/api/projects/{project['id']}/layers/snapshot").json()
    assert layers[0]["rotation"] == 45
    assert snapshot["layers"][0]["rotation"] == 45

    from app.store import Store

    reopened_store = Store(client.app.state.settings.data_dir)
    assert reopened_store.get_layers(project["id"])[0]["rotation"] == 45
    assert reopened_store.latest_valid_snapshot(project["id"])["layers"][0]["rotation"] == 45


def test_legacy_layers_and_snapshots_default_rotation_to_zero(tmp_path):
    import json
    import sqlite3

    from app.store import Store

    data_dir = tmp_path / "legacy-data"
    data_dir.mkdir()
    database = sqlite3.connect(data_dir / "app.db")
    database.executescript(
        """
        CREATE TABLE projects (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, canvas_w INTEGER NOT NULL,
            canvas_h INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE layers (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, type TEXT NOT NULL,
            name TEXT NOT NULL, z INTEGER NOT NULL DEFAULT 0, x REAL DEFAULT 0,
            y REAL DEFAULT 0, w REAL DEFAULT 0, h REAL DEFAULT 0,
            opacity REAL NOT NULL DEFAULT 1.0, visible INTEGER NOT NULL DEFAULT 1,
            locked INTEGER NOT NULL DEFAULT 0, blend TEXT NOT NULL DEFAULT 'normal',
            content TEXT NOT NULL DEFAULT '{}', created_at TEXT, updated_at TEXT
        );
        CREATE TABLE snapshots (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, layers TEXT NOT NULL,
            created_at TEXT NOT NULL, reason TEXT NOT NULL DEFAULT 'auto'
        );
        INSERT INTO projects VALUES('p_legacy', '旧项目', 1080, 1080, 'created', 'updated');
        INSERT INTO layers(id, project_id, type, name, content)
            VALUES('l_legacy', 'p_legacy', 'text', '旧文字', '{"text":"兼容"}');
        """
    )
    legacy_snapshot = [{"id": "l_legacy", "project_id": "p_legacy", "type": "text", "content": {"text": "兼容"}}]
    database.execute(
        "INSERT INTO snapshots VALUES(?, ?, ?, ?, ?)",
        ("s_legacy", "p_legacy", json.dumps(legacy_snapshot), "created", "auto"),
    )
    database.commit()
    database.close()

    store = Store(str(data_dir))
    assert store.get_layers("p_legacy")[0]["rotation"] == 0
    snapshot = store.latest_valid_snapshot("p_legacy")
    assert snapshot["layers"][0]["rotation"] == 0


def test_layers_persist_after_restart(client, project, tmp_path, monkeypatch):
    layers = [{"id": "l_1", "project_id": project["id"], "type": "text", "name": "x", "z": 0, "content": {"text": "持久化"}}]
    client.put(f"/api/projects/{project['id']}/layers", json={"layers": layers})

    # 用同一数据目录重新打开 Store，验证落盘可恢复
    from app.store import Store

    data_dir = tmp_path / "data"
    store2 = Store(str(data_dir))
    got = store2.get_layers(project["id"])
    assert len(got) == 1
    assert got[0]["content"]["text"] == "持久化"
    snapshot = client.get(f"/api/projects/{project['id']}/layers/snapshot").json()
    assert snapshot["layers"][0]["content"]["text"] == "持久化"


def test_layers_project_not_found(client):
    r = client.put("/api/projects/p_none/layers", json={"layers": []})
    assert r.status_code == 404


def test_exit_save_beacon_persists_snapshot(client, project):
    layers = [{"id": "l_exit", "project_id": project["id"], "type": "text", "content": {"text": "关闭前保存"}}]
    response = client.post(f"/api/projects/{project['id']}/layers/beacon", json={"layers": layers})
    assert response.status_code == 204
    assert client.get(f"/api/projects/{project['id']}/layers").json()[0]["content"]["text"] == "关闭前保存"


def test_latest_snapshot_falls_back_when_asset_is_missing(client, project):
    from app.store import Store

    client.put(
        f"/api/projects/{project['id']}/layers",
        json={"layers": [{"id": "l_ok", "project_id": project["id"], "type": "text", "content": {"text": "有效快照"}}]},
    )
    client.put(
        f"/api/projects/{project['id']}/layers",
        json={"layers": [{"id": "l_missing", "project_id": project["id"], "type": "image", "content": {"asset_id": "a_missing"}}]},
    )
    snapshot = Store(client.app.state.settings.data_dir).latest_valid_snapshot(project["id"])
    assert snapshot is not None
    assert snapshot["layers"][0]["id"] == "l_ok"
