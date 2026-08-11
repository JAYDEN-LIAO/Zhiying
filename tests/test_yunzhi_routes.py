"""yunzhi 集成新逻辑测试 — DB 幂等查重 + 排队中回调。"""
import json
import uuid
from unittest.mock import patch

import pytest

from core.models import PipelineTask
from core.schemas import YunzhiJobPayload, YunzhiJobCallback, YunzhiJobTask, YunzhiJobFile


def _payload():
    return YunzhiJobPayload(
        jobToken="tok-1",
        callback=YunzhiJobCallback(
            progressUrl="http://platform/progress",
            completeUrl="http://platform/complete",
            failUrl="http://platform/fail",
        ),
        task=YunzhiJobTask(automationJobId=8),
        file=YunzhiJobFile(id=100, name="a.mp4", absolutePath="/tmp/a.mp4"),
        operation="zhiying-video-analysis",
        eventId="evt-1",
        workDirectory="/tmp/wd",
    )


@pytest.mark.asyncio
async def test_lookup_task_biz_id_from_db(db_session_factory, fake_app):
    """重启后进程内 dict 丢失 → 按 pipeline_tasks.dedup_key 找回已登记任务（幂等跨重启）。"""
    from api.yunzhi_routes import _lookup_task_biz_id
    key = "idem-key-1"
    automation = "42"
    async with db_session_factory() as s:
        s.add(PipelineTask(
            id=uuid.uuid4(), type="yunzhi_job", dedup_key=key,
            payload_json=json.dumps({"task": {"automationJobId": automation}}),
            status="queued",
        ))
        await s.commit()
    assert await _lookup_task_biz_id(fake_app, key) == f"yunzhi-{automation}"
    assert await _lookup_task_biz_id(fake_app, "missing-key") is None


@pytest.mark.asyncio
async def test_send_queued_callback():
    """入队后向平台 progressUrl 发"排队中"低进度回调（best-effort）。"""
    from api.yunzhi_routes import _send_queued_callback
    captured = {}

    class FakeResp:
        status_code = 200

    class FakeClient:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResp()

    with patch("httpx.AsyncClient", FakeClient):
        await _send_queued_callback(_payload())
    assert captured["url"] == "http://platform/progress"
    assert captured["json"]["progress"] == 1
    assert "排队" in captured["json"]["message"]
    assert captured["headers"]["X-Yunzhi-Job-Token"] == "tok-1"
