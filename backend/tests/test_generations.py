import time
import threading


def _wait(client, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/generations/{job_id}")
        assert r.status_code == 200
        body = r.json()
        if body["status"] in ("succeeded", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError("任务未在超时内结束")


def test_txt2img_succeeds(client, project):
    r = client.post(
        f"/api/projects/{project['id']}/generations",
        json={"mode": "txt2img", "prompt": "极简大理石台面，柔和影棚光", "width": 1024, "height": 1024, "confirm_cost": True},
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    body = _wait(client, job_id)
    assert body["status"] == "succeeded"
    assert body["progress"] == 100
    assert body["result_asset_ids"]


def test_num_images_creates_independent_jobs(client, project):
    response = client.post(
        f"/api/projects/{project['id']}/generations",
        json={"mode": "txt2img", "prompt": "独立队列任务", "num_images": 3, "confirm_cost": True},
    )
    assert response.status_code == 202
    job_ids = response.json()["job_ids"]
    assert len(job_ids) == 3
    assert len(set(job_ids)) == 3
    jobs = [client.get(f"/api/generations/{job_id}").json() for job_id in job_ids]
    assert all(job["params"]["num_images"] == 1 for job in jobs)


def test_matting_succeeds(client, project):
    import io

    from PIL import Image

    img = Image.new("RGB", (16, 16), (255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    up = client.post(
        f"/api/projects/{project['id']}/assets",
        files={"file": ("口红.png", buf.getvalue(), "image/png")},
    )
    aid = up.json()["id"]

    r = client.post(f"/api/assets/{aid}/matting")
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    body = _wait(client, job_id)
    assert body["status"] == "succeeded"
    assert body["result_asset_ids"]


def test_model_not_ready_maps_to_failed(client, project):
    r = client.post(
        f"/api/projects/{project['id']}/generations",
        json={"mode": "txt2img", "prompt": "FAIL", "confirm_cost": True},
    )
    job_id = r.json()["job_id"]
    body = _wait(client, job_id)
    assert body["status"] == "failed"
    assert body["error"]


def test_unsupported_mode_rejected(client, project):
    r = client.post(
        f"/api/projects/{project['id']}/generations",
        json={"mode": "img2img", "prompt": "x"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "NOT_SUPPORTED"


def test_empty_prompt_rejected(client, project):
    r = client.post(
        f"/api/projects/{project['id']}/generations",
        json={"mode": "txt2img", "prompt": "   "},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_PARAMS"


def test_cloud_generation_requires_explicit_cost_confirmation(client, project):
    response = client.post(
        f"/api/projects/{project['id']}/generations",
        json={"mode": "txt2img", "prompt": "这条请求不得提交"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "COST_CONFIRMATION_REQUIRED"
    assert client.app.state.store.list_generations(project["id"]) == []


def test_missing_token_fails_cleanly(client, project):
    """未配置 API 密钥时，任务应如实失败而非假装成功。"""
    client.app.state.tasks.settings.dashscope_api_key = ""
    client.app.state.tasks.settings.dashscope_base_url = ""
    client.app.state.tasks._engine = None  # 用真实引擎（replicate 无 token）
    r = client.post(
        f"/api/projects/{project['id']}/generations",
        json={"mode": "txt2img", "prompt": "测试", "confirm_cost": True},
    )
    assert r.status_code == 202
    body = _wait(client, r.json()["job_id"])
    assert body["status"] == "failed"
    assert "DASHSCOPE_API_KEY" in (body["error"] or "")


def test_retry_failed_creates_new_job(client, project):
    r = client.post(
        f"/api/projects/{project['id']}/generations",
        json={"mode": "txt2img", "prompt": "FAIL", "confirm_cost": True},
    )
    job1 = r.json()["job_id"]
    body1 = _wait(client, job1)
    assert body1["status"] == "failed"

    unconfirmed_retry = client.post(f"/api/generations/{job1}/retry")
    assert unconfirmed_retry.status_code == 409
    assert unconfirmed_retry.json()["error"]["code"] == "COST_CONFIRMATION_REQUIRED"
    r2 = client.post(f"/api/generations/{job1}/retry", json={"confirm_cost": True})
    assert r2.status_code == 202
    job2 = r2.json()["job_id"]
    assert job2 != job1
    body2 = _wait(client, job2)
    # 同参数仍会失败，但重试机制（新任务 + 复用参数）成立
    assert body2["status"] == "failed"


def test_retry_rejected_for_succeeded(client, project):
    r = client.post(
        f"/api/projects/{project['id']}/generations",
        json={"mode": "txt2img", "prompt": "正常", "confirm_cost": True},
    )
    job = _wait(client, r.json()["job_id"])
    assert job["status"] == "succeeded"
    r2 = client.post(f"/api/generations/{job['id']}/retry")
    assert r2.status_code == 400


def test_retry_interrupted_requires_unknown_status_confirmation(client, project):
    job = client.app.state.store.create_generation(project["id"], {"mode": "txt2img", "prompt": "中断测试"})
    job_id = job["id"]
    client.app.state.store.update_generation(
        job_id,
        status="interrupted",
        error="云端状态不明",
    )

    retry = client.post(f"/api/generations/{job_id}/retry")
    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "TASK_STATUS_UNKNOWN"

    cost_unconfirmed = client.post(
        f"/api/generations/{job_id}/retry",
        json={"confirm_unknown_status": True},
    )
    assert cost_unconfirmed.status_code == 409
    assert cost_unconfirmed.json()["error"]["code"] == "COST_CONFIRMATION_REQUIRED"

    confirmed = client.post(
        f"/api/generations/{job_id}/retry",
        json={"confirm_unknown_status": True, "confirm_cost": True},
    )
    assert confirmed.status_code == 202
    assert confirmed.json()["job_id"] != job_id


def test_cancel_terminal_returns_status(client, project):
    r = client.post(
        f"/api/projects/{project['id']}/generations",
        json={"mode": "txt2img", "prompt": "正常", "confirm_cost": True},
    )
    job = _wait(client, r.json()["job_id"])
    assert job["status"] == "succeeded"
    r2 = client.post(f"/api/generations/{job['id']}/cancel")
    assert r2.status_code == 200
    assert r2.json()["status"] == "succeeded"  # 已终态不改变


def _install_blocking_engine(client):
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    engine = client.app.state.tasks.engine

    def run(mode, params, project_id, on_progress):
        try:
            on_progress(35, "sampling")
            entered.set()
            if not release.wait(3):
                raise AssertionError("test did not release the blocked task")
            on_progress(80, "decoding")
            return {"asset_ids": []}
        finally:
            finished.set()

    engine.run = run
    return entered, release, finished


def test_running_cloud_cancel_remains_interrupted_and_does_not_resubmit(client, project):
    entered, release, finished = _install_blocking_engine(client)
    try:
        response = client.post(
            f"/api/projects/{project['id']}/generations",
            json={"mode": "txt2img", "prompt": "被取消的云端任务", "confirm_cost": True},
        )
        job_id = response.json()["job_id"]
        assert entered.wait(2)

        cancelled = client.post(f"/api/generations/{job_id}/cancel").json()
        assert cancelled["status"] == "interrupted"
        assert "百炼" in cancelled["error"]
        assert "避免重复提交" in cancelled["error"]
        release.set()
        assert finished.wait(2)

        final = client.get(f"/api/generations/{job_id}").json()
        assert final["status"] == "interrupted"
        assert final["error"] == cancelled["error"]
        assert len(client.app.state.store.list_generations(project["id"])) == 1
        assert client.post(f"/api/generations/{job_id}/retry").json()["error"]["code"] == "TASK_STATUS_UNKNOWN"
    finally:
        release.set()


def test_running_local_matting_cancel_has_no_cloud_warning_and_can_retry(client, project):
    import io

    from PIL import Image

    image = Image.new("RGB", (16, 16), (200, 0, 0))
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    imported = client.post(
        f"/api/projects/{project['id']}/assets",
        files={"file": ("product.png", encoded.getvalue(), "image/png")},
    )
    entered, release, finished = _install_blocking_engine(client)
    try:
        response = client.post(f"/api/assets/{imported.json()['id']}/matting")
        job_id = response.json()["job_id"]
        assert entered.wait(2)

        cancelled = client.post(f"/api/generations/{job_id}/cancel").json()
        assert cancelled["status"] == "cancelled"
        assert "本地任务已取消" in cancelled["error"]
        assert "百炼" not in cancelled["error"]
        release.set()
        assert finished.wait(2)

        final = client.get(f"/api/generations/{job_id}").json()
        assert final["status"] == "cancelled"
        assert final["error"] == cancelled["error"]
    finally:
        release.set()

    retry = client.post(f"/api/generations/{job_id}/retry")
    assert retry.status_code == 202
    assert _wait(client, retry.json()["job_id"])["status"] == "succeeded"


def test_result_asset_retrievable_and_placeable(client, project):
    """任务结果 ID 必须能查到素材、图片接口可访问、能置入画布。"""
    r = client.post(
        f"/api/projects/{project['id']}/generations",
        json={"mode": "txt2img", "prompt": "极简大理石台面", "confirm_cost": True},
    )
    body = _wait(client, r.json()["job_id"])
    assert body["status"] == "succeeded"
    aid = body["result_asset_ids"][0]

    # 能通过接口查到素材元数据（不存在时这里会 404）
    asset = client.get(f"/api/assets/{aid}/file")
    assert asset.status_code == 200
    assert asset.headers.get("content-type", "").startswith("image/")

    # 能置入画布：图层 content.asset_id 引用该 id，PUT 成功且能读回
    layer = {
        "id": "l_img",
        "project_id": project["id"],
        "type": "image",
        "name": "生成结果",
        "z": 0,
        "content": {"asset_id": aid},
    }
    assert client.put(f"/api/projects/{project['id']}/layers", json={"layers": [layer]}).status_code == 204
    got = client.get(f"/api/projects/{project['id']}/layers").json()
    assert got[0]["content"]["asset_id"] == aid
