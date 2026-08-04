"""
core/gpu_lock.py
═══════════════════════════════════════════════════════════
全局 GPU 推理锁 — 串行化所有 GPU 前向，避免多模型并发驱动故障。

背景：24GB 部署机上 YOLO(cuDNN 卷积) 与 embedder(bitsandbytes 8bit matmul)
并发前向会触发 GPU 驱动硬故障（蓝屏/卡死）。裸 YOLO 或裸 embedder 单独跑都稳，
唯独并发崩 —— 所以在插件层加一把全局锁，保证任何时刻只有一个模型在 GPU 上前向。

被谁使用：
  - plugins/embedder/qwen_vl_embedder.py  的 4 个 encode_* 方法
  - plugins/detector/yolo.py              的 detect()（含模型加载/tracker 初始化/批量前向）

锁只串行 GPU 计算，不串行其余异步工作（NVDEC 解码/帧提取/DB），
因此单 NVDEC 流共享、embedder 共享等资源复用全部保留。
"""

import asyncio

# 全局 GPU 推理锁（单进程单事件循环，asyncio.Lock 模块级即可）
gpu_lock = asyncio.Lock()
