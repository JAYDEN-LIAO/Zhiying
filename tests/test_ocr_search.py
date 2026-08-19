"""OCR 检索测试（v0.34）— 归一化规则 + ocr_text_search 查询结构/过滤。

不使用真实 PostgreSQL（levenshtein/ILIKE/translate 为 PG 专属）：
用 AsyncMock 会话捕获生成的 SQL，编译为 PG dialect 后断言结构，验证 video_ids 过滤。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects import postgresql

from core.search import ocr_text_search, _normalize_plate


@pytest.mark.asyncio
async def test_ocr_text_search_filters_video_ids():
    """video_ids 传入 → SQL 含 IN 过滤且绑定对应 id；不传 → 无过滤。"""
    rows, stmt = await _run_search("五点半到", video_ids=["u-1", "u-2"])
    assert rows == []
    compiled = stmt.compile(dialect=postgresql.dialect())
    sql, params = str(compiled), compiled.params
    assert "ocr_detections" in sql
    assert "ILIKE" in sql and "levenshtein" in sql
    # video_id IN 展开为参数列表 → 校验两 id 都绑定了过滤
    in_bind = [v for v in params.values() if isinstance(v, (list, tuple))]
    assert any("u-1" in v and "u-2" in v for v in in_bind)

    _, stmt_all = await _run_search("五点半到", video_ids=None)
    c2 = stmt_all.compile(dialect=postgresql.dialect())
    in_bind2 = [v for v in c2.params.values() if isinstance(v, (list, tuple))]
    assert not any("u-1" in v or "u-2" in v for v in in_bind2)


@pytest.mark.asyncio
async def test_ocr_text_search_binds_normalized_query():
    """查询侧走归一化（全角→半角/去分隔符/大写）后绑定，与 DB 侧 _plate_norm_sql 同源。"""
    _, stmt = await _run_search("ＧＡ ８８２５・ＡＢ", video_ids=None)
    params = stmt.compile(dialect=postgresql.dialect()).params
    assert "GA8825AB" in params.values()   # 归一化后的查询已用于 ILIKE/levenshtein


def test_normalize_plate_on_chat_text():
    """归一化对聊天文本适用：全角→半角、去分隔符、中文透传、统一大写。"""
    assert _normalize_plate("ＧＡ ８８２５・ＡＢ") == "GA8825AB"
    assert _normalize_plate("ＡＢＣ-１２３") == "ABC123"
    assert _normalize_plate("五点半到") == "五点半到"       # 中文原样
    assert _normalize_plate("现在 到 楼 下 了") == "现在到楼下了"  # 空格是分隔符
    assert _normalize_plate("I'll be there at 9.30") == "I'LLBETHEREAT930"  # 撇号非分隔符,保留


# ── OcrRunner._dedup_tracklets 去重 + 时序整理（不依赖 DB） ──

def _line(text, y1=0.5, conf=0.8, x1=0.1):
    return {"text": text, "bbox": {"x1": x1, "y1": y1, "x2": x1 + 0.6, "y2": y1 + 0.2},
            "confidence": conf}


def test_dedup_keeps_early_sliding_messages():
    """回归：滚动聊天中早期消息（先上屏、随后滚走）必须全部保留，不得被丢弃。"""
    from pipeline.runners.ocr import _dedup_tracklets
    frames = [
        (0.0, [_line("你好", y1=0.05), _line("你好啊", y1=0.30)]),
        (1.0, [_line("你好", y1=0.05), _line("你好啊", y1=0.30), _line("你吃饭了吗", y1=0.55)]),
        (2.0, [_line("你吃饭了吗", y1=0.55), _line("刚刚吃完", y1=0.80)]),
        (6.0, [_line("刚刚吃完", y1=0.80), _line("那你呢", y1=0.15)]),
        (11.5, [_line("今天天气不错", y1=0.20)]),
    ]
    res = _dedup_tracklets("vid", frames)
    texts = [r["text"] for r in res]
    for expect in ["你好", "你好啊", "你吃饭了吗", "刚刚吃完", "那你呢", "今天天气不错"]:
        assert expect in texts, "缺失早期消息: " + expect
    assert (res[0]["timestamp_sec"], res[0]["bbox"]["y1"]) == (0.0, 0.05)


def test_dedup_global_merge_same_text():
    """同文本在视频内多次出现（滚动复读，即使跨 5s）→ 全局合并成 1 条，
    时间钉首现、取最佳置信读取。"""
    from pipeline.runners.ocr import _dedup_tracklets
    frames = [
        (0.0, [_line("你好", y1=0.30, conf=0.6)]),
        (2.0, [_line("你好", y1=0.35, conf=0.95)]),   # 同文本滚动
        (10.0, [_line("你好", y1=0.40, conf=0.5)]),   # 跨窗再现仍是同一条
    ]
    res = _dedup_tracklets("vid", frames)
    y = [r for r in res if r["text"] == "你好"]
    assert len(y) == 1, "全局合并应只 1 条, got %d" % len(y)
    assert y[0]["timestamp_sec"] == 0.0                # 首现时间
    assert y[0]["confidence"] == 0.95                  # 最佳置信读取


def test_dedup_fixed_text_read_once():
    """顶部固定文字（位置不动持续多帧，如状态栏时间）→ 只输出 1 条（首次）。"""
    from pipeline.runners.ocr import _dedup_tracklets
    frames = [(i * 0.5, [_line("20:02", y1=0.02, conf=0.8)]) for i in range(24)]
    res = _dedup_tracklets("vid", frames)
    y = [r for r in res if r["text"] == "20:02"]
    assert len(y) == 1, "固定文字应只 1 条, got %d" % len(y)
    assert y[0]["timestamp_sec"] == 0.0


def test_dedup_distinct_texts_all_kept_sorted():
    """不同文本全部保留，输出按 (时间, y1, x1) 阅读序升序。"""
    from pipeline.runners.ocr import _dedup_tracklets
    frames = [
        (0.0, [_line("你好", y1=0.30), _line("你好啊", y1=0.10)]),
        (1.0, [_line("在吗", y1=0.50)]),
    ]
    res = _dedup_tracklets("vid", frames)
    assert {r["text"] for r in res} == {"你好", "你好啊", "在吗"}
    keys = [(r["timestamp_sec"], r["bbox"]["y1"], r["bbox"]["x1"]) for r in res]
    assert keys == sorted(keys), "应按阅读序升序"


def test_dedup_dynamic_merged_fixed_persistent():
    """顶部固定字段全程静止→ 只 1 条；滚动消息同文本不同位置→ 各自也只 1 条（全局合并）。"""
    from pipeline.runners.ocr import _dedup_tracklets
    frames = [(i * 0.5,
               [_line("已备餐", y1=0.01, conf=0.7),
                _line("消息%d" % (i // 2), y1=0.5 + (i % 2) * 0.3, conf=0.8)])
              for i in range(12)]
    res = _dedup_tracklets("vid", frames)
    texts = {r["text"] for r in res}
    assert texts == {"已备餐"} | {"消息%d" % i for i in range(6)}
    yip = [r for r in res if r["text"] == "已备餐"]
    assert len(yip) == 1 and yip[0]["timestamp_sec"] == 0.0   # 固定文字只 1 条
    for i in range(6):
        m = [r for r in res if r["text"] == "消息%d" % i]
        assert len(m) == 1, "消息%d 应全局合并 1 条, got %d" % (i, len(m))


async def _run_search(query: str, video_ids=None):
    """以桩会话执行 ocr_text_search，返回 (rows, 已捕获的 SQL statement)。"""
    session = AsyncMock()
    res = MagicMock()
    session.execute.return_value = res
    res.scalars.return_value.all.return_value = []
    rows = await ocr_text_search(session, query, video_ids=video_ids)
    stmt = session.execute.call_args[0][0]
    return rows, stmt