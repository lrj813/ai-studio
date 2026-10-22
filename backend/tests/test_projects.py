def test_create_and_list(client):
    r = client.post("/api/projects", json={"name": "口红主图", "canvas": {"w": 800, "h": 800}})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "口红主图"
    assert body["canvas"] == {"w": 800, "h": 800}

    r = client.get("/api/projects")
    assert r.status_code == 200
    assert any(p["id"] == body["id"] for p in r.json())


def test_get_project(client, project):
    r = client.get(f"/api/projects/{project['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == project["id"]
    assert client.get("/api/projects/p_missing").json()["error"]["code"] == "PROJECT_NOT_FOUND"


def test_preset_project_has_real_product_photo_and_editable_layers(client):
    response = client.post("/api/projects/preset")
    assert response.status_code == 201
    project = response.json()
    assets = client.get(f"/api/projects/{project['id']}/assets").json()
    layers = client.get(f"/api/projects/{project['id']}/layers").json()
    assert len(assets) == 1
    assert assets[0]["filename"].startswith("公共领域示例")
    assert assets[0]["width"] == 1280
    assert any(layer["type"] == "text" and layer["content"].get("text") == "复古玫瑰香氛" for layer in layers)
    assert any(layer["type"] == "image" and layer["content"].get("asset_id") == assets[0]["id"] for layer in layers)


def test_project_refresh_route_serves_spa(client, project):
    response = client.get(f"/project/{project['id']}")
    if response.status_code == 200:
        assert "<div id=\"root\">" in response.text
    else:
        assert response.status_code == 404


def test_duplicate_name_auto_suffix(client):
    client.post("/api/projects", json={"name": "同名"})
    r = client.post("/api/projects", json={"name": "同名"})
    assert r.status_code == 201
    assert r.json()["name"] == "同名-1"


def test_name_validation(client):
    assert client.post("/api/projects", json={"name": ""}).status_code == 422
    assert client.post("/api/projects", json={"name": "x" * 51}).status_code == 422


def test_update_and_delete(client, project):
    r = client.patch(f"/api/projects/{project['id']}", json={"name": "新名字"})
    assert r.status_code == 200
    assert r.json()["name"] == "新名字"
    assert client.patch(f"/api/projects/{project['id']}", json={"name": "新名字"}).json()["name"] == "新名字"

    assert client.delete(f"/api/projects/{project['id']}").status_code == 204
    assert client.get("/api/projects").json() == []


def test_not_found(client):
    assert client.patch("/api/projects/p_none", json={"name": "x"}).status_code == 404
    assert client.delete("/api/projects/p_none").status_code == 404
