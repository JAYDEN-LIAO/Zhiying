"""
services/ai_detect_service.py
═══════════════════════════════════════════════════════════
AICheck CLI 调用封装 — AI 生成内容检测。

提供两层接口：
  - run_ai_check(file_path, deep=False) → dict    (subprocess 调用 aic)
  - check_ai_check_available() → bool              (检测 aic 是否在 PATH 中)

优雅降级：aic 未安装时返回 status="error"，不崩服务。
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# AICheck 可执行文件名
AIC_CLI = "aic"


def check_ai_check_available() -> bool:
    """检测 AICheck CLI 是否在系统 PATH 中。"""
    return shutil.which(AIC_CLI) is not None


async def run_ai_check(file_path: str | Path, deep: bool = False) -> dict[str, Any]:
    """运行 AICheck 进行 AI 生成内容检测。

    Args:
        file_path: 视频文件路径。
        deep: 是否启用 --deep 模式（像素级水印分析）。

    Returns:
        标准化的检测结果 dict:
        {
            "status": "completed" | "error",
            "score": float | None,          # 0.0~1.0, 1.0=AI 生成
            "verdict": "ai_generated" | "no_signal" | "error" | None,
            "signals": [...],
            "software_info": [...],
            "error_message": str | None,
        }
    """
    # 检查 CLI 是否可用
    if not check_ai_check_available():
        logger.warning("AICheck CLI (%s) not found in PATH. AI detection disabled.", AIC_CLI)
        return _error_result("AICheck CLI not installed or not in PATH")

    file_path_str = str(file_path)
    args = [AIC_CLI, "--json", "check"]
    if deep:
        args.append("--deep")
    args.append(file_path_str)

    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        timeout = 30 if deep else 5
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            logger.warning("AICheck timed out after %ss (deep=%s)", timeout, deep)
            return _error_result(f"AICheck timed out after {timeout}s")

        stdout_str = stdout.decode("utf-8", errors="replace").strip()
        stderr_str = stderr.decode("utf-8", errors="replace").strip()

        # AICheck 返回码: 0=detected, 1=not detected, 2=error
        if process.returncode == 2:
            logger.warning("AICheck error (rc=2): %s", stderr_str[:500])
            return _error_result(stderr_str[:500] or "AICheck returned error status")

        # 解析 JSON 输出
        if stdout_str:
            try:
                raw = json.loads(stdout_str)
            except json.JSONDecodeError:
                logger.warning("AICheck output not valid JSON: %.200s", stdout_str)
                return _error_result("AICheck output is not valid JSON")
        else:
            logger.warning("AICheck produced no output (rc=%s)", process.returncode)
            return _error_result(f"AICheck returned empty output (rc={process.returncode})")

        # 标准化输出
        return _normalize_result(raw, deep)

    except OSError as e:
        logger.error("Failed to run AICheck: %s", e)
        return _error_result(str(e))


# ═══════════════════════════════════════════════════════════
# 内部函数
# ═══════════════════════════════════════════════════════════

def _error_result(error_message: str) -> dict[str, Any]:
    """构造错误结果。"""
    return {
        "status": "error",
        "score": None,
        "verdict": "error",
        "signals": [],
        "software_info": [],
        "error_message": error_message,
    }


def _normalize_result(raw: dict[str, Any], deep: bool) -> dict[str, Any]:
    """将 AICheck 原始 JSON 输出标准化为统一格式。

    AICheck JSON 格式参考（简化）：
    {
      "score": 0.85,
      "signals": [
        {"source": "C2PA", "confidence": "high",
         "description": "...", "tool": "sora"},
        ...
      ],
      "software_info": [["Encoder", "Lavf60.16.100"]],
      "analysis_type": "check" 或 "deep"
    }
    """
    signals_raw = raw.get("signals", []) if isinstance(raw.get("signals"), list) else []
    software_raw = raw.get("software_info", []) if isinstance(raw.get("software_info"), list) else []

    # 标准化信号
    signals = []
    has_high = False
    for s in signals_raw:
        signal = {
            "source": str(s.get("source", "") or ""),
            "confidence": str(s.get("confidence", "") or ""),
            "description": str(s.get("description", "") or ""),
            "tool": s.get("tool") or None,
        }
        if signal["confidence"] == "high":
            has_high = True
        signals.append(signal)

    # 标准化 software_info
    software_info = []
    for item in software_raw:
        if isinstance(item, list) and len(item) >= 2:
            software_info.append((str(item[0]), str(item[1])))
        elif isinstance(item, dict):
            for k, v in item.items():
                software_info.append((str(k), str(v)))

    # 计算裁决
    score = raw.get("score")
    if score is not None:
        score = float(score)
        score = max(0.0, min(1.0, score))

    verdict: str | None
    if score is not None and score >= 0.5:
        verdict = "ai_generated"
    elif score is not None and score > 0.0:
        verdict = "likely_ai"
    elif has_high:
        # 即使 score 不明显，有 HIGH 信号也算 AI 生成
        verdict = "ai_generated"
        if score is None or score < 0.5:
            score = 0.8
    else:
        verdict = "no_signal"

    return {
        "status": "completed",
        "score": score,
        "verdict": verdict,
        "signals": signals,
        "software_info": software_info,
        "error_message": None,
        "deep_analysis_used": deep,
    }
