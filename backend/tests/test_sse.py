def test_sse_ends_with_done(client, project):
    with client.stream("GET", f"/api/sse/tasks?project_id={project['id']}") as stream:
        # 流已建立后再提交任务
        client.post(
            f"/api/projects/{project['id']}/generations",
            json={"mode": "txt2img", "prompt": "测试", "confirm_cost": True},
        )
        events = []
        for line in stream.iter_lines():
            if line.startswith("data: "):
                events.append(line[len("data: "):])
                if '"type": "done"' in line or '"type": "error"' in line:
                    break
        assert events, "未收到任何 SSE 事件"
        assert any('"type": "done"' in e for e in events) or any('"type": "error"' in e for e in events)


def test_sse_error_structure(client, project):
    with client.stream("GET", f"/api/sse/tasks?project_id={project['id']}") as stream:
        client.post(
            f"/api/projects/{project['id']}/generations",
            json={"mode": "txt2img", "prompt": "FAIL", "confirm_cost": True},
        )
        for line in stream.iter_lines():
            if line.startswith("data: "):
                if '"type": "error"' in line:
                    import json as _json

                    payload = _json.loads(line[len("data: "):])
                    assert payload["error"]["code"] == "MODEL_NOT_READY"
                    break
