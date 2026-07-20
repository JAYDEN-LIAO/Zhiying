#!/usr/bin/env python3
"""Build Cerno PPT — single HTML slide deck from ppt-content.md"""

import json, re

# ── Load logo ──
with open('/tmp/logo_b64.txt') as f:
    LOGO_B64 = f.read().strip()

# ── Slide data ──
slides = []

def S(layout, title, content_fn):
    """Register a slide"""
    slides.append({"layout": layout, "title": title, "content": content_fn})

# ================================================================
#  SLIDE 1 — Cover
# ================================================================
S("cover", "", lambda: """
<div class="slide-content cover-layout">
  <img class="logo" src="data:image/png;base64,%s" alt="Cerno">
  <h1>Cerno — 通用视频语义分析引擎</h1>
  <p class="subtitle">完全本地部署 · 声明式 DAG 驱动 · 3 路并行语义编码</p>
  <div class="tagline-row">
    <span class="tag">🎥 自动摘要</span>
    <span class="tag">🔍 自然语言搜索</span>
    <span class="tag">🔒 数据不出域</span>
  </div>
  <p class="version">v0.8 / 2026.07</p>
</div>
""" % LOGO_B64)

# ================================================================
#  SLIDE 2 — What is Cerno
# ================================================================
S("two-col-2", "Cerno 是什么", lambda: """
<div class="slide-content two-col-layout">
  <div class="col-left">
    <p class="section-label">ABOUT</p>
    <h2>Cerno 是什么</h2>
    <p class="lead-text">一个完全本地部署的视频理解与检索系统——<br>自动摘要 + 自由搜索。</p>
    <p class="body-text">上传视频 → 自动输出结构化摘要（一句话概括 + 场景级描述 + 关键词 + 主题 + 实体）。四级摘要质量可升降——默认零成本 Python 聚合器，可按需升级到 DeepSeek V3 / R1 / 本地部署 LLM。</p>
  </div>
  <div class="col-right">
    <div class="feature-card">
      <div class="card-icon">📝</div>
      <h3>视频内容智能摘要</h3>
      <p>上传视频 → 自动输出结构化摘要。四级摘要质量可升降——默认零成本 Python 聚合器，可按需升级到 DeepSeek V3 / R1。</p>
    </div>
    <div class="feature-card">
      <div class="card-icon">🔍</div>
      <h3>视频内容自由检索</h3>
      <p>用自然语言搜索视频中的任意片段。3 路并行检索（帧级 1fps + chunk 滑动窗口 + 文本语义）互补覆盖。</p>
    </div>
  </div>
</div>
""")

# ================================================================
#  SLIDE 3 — Market Background + Competitive Quadrant
# ================================================================
S("quadrant", "市场背景 + 竞品全景", lambda: """
<div class="slide-content quadrant-layout">
  <div class="top-row">
    <div class="stat-box"><span class="stat-num">$422亿</span><span class="stat-label">AI 视频分析市场 2030</span></div>
    <div class="stat-box"><span class="stat-num">90%+</span><span class="stat-label">自托管 vs 公共 API 成本降低</span></div>
    <div class="stat-box"><span class="stat-num">87%</span><span class="stat-label">大型企业正在部署 AI</span></div>
  </div>
  <div class="main-area">
    <div class="quadrant-chart">
      <svg viewBox="0 0 520 420" style="width:100%;height:100%">
        <!-- Axes -->
        <line x1="60" y1="360" x2="480" y2="360" stroke="#d1d5db" stroke-width="1.5"/>
        <line x1="60" y1="60" x2="60" y2="360" stroke="#d1d5db" stroke-width="1.5"/>
        <!-- Axis labels -->
        <text x="260" y="395" text-anchor="middle" fill="#9ca3af" font-size="11" font-family="Inter">语义理解深度 →</text>
        <text x="30" y="210" text-anchor="middle" fill="#9ca3af" font-size="11" font-family="Inter" transform="rotate(-90,30,210)">数据隐私 / 部署可控性 →</text>
        <!-- Arrow labels -->
        <text x="480" y="355" text-anchor="end" fill="#9ca3af" font-size="10" font-family="Inter">深</text>
        <text x="60" y="355" text-anchor="start" fill="#9ca3af" font-size="10" font-family="Inter">浅</text>
        <text x="56" y="60" text-anchor="end" fill="#9ca3af" font-size="10" font-family="Inter">高</text>
        <text x="56" y="365" text-anchor="end" fill="#9ca3af" font-size="10" font-family="Inter">低</text>
        <!-- Quadrant labels (faded) -->
        <text x="140" y="120" text-anchor="middle" fill="#e5e7eb" font-size="18" font-family="Inter" font-weight="700">隐私好·语义浅</text>
        <text x="380" y="120" text-anchor="middle" fill="#e5e7eb" font-size="18" font-family="Inter" font-weight="700">隐私好·语义深</text>
        <text x="140" y="280" text-anchor="middle" fill="#e5e7eb" font-size="18" font-family="Inter" font-weight="700">隐私差·语义浅</text>
        <text x="380" y="280" text-anchor="middle" fill="#e5e7eb" font-size="18" font-family="Inter" font-weight="700">隐私差·语义深</text>
        <!-- Dots -->
        <!-- Cerno - top right (highlighted) -->
        <circle cx="390" cy="110" r="10" fill="#1a65e1" stroke="white" stroke-width="3"/>
        <text x="390" y="92" text-anchor="middle" fill="#1a65e1" font-size="11" font-weight="700" font-family="Inter">Cerno</text>
        <!-- 绝影 - top right -->
        <circle cx="340" cy="130" r="7" fill="#67c4c0" stroke="white" stroke-width="2"/>
        <text x="340" y="112" text-anchor="middle" fill="#67c4c0" font-size="10" font-weight="600" font-family="Inter">绝影</text>
        <!-- Twelve Labs - bottom right -->
        <circle cx="370" cy="280" r="7" fill="#5ca8e8" stroke="white" stroke-width="2"/>
        <text x="370" y="300" text-anchor="middle" fill="#5ca8e8" font-size="10" font-weight="600" font-family="Inter">Twelve Labs</text>
        <!-- Mixpeek - bottom right -->
        <circle cx="310" cy="260" r="7" fill="#5799e9" stroke="white" stroke-width="2"/>
        <text x="310" y="278" text-anchor="middle" fill="#5799e9" font-size="10" font-weight="600" font-family="Inter">Mixpeek</text>
        <!-- txtai - top left -->
        <circle cx="140" cy="140" r="7" fill="#4f93ed" stroke="white" stroke-width="2"/>
        <text x="140" y="122" text-anchor="middle" fill="#4f93ed" font-size="10" font-weight="600" font-family="Inter">txtai</text>
        <!-- VideoDB - center right -->
        <circle cx="280" cy="200" r="7" fill="#63b4e0" stroke="white" stroke-width="2"/>
        <text x="280" y="218" text-anchor="middle" fill="#63b4e0" font-size="10" font-weight="600" font-family="Inter">VideoDB</text>
        <!-- Cloud giants - bottom left -->
        <circle cx="120" cy="310" r="7" fill="#d1d5db" stroke="white" stroke-width="2"/>
        <text x="120" y="328" text-anchor="middle" fill="#d1d5db" font-size="10" font-weight="600" font-family="Inter">云巨头</text>
        <!-- Label: 空位标注 -->
        <rect x="335" y="68" width="120" height="22" rx="11" fill="#1a65e1" opacity="0.12"/>
        <text x="395" y="83" text-anchor="middle" fill="#1a65e1" font-size="9" font-weight="600" font-family="Inter">右上角是空的 →</text>
      </svg>
    </div>
    <div class="quadrant-note glass-card">
      <p>做语义搜索的不能本地部署，能本地部署的不做语义搜索。<br><strong>Cerno 卡的就是这个位。</strong></p>
    </div>
  </div>
</div>
""")

# ================================================================
#  SLIDE 4 — Twelve Labs
# ================================================================
S("three-card", "Twelve Labs — 行业标杆", lambda: """
<div class="slide-content three-card-layout">
  <div class="section-header">
    <p class="section-label">COMPETITIVE ANALYSIS</p>
    <h2>Twelve Labs — 行业标杆，我们的决策起点</h2>
  </div>
  <div class="cards-row">
    <div class="info-card">
      <div class="card-accent blue-accent"></div>
      <h3>🚀  Marengo + Pegasus</h3>
      <p>多模态嵌入 Marengo（512 维，专有）+ Pegasus 1.2 摘要模型。<br>仅云 API，按分钟 + 查询双重计费。</p>
    </div>
    <div class="info-card">
      <div class="card-accent blue-accent"></div>
      <h3>⚖️  优势与劣势</h3>
      <p>优势：产品成熟、嵌入效率高（512 维仅为 Cerno 2048 的 1/4）。<br>劣势：数据必须上传、不可本地部署、不可定制。</p>
    </div>
    <div class="info-card">
      <div class="card-accent blue-accent"></div>
      <h3>🎯  影响我们三个关键决策</h3>
      <p>Embedding 选型 → 开源 Qwen3-VL-Emb 而非自研<br>检索架构 → 3 路并行而非单一路径<br>摘要方案 → 四级升降而非绑定单个模型</p>
    </div>
  </div>
</div>
""")

# ================================================================
#  SLIDE 5 — 绝影V3.0
# ================================================================
S("split-image", "绝影V3.0 — 最值得关注的国内竞品", lambda: """
<div class="slide-content split-layout">
  <div class="split-left">
    <p class="section-label">COMPETITIVE ANALYSIS</p>
    <h2>绝影V3.0</h2>
    <p class="body-text" style="margin-top:8px;">北京多维视通（中科院自动化所背景），公安视频侦查装备。以自研「多维视界大模型」为底座。</p>
    <div class="engine-list">
      <div class="engine-item"><div class="engine-dot" style="background:#4f93ed"></div><strong>文搜图大模型</strong> — 共享字典 Codebook 跨模态对齐，支持模糊自然语言检索</div>
      <div class="engine-item"><div class="engine-dot" style="background:#5ca8e8"></div><strong>REID 大模型</strong> — 人体先验自监督预训练，20+ 维度特征融合，换装可识别</div>
      <div class="engine-item"><div class="engine-dot" style="background:#67c4c0"></div><strong>目标检测大模型</strong> — 与文搜图/REID 协同，大幅降低误报率</div>
    </div>
  </div>
  <div class="split-right">
    <div class="highlight-card">
      <h3>📊 关键指标</h3>
      <div class="metric-row">
        <div><span class="metric-num">60-360x</span><span class="metric-lbl">倍速处理</span></div>
        <div><span class="metric-num">29 省</span><span class="metric-lbl">公安代表队</span></div>
        <div><span class="metric-num">120h→1h</span><span class="metric-lbl">视频压缩筛查</span></div>
      </div>
    </div>
    <div class="moat-card">
      <h3>🏰 真正的护城河</h3>
      <p>不是模型——是「影系列」完整产品生态（掠影→绝影→猎影→汇影→火影）、技战法体系、多源硬件接入（GB28181/DVR/NVR）、信创适配。十余年深耕公安的生态积累。</p>
      <div class="learn-tag">Cerno 可学习：YOLO 检测集成、REID 开源方案、Codebook 技术储备</div>
    </div>
  </div>
</div>
""")

# ================================================================
#  SLIDE 6 — Other competitors + Differentiation
# ================================================================
S("two-col-3", "竞品速览 + 差异化定位", lambda: """
<div class="slide-content three-stack-layout">
  <div class="stack-row">
    <div class="mini-card">
      <h3>Mixpeek</h3>
      <div class="mini-tag">架构最接近</div>
      <p>多模态提取 pipeline + 多阶段检索。与 Cerno 3 路编码思路高度相似，但用通用图像嵌入 + 外部 API（Gemini）。</p>
    </div>
    <div class="mini-card">
      <h3>VideoDB</h3>
      <div class="mini-tag">Agent-first</div>
      <p>「视频即数据」理念，Agent 驱动交互。与 Cerno 声明式 DAG 不同设计哲学——适合实时交互 vs 可配置批量分析。</p>
    </div>
    <div class="mini-card">
      <h3>txtai</h3>
      <div class="mini-tag">通用框架</div>
      <p>Apache 2.0 开源的全能型 AI 框架。all-MiniLM-L6-v2（384 维）+ BLIP，证明通用框架套视频的局限性。</p>
    </div>
  </div>
  <div class="diff-section">
    <h3>Cerno 四个差异化锚点</h3>
    <div class="diff-grid">
      <div class="diff-item"><span class="diff-num">1</span><div><strong>全本地 + 全开源</strong><span class="diff-desc">唯一同时满足数据不出域 + 不锁定供应商的方案</span></div></div>
      <div class="diff-item"><span class="diff-num">2</span><div><strong>声明式 DAG</strong><span class="diff-desc">新增感知模块只需 Runner + Operation 注册，引擎零改动</span></div></div>
      <div class="diff-item"><span class="diff-num">3</span><div><strong>3 路并行检索 + 精度分层</strong><span class="diff-desc">帧级 1fps > 文本场景级 > chunk 窗口级，互补覆盖</span></div></div>
      <div class="diff-item"><span class="diff-num">4</span><div><strong>四级摘要升降</strong><span class="diff-desc">默认零成本 Python 聚合器，不绑定单一方案</span></div></div>
    </div>
  </div>
</div>
""")

# ================================================================
#  SLIDE 7 — VLM Selection (1): Landscape
# ================================================================
S("top-title", "VLM 选型 — 赛道扫描", lambda: """
<div class="slide-content top-title-layout">
  <p class="section-label">MODEL SELECTION</p>
  <h2>VLM — 视频理解的眼睛 (1/3)：赛道扫描</h2>
  <p class="body-text" style="max-width:90%;margin-bottom:16px;">VLM 的选型目标：在单 GPU 可部署的约束下，找到视频理解能力最强的开源模型。</p>
  <div class="model-grid">
    <div class="model-family selected">
      <div class="fam-header"><span class="fam-dot" style="background:#1a65e1"></span>Qwen-VL 系列 ← 最终选择</div>
      <p>Qwen → Qwen2-VL → Qwen2.5-VL → <strong>Qwen3-VL (Dense+MoE)</strong><br>原生视频 120fps 输入，256K 上下文，Thinking 模式。全部 Apache 2.0，中文优化最深。</p>
    </div>
    <div class="model-family">
      <div class="fam-header"><span class="fam-dot" style="background:#5ca8e8"></span>InternVL 系列</div>
      <p>上海 AI Lab，MIT 开源。26B/76B 接近 Qwen 但中文优化不足，EgoPlan-Bench 帧扩展性差。</p>
    </div>
    <div class="model-family">
      <div class="fam-header"><span class="fam-dot" style="background:#63b4e0"></span>LLaVA 系列</div>
      <p>学术开源标杆。Video-MME 57.8%（7B）vs Qwen2.5-VL 71.6%——14 个百分点的代际差距。</p>
    </div>
    <div class="model-family excluded">
      <div class="fam-header"><span class="fam-dot" style="background:#d1d5db"></span>MiniCPM-V</div>
      <p>端侧轻量，视频非核心方向。</p>
    </div>
  </div>
  <div class="note-bar">其他排除：CogVLM2（无视频分支）、VideoLLaMA3（评测不合格）、DeepSeek-VL2（视频非重点）</div>
</div>
""")

# ================================================================
#  SLIDE 8 — VLM Selection (2): Funnel
# ================================================================
S("funnel", "VLM 选型 — 筛选漏斗 (2/3)", lambda: """
<div class="slide-content funnel-layout">
  <p class="section-label">MODEL SELECTION</p>
  <h2>VLM — 30+ → 13 → 8 → 1</h2>
  <div class="funnel-svg-wrap">
    <svg viewBox="0 0 600 340" style="width:100%;height:100%">
      <!-- Funnel shape -->
      <polygon points="300,20 520,100 480,160 120,160 80,100" fill="#e8f0fc" stroke="#4f93ed" stroke-width="1.5"/>
      <text x="300" y="60" text-anchor="middle" fill="#4f93ed" font-size="11" font-weight="600" font-family="Inter">全领域 30+ VLM</text>
      <text x="300" y="75" text-anchor="middle" fill="#9ca3af" font-size="9" font-family="Inter">包括 Qwen/InternVL/LLaVA/MiniCPM 等全系列</text>
      <!-- Layer 1 -->
      <rect x="160" y="95" width="280" height="28" rx="14" fill="#1a65e1" opacity="0.15"/>
      <text x="300" y="113" text-anchor="middle" fill="#1a65e1" font-size="10" font-weight="600" font-family="Inter">第一层：硬性功能筛选 — 必须支持视频输入</text>
      <!-- Layer 2 -->
      <rect x="180" y="130" width="240" height="28" rx="14" fill="#1a65e1" opacity="0.2"/>
      <text x="300" y="148" text-anchor="middle" fill="#1a65e1" font-size="10" font-weight="600" font-family="Inter">第二层：部署可行性 — 开源 + 单 GPU</text>
      <!-- Narrowing -->
      <polygon points="300,165 420,200 380,240 220,240 180,200" fill="#d8e5ef" stroke="#5799e9" stroke-width="1.5"/>
      <text x="300" y="195" text-anchor="middle" fill="#5799e9" font-size="11" font-weight="600" font-family="Inter">短名单 13 个</text>
      <text x="300" y="210" text-anchor="middle" fill="#9ca3af" font-size="9" font-family="Inter">Qwen/InternVL/LLaVA 各尺寸入围</text>
      <!-- Layer 3 -->
      <rect x="200" y="220" width="200" height="24" rx="12" fill="#5ca8e8" opacity="0.2"/>
      <text x="300" y="236" text-anchor="middle" fill="#5ca8e8" font-size="10" font-weight="600" font-family="Inter">第三层：Benchmark 验证 — Video-MME</text>
      <!-- Final -->
      <polygon points="300,250 360,280 340,310 260,310 240,280" fill="#e6f0ed" stroke="#34d399" stroke-width="1.5"/>
      <text x="300" y="280" text-anchor="middle" fill="#34d399" font-size="12" font-weight="700" font-family="Inter">Qwen3-VL-32B</text>
      <text x="300" y="296" text-anchor="middle" fill="#9ca3af" font-size="9" font-family="Inter">Video-MME 74.5%</text>
      <!-- First round exclusion bubbles -->
      <text x="530" y="120" text-anchor="start" fill="#9ca3af" font-size="9" font-family="Inter">❌ LLaVA (57.8~63.5%)</text>
      <text x="530" y="136" text-anchor="start" fill="#9ca3af" font-size="9" font-family="Inter">❌ InternVL2-76B (多卡)</text>
      <!-- Second round -->
      <text x="530" y="210" text-anchor="start" fill="#9ca3af" font-size="9" font-family="Inter">❌ InternVL 中文不足</text>
      <text x="530" y="226" text-anchor="start" fill="#9ca3af" font-size="9" font-family="Inter">❌ Qwen2.5-VL-72B (4卡)</text>
      <text x="530" y="242" text-anchor="start" fill="#9ca3af" font-size="9" font-family="Inter">❌ Qwen3-VL-8B (74.5 vs 71.4)</text>
    </svg>
  </div>
</div>
""")

# ================================================================
#  SLIDE 9 — VLM Selection (3): Final Choice
# ================================================================
S("three-card", "VLM 选型 — 最终选择 (3/3)", lambda: """
<div class="slide-content three-card-layout">
  <div class="section-header">
    <p class="section-label">MODEL SELECTION</p>
    <h2>最终选择：Qwen3-VL-32B MoE</h2>
    <p class="body-text" style="margin-top:4px;font-size:13px;">32B 参数 · MoE 仅 3B 激活 · Video-MME 74.5% · INT4 后约 8GB 单卡推理</p>
  </div>
  <div class="cards-row">
    <div class="info-card">
      <div class="card-accent green-accent"></div>
      <h3>🎯 MoE 架构红利</h3>
      <p>32B 参数仅 3B 激活。INT4 后约 8GB 单卡推理，质量接近 72B 级别（Video-MME 74.5% vs ~77%+），显存需求少 <strong>4.5 倍</strong>。</p>
    </div>
    <div class="info-card">
      <div class="card-accent green-accent"></div>
      <h3>📹 原生视频 120fps</h3>
      <p>不是帧采样后拼接——是模型原生接受视频流，内部时序编码。帧采样丢失帧间运动信息，原生视频保留动作连贯性。</p>
    </div>
    <div class="info-card">
      <div class="card-accent green-accent"></div>
      <h3>🧠 Thinking 模式 + 长视频</h3>
      <p>Chain-of-Thought 推理——先分析再描述。20+ 分钟连续理解，长会议、监控录像不需要切分再拼合。</p>
    </div>
  </div>
</div>
""")

# ================================================================
#  SLIDE 10 — Embedding Selection (1): Landscape
# ================================================================
S("top-title", "Embedding 选型 — 赛道扫描", lambda: """
<div class="slide-content top-title-layout">
  <p class="section-label">MODEL SELECTION</p>
  <h2>Embedding — 搜索质量的基石 (1/2)</h2>
  <p class="body-text" style="max-width:90%;margin-bottom:16px;">选型目标：三模态统一（同一模型同时支持图像、文本、视频编码），共同嵌入空间，search compare 无需跨模型校准。</p>
  <div class="model-grid">
    <div class="model-family selected">
      <div class="fam-header"><span class="fam-dot" style="background:#1a65e1"></span>Qwen3-VL-Embedding ← 最终选择</div>
      <p>2B / 8B，2048 维，30+ 语言。<strong>唯一做到三模态统一 + 有视频 benchmark + 开源</strong>的模型系列。<br>MMEB-V2 总分 <strong>77.8（8B）</strong>——所有 embedding 模型中的总冠军。</p>
    </div>
    <div class="model-family">
      <div class="fam-header"><span class="fam-dot" style="background:#5ca8e8"></span>CLIP / SigLIP 家族</div>
      <p>最庞大的嵌入家族。致命短板：不支持视频编码。逐帧 mean pooling 丢失帧间时序。</p>
    </div>
    <div class="model-family">
      <div class="fam-header"><span class="fam-dot" style="background:#63b4e0"></span>InternVideo2 系列</div>
      <p>原生视频编码 MSRVTT R@1 55.9。但只支持 encode_video，不支持 image/text——需要多个模型，向量空间不可比。</p>
    </div>
    <div class="model-family excluded">
      <div class="fam-header"><span class="fam-dot" style="background:#d1d5db"></span>Jina / BGE / VLM2Vec</div>
      <p>89 语言支持强大但无视频；视频子项仅 34.6/33.6 vs Qwen 的 67.1。</p>
    </div>
  </div>
</div>
""")

# ================================================================
#  SLIDE 11 — Embedding Selection (2): Final
# ================================================================
S("two-col-2", "Embedding 选型 — 最终选择 (2/2)", lambda: """
<div class="slide-content two-col-layout">
  <div class="col-left">
    <p class="section-label">MODEL SELECTION</p>
    <h2>Qwen3-VL-Embedding-8B</h2>
    <p class="body-text" style="margin-top:8px;">MMEB-V2 总分 <strong style="color:#1a65e1;font-size:28px;">77.8</strong> — 第一</p>
    <div class="bench-compare">
      <div class="bench-row"><span class="bench-model">Qwen3-VL-Emb-8B</span><div class="bench-bar"><div style="width:95%;background:#1a65e1"></div></div><span class="bench-score">77.8</span></div>
      <div class="bench-row"><span class="bench-model">Qwen3-VL-Emb-2B</span><div class="bench-bar"><div style="width:88%;background:#4f93ed"></div></div><span class="bench-score">73.2</span></div>
      <div class="bench-row"><span class="bench-model">VLM2Vec-V2</span><div class="bench-bar"><div style="width:60%;background:#9ca3af"></div></div><span class="bench-score">~50</span></div>
      <div class="bench-row"><span class="bench-model">GME-2B</span><div class="bench-bar"><div style="width:55%;background:#d1d5db"></div></div><span class="bench-score">~46</span></div>
    </div>
  </div>
  <div class="col-right">
    <div class="feature-card">
      <h3>🏆 断层领先</h3>
      <p>视频子项 <strong>67.1</strong> vs 竞争对手 34.6/33.6——将近 2 倍的差距。<br>「搜得到」和「搜不到」的区别。</p>
    </div>
    <div class="feature-card">
      <h3>🔗 三模态统一</h3>
      <p>encode_image + encode_text + encode_video 共享一个模型实例。三条编码路径同一嵌入空间，无需跨模型校准。</p>
    </div>
    <div class="feature-card">
      <h3>📐 2048 维</h3>
      <p>vs Twelve Labs Marengo 512 维——4x 存储。当前 demo 可接受，未来可 Matryoshka 降维或向量数据库升级。</p>
    </div>
  </div>
</div>
""")

# ================================================================
#  SLIDE 12 — ASR + Segmentation
# ================================================================
S("three-card", "ASR + 场景分割选型", lambda: """
<div class="slide-content three-card-layout">
  <div class="section-header">
    <p class="section-label">MODEL SELECTION</p>
    <h2>ASR + 场景分割 — 非核心差异化模块的选型逻辑</h2>
  </div>
  <div class="three-wide">
    <div class="info-card">
      <div class="card-accent blue-accent"></div>
      <h3>🎤 ASR — 双引擎路由</h3>
      <p><strong>中文/中英混合 → SenseVoice-Small</strong><br>CER 7.81%，169.6x 倍实时，1.6GB 显存<br>2.5x 精度提升，13x 速度提升，省 70% 显存</p>
      <p style="margin-top:8px;"><strong>非中文 → faster-whisper large-v3</strong><br>99 语言覆盖，13.4x 倍实时</p>
    </div>
    <div class="info-card">
      <div class="card-accent blue-accent"></div>
      <h3>✂️ 场景分割 — TransNetV2</h3>
      <p>6 个候选人分三档：PySceneDetect（F1 0.061≈随机）、CLIP-based（F1 0.815 精度最高但 3-4 个模型）、<strong>TransNetV2（F1 0.648，30+ FPS）</strong>。</p>
      <p style="margin-top:8px;">分割服务于下游 caption/embedding，不是最终产品。「够用就行」是合理的工程判断。</p>
    </div>
    <div class="info-card">
      <div class="card-accent blue-accent"></div>
      <h3>📊 排除逻辑一览</h3>
      <p>Fun-ASR-Nano 17x 太慢（1h 视频需 3.5 分钟转录）<br>WhisperX 的 ±30ms 词级时间戳 Cerno 已有 alignment<br>CLIP 方案 F1 从 0.648→0.815 的收益不值得 3-4 模型显存</p>
    </div>
  </div>
</div>
""")

# ================================================================
#  SLIDE 13 — Summary LLM
# ================================================================
S("summary-tier", "摘要 LLM — 四级升降方案", lambda: """
<div class="slide-content tier-layout">
  <p class="section-label">MODEL SELECTION</p>
  <h2>摘要 LLM — 不绑定单一模型，构建四级质量/成本阶梯</h2>
  <div class="tier-row">
    <div class="tier-card l1">
      <div class="tier-badge">L1 默认</div>
      <h3>Python 聚合器</h3>
      <div class="tier-cost">￥0</div>
      <p>Counter 频率统计 + 去重排序。零成本、零延迟、零数据外泄。对日常/教育视频完全够用。</p>
    </div>
    <div class="tier-card l2">
      <div class="tier-badge">L2 主力</div>
      <h3>DeepSeek V3</h3>
      <div class="tier-cost">￥8 /百万输出</div>
      <p>中文摘要质量优秀，128K 上下文，开源权重可自部署。价格为 GPT-4o 的 <strong>1/9</strong>。</p>
    </div>
    <div class="tier-card l3">
      <div class="tier-badge">L3 高质</div>
      <h3>DeepSeek R1</h3>
      <div class="tier-cost">￥16 /百万输出</div>
      <p>ROUGE-L +17.6% vs 通用 LLM，R1-0528 幻觉率降低 45-50%。复杂推理场景首选。</p>
    </div>
    <div class="tier-card l4">
      <div class="tier-badge">L4 全隐私</div>
      <h3>本地 DeepSeek V3</h3>
      <div class="tier-cost">GPU 成本</div>
      <p>开源权重，完全离线。政府/军工等隐私极高场景。零数据外泄。</p>
    </div>
  </div>
</div>
""")

# ================================================================
#  SLIDE 14 — Model Selection Summary
# ================================================================
S("model-summary", "模型选型总结 — 5 模块一览", lambda: """
<div class="slide-content summary-5-layout">
  <p class="section-label">MODEL SELECTION</p>
  <h2>五模块选型总览</h2>
  <div class="summary-5-grid">
    <div class="s5-card" style="border-top:3px solid #1a65e1">
      <div class="s5-icon">👁️</div>
      <h3>VLM</h3>
      <div class="s5-model">Qwen3-VL-32B MoE</div>
      <p class="s5-reason">MoE 让 32B 仅 3B 激活，质量接近 72B 但显存省 4.5x</p>
    </div>
    <div class="s5-card" style="border-top:3px solid #4f93ed">
      <div class="s5-icon">🧩</div>
      <h3>Embedding</h3>
      <div class="s5-model">Qwen3-VL-Emb-8B</div>
      <p class="s5-reason">MMEB-V2 77.8 总分第一，没有更强的可选</p>
    </div>
    <div class="s5-card" style="border-top:3px solid #5ca8e8">
      <div class="s5-icon">🎤</div>
      <h3>ASR</h3>
      <div class="s5-model">SenseVoice + Whisper</div>
      <p class="s5-reason">双引擎：中文 2.5x 精度 + 169.6x 加速，双引擎覆盖全语种</p>
    </div>
    <div class="s5-card" style="border-top:3px solid #63b4e0">
      <div class="s5-icon">✂️</div>
      <h3>分割</h3>
      <div class="s5-model">TransNetV2</div>
      <p class="s5-reason">传统最优，满足 pipeline 需求，F1 0.648</p>
    </div>
    <div class="s5-card" style="border-top:3px solid #55c890">
      <div class="s5-icon">📝</div>
      <h3>LLM</h3>
      <div class="s5-model">四级升降方案</div>
      <p class="s5-reason">￥0 → ￥8 → ￥16 → 本地，不绑定单一方案</p>
    </div>
  </div>
  <div class="methodology-bar">
    <span>选型方法论：全量候选枚举 → 硬性排除 → 定量对比（benchmark）→ 定性论证（显存/速度/生态/语言/视频原生）</span>
  </div>
</div>
""")

# ================================================================
#  SLIDE 15 — Workflow DAG
# ================================================================
S("dag-layout", "声明式 DAG 编排", lambda: """
<div class="slide-content dag-layout">
  <div class="dag-left">
    <p class="section-label">ARCHITECTURE</p>
    <h2>声明式 DAG 编排</h2>
    <p class="body-text">每个处理能力被抽象成一个独立「操作」，声明「我需要等谁完成」。引擎自动计算哪些操作需要执行、哪些可以并行、哪些有先后依赖。</p>
    <div class="dag-benefits">
      <div class="dag-benefit"><span class="dag-check">✅</span><strong>新增能力不影响现有功能</strong> — 未来加 YOLO/REID 只需新增一个操作声明</div>
      <div class="dag-benefit"><span class="dag-check">✅</span><strong>参数联动自动校验</strong> — 关掉 Vision，Caption 和 Summary 自动关闭</div>
      <div class="dag-benefit"><span class="dag-check">✅</span><strong>能并行的自动并行</strong> — 转录和分割自动拆到两条线同时跑</div>
    </div>
    <div class="dag-inspiration glass-card" style="padding:14px 18px;margin-top:12px;">
      <p style="font-size:11px;color:#6b7280;">灵感来源：AirFlow/Dagster 的任务编排（+ Gate 驱动条件过滤） · Kubernetes 声明式配置 · 微服务插件化</p>
    </div>
  </div>
  <div class="dag-right">
    <svg viewBox="0 0 360 360" style="width:100%;height:100%">
      <!-- DAG nodes -->
      <!-- Duration -->
      <rect x="140" y="10" width="80" height="32" rx="16" fill="#34d399" stroke="white" stroke-width="2"/>
      <text x="180" y="30" text-anchor="middle" fill="white" font-size="10" font-weight="600" font-family="Inter">Duration</text>
      <!-- Row 1: Segmentation + Transcription -->
      <rect x="50" y="72" width="100" height="32" rx="16" fill="#4f93ed" stroke="white" stroke-width="2"/>
      <text x="100" y="92" text-anchor="middle" fill="white" font-size="10" font-weight="600" font-family="Inter">Segmentation</text>
      <rect x="210" y="72" width="110" height="32" rx="16" fill="#5799e9" stroke="white" stroke-width="2"/>
      <text x="265" y="92" text-anchor="middle" fill="white" font-size="10" font-weight="600" font-family="Inter">Transcription</text>
      <!-- Row 2: Keyframes + Alignment -->
      <rect x="30" y="140" width="100" height="32" rx="16" fill="#5ca8e8" stroke="white" stroke-width="2"/>
      <text x="80" y="160" text-anchor="middle" fill="white" font-size="10" font-weight="600" font-family="Inter">Keyframes</text>
      <rect x="230" y="140" width="100" height="32" rx="16" fill="#63b4e0" stroke="white" stroke-width="2"/>
      <text x="280" y="160" text-anchor="middle" fill="white" font-size="10" font-weight="600" font-family="Inter">Alignment</text>
      <!-- Row 3: Caption + Frame Encode -->
      <rect x="50" y="210" width="90" height="32" rx="16" fill="#67c4c0" stroke="white" stroke-width="2"/>
      <text x="95" y="230" text-anchor="middle" fill="white" font-size="10" font-weight="600" font-family="Inter">Caption</text>
      <rect x="220" y="210" width="110" height="32" rx="16" fill="#60c9a8" stroke="white" stroke-width="2"/>
      <text x="275" y="230" text-anchor="middle" fill="white" font-size="10" font-weight="600" font-family="Inter">Frame Encode</text>
      <!-- Row 4: Summary + Text Encode -->
      <rect x="50" y="280" width="90" height="32" rx="16" fill="#55c890" stroke="white" stroke-width="2"/>
      <text x="95" y="300" text-anchor="middle" fill="white" font-size="10" font-weight="600" font-family="Inter">Summary</text>
      <rect x="220" y="280" width="110" height="32" rx="16" fill="#34d399" stroke="white" stroke-width="2"/>
      <text x="275" y="300" text-anchor="middle" fill="white" font-size="10" font-weight="600" font-family="Inter">Text Encode</text>
      <!-- Arrows -->
      <line x1="180" y1="42" x2="100" y2="72" stroke="#d1d5db" stroke-width="1.5" marker-end="url(#arrow)"/>
      <line x1="180" y1="42" x2="265" y2="72" stroke="#d1d5db" stroke-width="1.5" marker-end="url(#arrow)"/>
      <line x1="100" y1="104" x2="80" y2="140" stroke="#d1d5db" stroke-width="1.5" marker-end="url(#arrow)"/>
      <line x1="265" y1="104" x2="280" y2="140" stroke="#d1d5db" stroke-width="1.5" marker-end="url(#arrow)"/>
      <line x1="80" y1="172" x2="95" y2="210" stroke="#d1d5db" stroke-width="1.5" marker-end="url(#arrow)"/>
      <line x1="280" y1="172" x2="275" y2="210" stroke="#d1d5db" stroke-width="1.5" marker-end="url(#arrow)"/>
      <line x1="95" y1="242" x2="95" y2="280" stroke="#d1d5db" stroke-width="1.5" marker-end="url(#arrow)"/>
      <line x1="275" y1="242" x2="275" y2="280" stroke="#d1d5db" stroke-width="1.5" marker-end="url(#arrow)"/>
      <!-- Gate icon -->
      <circle cx="320" cy="320" r="16" fill="#1a65e1" opacity="0.15"/>
      <text x="320" y="325" text-anchor="middle" fill="#1a65e1" font-size="10" font-weight="700" font-family="Inter">Gate</text>
      <defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10" fill="none" stroke="#d1d5db" stroke-width="1.5"/></marker></defs>
    </svg>
  </div>
</div>
""")

# ================================================================
#  SLIDE 16 — Summary 3 Routes
# ================================================================
S("two-col-2", "视频摘要 — 三大技术路线", lambda: """
<div class="slide-content two-col-layout">
  <div class="col-left">
    <p class="section-label">SOLUTION COMPARISON</p>
    <h2>视频摘要三大路线</h2>
    <div class="route-list">
      <div class="route-item"><span class="route-badge" style="background:#4f93ed">端到端</span><span>原始视频 → 巨型多模态模型 → 摘要文本</span></div>
      <div class="route-item"><span class="route-badge" style="background:#1a65e1">Pipeline</span><span>原始视频 → 分割 → VLM Caption → LLM/聚合器拼合 → 摘要</span></div>
      <div class="route-item"><span class="route-badge" style="background:#67c4c0">混合</span><span>粗粒度 API + 细粒度本地方案 → 融合输出</span></div>
    </div>
    <div class="evidence-card glass-card" style="margin-top:16px;">
      <p style="font-size:12px;color:#1a65e1;font-weight:600;">📖 关键学术证据：Pipeline 在长视频上已反超端到端</p>
      <p style="font-size:11px;color:#6b7280;margin-top:4px;">Video-RAG（NeurIPS 2025）证明：配合 72B 级别模型的 Pipeline 方案在长视频摘要上可超越 Gemini-1.5-Pro 和 GPT-4o。</p>
    </div>
    <p class="body-text" style="font-size:12px;margin-top:12px;"><strong>Cerno 选择：Pipeline</strong> — 学术证据 + 本地部署硬约束 + 零成本聚合器 + 结构化输出</p>
  </div>
  <div class="col-right" style="gap:12px;">
    <div class="info-card">
      <h3>🚀 Gemini 2.5 Pro</h3>
      <p>Video-MME 84.8% SOTA。3h 上下文。仅云 API，数据出境，闭源。token 成本不可控。</p>
    </div>
    <div class="info-card">
      <h3>🏢 NVIDIA LVS</h3>
      <p>层级式摘要标杆。30-60s 固定窗口 + VLM 描述 + CA-RAG 聚合。管道式无限扩展，但无统一产品形态。</p>
    </div>
    <div class="info-card">
      <h3>🔒 Cerno</h3>
      <p>双模式 Pipeline：逐场景 Caption（结构化 JSON）→ Python 聚合器（零成本），可选升级到 DeepSeek V3/R1。</p>
    </div>
  </div>
</div>
""")

# ================================================================
#  SLIDE 17 — Search 4 Paradigms
# ================================================================
S("top-title", "视频搜索 — 四种检索范式", lambda: """
<div class="slide-content top-title-layout">
  <p class="section-label">SOLUTION COMPARISON</p>
  <h2>四种检索范式横向对比</h2>
  <div class="paradigm-grid">
    <div class="paradigm-card">
      <div class="para-header" style="background:#4f93ed">统一嵌入 + 单路检索</div>
      <div class="para-body">
        <p class="para-example">Twelve Labs Marengo 512 维</p>
        <p>最简洁的方案。单路径无法区分精度层级——用户不能控制帧级还是场景级。</p>
      </div>
    </div>
    <div class="paradigm-card">
      <div class="para-header" style="background:#5ca8e8">Codebook 跨模态对齐</div>
      <div class="para-body">
        <p class="para-example">绝影V3.0 文搜图</p>
        <p>双侧塔架构，共享字典离散空间对齐。公安封闭目标集可针对性优化，但模型不可替换。</p>
      </div>
    </div>
    <div class="paradigm-card">
      <div class="para-header" style="background:#63b4e0">多模型拼接 + RRF 融合</div>
      <div class="para-body">
        <p class="para-example">Mixpeek</p>
        <p>CLIP + Gemini + Whisper 各自检索后用 RRF 合并。灵活但向量空间不可比，融合有损。</p>
      </div>
    </div>
    <div class="paradigm-card highlighted">
      <div class="para-header" style="background:#1a65e1">统一嵌入 + 3 路并行</div>
      <div class="para-body">
        <p class="para-example">Cerno</p>
        <p>Qwen3-VL-Emb 单模型覆盖三路。帧路×1.0 / 文本路×0.85 / chunk 路×0.7，智能合并。</p>
      </div>
    </div>
  </div>
  <div class="note-bar" style="margin-top:12px;">四种范式的本质差异：「在哪里做跨模态对齐」——模型内 / Codebook / 融合阶段 / 根本不专门做</div>
</div>
""")

# ================================================================
#  SLIDE 18 — Cerno 3-path Search
# ================================================================
S("search-flow", "Cerno 3 路并行检索", lambda: """
<div class="slide-content search-flow-layout">
  <div class="section-header">
    <p class="section-label">SOLUTION COMPARISON</p>
    <h2>Cerno 的 3 路并行 + 统一嵌入</h2>
  </div>
  <div class="search-body">
    <div class="search-query glass-card">
      <span>🔍</span> 用户查询 → <strong>Qwen3-VL-Emb-8B</strong> encode_text() → 2048-dim 向量
    </div>
    <div class="search-paths">
      <div class="path-card path-frame">
        <div class="path-head">路 1 · 帧级检索</div>
        <div class="path-detail">frame_embeddings 表 · cosine ×1.0</div>
        <div class="path-precision">precision: <span>frame</span></div>
        <p>1fps 秒级定位，最高精度</p>
      </div>
      <div class="path-card path-chunk">
        <div class="path-head">路 2 · Chunk 检索</div>
        <div class="path-detail">chunks 表 · cosine ×0.7</div>
        <div class="path-precision">precision: <span>chunk</span></div>
        <p>原生视频编码，保留时序动态</p>
      </div>
      <div class="path-card path-text">
        <div class="path-head">路 3 · 文本检索</div>
        <div class="path-detail">scenes.text_embedding · cosine ×0.85</div>
        <div class="path-precision">precision: <span>text</span></div>
        <p>caption + OCR + transcript 语义</p>
      </div>
      <div class="path-card path-label" style="opacity:0.5">
        <div class="path-head">路 4 · Label 检索 (预留)</div>
        <div class="path-detail">scenes.entities JSONB</div>
        <div class="path-precision">precision: <span>label</span></div>
        <p>YOLO 激活后启用</p>
      </div>
    </div>
    <div class="search-merge glass-card">
      <strong>按 Scene 合并去重</strong> · 帧簇优先（≤4s 聚类），非重叠保留，路径感知排序
    </div>
  </div>
</div>
""")

# ================================================================
#  SLIDE 19 — Index + Parameter System
# ================================================================
S("param-system", "三级索引 + 四级参数", lambda: """
<div class="slide-content param-layout">
  <div class="param-top">
    <p class="section-label">ARCHITECTURE</p>
    <h2>三级索引体系 + 4 级参数系统</h2>
  </div>
  <div class="param-body">
    <div class="index-section">
      <div class="index-card idx-frame"><div class="idx-num">1</div><h3>画面索引</h3><p>帧级 1fps，最高精度。搜「穿黑衣服的人」——精确到秒。</p></div>
      <div class="index-card idx-text"><div class="idx-num">2</div><h3>内容索引</h3><p>文本级语义最深。搜「讨论预算的会议」——理解上下文。</p></div>
      <div class="index-card idx-chunk"><div class="idx-num">3</div><h3>过程索引</h3><p>chunk 级保留动态。搜「有人站起来」——捕捉连续动作。</p></div>
    </div>
    <div class="param-pyramid">
      <svg viewBox="0 0 500 260" style="width:100%">
        <!-- L1 -->
        <polygon points="250,10 460,50 40,50" fill="rgba(26,101,225,0.12)" stroke="#1a65e1" stroke-width="2"/>
        <text x="250" y="35" text-anchor="middle" fill="#1a65e1" font-size="14" font-weight="700" font-family="Inter">L1 场景类型</text>
        <text x="250" y="48" text-anchor="middle" fill="#6b7280" font-size="9" font-family="Inter">「会议」「监控」「课程」— 自动填充三层默认值</text>
        <!-- L2 -->
        <polygon points="250,60 420,100 80,100" fill="rgba(26,101,225,0.08)" stroke="#4f93ed" stroke-width="1.5"/>
        <text x="250" y="85" text-anchor="middle" fill="#4f93ed" font-size="13" font-weight="600" font-family="Inter">L2 感知模块</text>
        <text x="250" y="98" text-anchor="middle" fill="#6b7280" font-size="9" font-family="Inter">Vision / Audio / OCR / Caption — 按需勾选</text>
        <!-- L3 -->
        <polygon points="250,108 380,148 120,148" fill="rgba(79,147,237,0.08)" stroke="#5ca8e8" stroke-width="1.5"/>
        <text x="250" y="133" text-anchor="middle" fill="#5ca8e8" font-size="12" font-weight="600" font-family="Inter">L3 功能路径</text>
        <text x="250" y="146" text-anchor="middle" fill="#6b7280" font-size="9" font-family="Inter">摘要 / 搜索索引 — 质量 vs 成本权衡</text>
        <!-- L4 -->
        <polygon points="250,156 340,196 160,196" fill="rgba(92,168,232,0.08)" stroke="#63b4e0" stroke-width="1"/>
        <text x="250" y="181" text-anchor="middle" fill="#63b4e0" font-size="11" font-weight="600" font-family="Inter">L4 高级参数</text>
        <text x="250" y="194" text-anchor="middle" fill="#6b7280" font-size="9" font-family="Inter">语言 / 采样帧率 / 阈值 / 摘要详情 — 专家模式</text>
      </svg>
    </div>
  </div>
</div>
""")

# ================================================================
#  SLIDE 20 — Tech Stack + Status
# ================================================================
S("tech-stack", "技术栈 + 当前状态", lambda: """
<div class="slide-content tech-layout">
  <div class="section-header">
    <p class="section-label">PROJECT STATUS</p>
    <h2>技术栈 & 当前状态</h2>
  </div>
  <div class="tech-body">
    <div class="tech-grid">
      <div class="tech-item"><span class="tech-cat">后端</span><span>FastAPI (Python 3.12) + SQLAlchemy async</span></div>
      <div class="tech-item"><span class="tech-cat">数据库</span><span>PostgreSQL 17 + pgvector 0.8</span></div>
      <div class="tech-item"><span class="tech-cat">VLM</span><span>Qwen3-VL-32B MoE · 3B 激活 · Video-MME 74.5%</span></div>
      <div class="tech-item"><span class="tech-cat">Embedding</span><span>Qwen3-VL-Emb-8B · 2048 维 · MMEB-V2 77.8</span></div>
      <div class="tech-item"><span class="tech-cat">ASR</span><span>SenseVoice-Small + faster-whisper 双引擎</span></div>
      <div class="tech-item"><span class="tech-cat">前端</span><span>React 19 + Vite 6 + Tailwind CSS 4</span></div>
    </div>
    <div class="status-cols">
      <div class="status-col">
        <h3>✅ 已完成 (v0.8)</h3>
        <ul>
          <li>Pipeline DAG 引擎（10 操作）</li>
          <li>3 路编码：frame / chunk / text</li>
          <li>3 路并行语义搜索</li>
          <li>双模式摘要 + Caption</li>
          <li>4 级参数系统</li>
          <li>TransNetV2 分割</li>
          <li>React 前端 Dashboard（8 子组件）</li>
          <li>增量处理 + 14 API Endpoint</li>
        </ul>
      </div>
      <div class="status-col">
        <h3>🔄 路线图</h3>
        <div class="road-item"><span class="road-prio p0">P0</span>1-3 月：ASR/VLM/Emb 升级，YOLO 集成，benchmark</div>
        <div class="road-item"><span class="road-prio p1">P1</span>3-6 月：OCR/REID 调研，频次分析，向量库升级</div>
        <div class="road-item"><span class="road-prio p2">P2</span>6-12 月：Agentic 分析，分布式 Pipeline，信创评估</div>
      </div>
    </div>
  </div>
</div>
""")

# ================================================================
#  SLIDE 21 — 绝影 vs Cerno
# ================================================================
S("vs-layout", "绝影V3.0 vs Cerno — 直面差距", lambda: """
<div class="slide-content vs-layout">
  <p class="section-label">COMPETITIVE ANALYSIS</p>
  <h2>绝影V3.0 vs Cerno — 差异分析</h2>
  <div class="vs-body">
    <div class="vs-col vs-red">
      <h3>绝影 领先</h3>
      <ul>
        <li><strong>REID 跨镜追踪</strong> — 换装可识别，复杂场景 +40%</li>
        <li><strong>目标检测</strong> — 自研三联协同检测引擎</li>
        <li><strong>技战法体系</strong> — 频次/同行人/M:N/轨迹分析</li>
        <li><strong>多源硬件接入</strong> — GB28181/DVR/NVR/硬盘直读</li>
        <li><strong>信创适配</strong> — 国产芯片+OS</li>
        <li><strong>十余年实战积累</strong> — 29 省反馈闭环</li>
        <li><strong>完整产品生态</strong> — 掠影→绝影→猎影→汇影→火影</li>
      </ul>
    </div>
    <div class="vs-col vs-blue">
      <h3>Cerno 占优</h3>
      <ul>
        <li><strong>声明式 DAG</strong> — 新增模块引擎零改动</li>
        <li><strong>3 路并行 + 精度分层</strong> — 三级互补覆盖</li>
        <li><strong>4 级参数系统</strong> — 场景→模块→功能→高级级联</li>
        <li><strong>四级摘要升降</strong> — 默认零成本</li>
        <li><strong>全开源 + 模型可替换</strong> — 零供应商锁定</li>
        <li><strong>方案链学术证据</strong> — MMEB-V2 77.8，Video-RAG</li>
        <li><strong>通用场景</strong> — 会议/教育/媒体/监控</li>
      </ul>
    </div>
    <div class="vs-col vs-mid">
      <h3>对等 & 追赶</h3>
      <p class="vs-mid-title">双方对等：</p>
      <p>以文搜视频、全本地部署、零 API 成本</p>
      <p class="vs-mid-title" style="margin-top:12px;">6-12 月可追赶：</p>
      <p>YOLO 检测 → label 搜索 · REID 开源集成 → 跨镜基础能力 · 频次/同行人初版 · RTSP 接入</p>
    </div>
  </div>
</div>
""")

# ================================================================
#  SLIDE 22 — Short Term Actions
# ================================================================
S("two-col-2", "近期升级 — 现在到 3 个月", lambda: """
<div class="slide-content two-col-layout">
  <div class="col-left">
    <p class="section-label">ROADMAP</p>
    <h2>包装 + 能力补齐</h2>
    <p class="body-text" style="margin-bottom:12px;">把 Cerno 从一个能跑的系统变成一个能拿得出手的产品。</p>
    <div class="feature-card" style="margin-bottom:10px">
      <h3>📺 播放器集成</h3>
      <p>搜索结果点击直接跳转对应时间点 + 匹配帧缩略图。对标 Twelve Labs 产品体验。</p>
    </div>
    <div class="feature-card">
      <h3>🎬 Demo 展示层</h3>
      <p>整理四类场景 demo 视频库 + 在线试用环境 + 快速开始指南。</p>
    </div>
  </div>
  <div class="col-right">
    <h3 style="font-size:18px;font-weight:700;color:#111827;margin-bottom:12px;">⚡ 短期能力补齐</h3>
    <div class="compact-list">
      <div class="compact-item"><span class="compact-check green">✓</span><strong>以图搜图</strong> — 已有 encode_image，同一模型不费力</div>
      <div class="compact-item"><span class="compact-check blue">✓</span><strong>YOLO + label 搜索</strong> — 3-5 天可集成，JSONB 精确查询零假阳性</div>
      <div class="compact-item"><span class="compact-check blue">✓</span><strong>rerank 重排序</strong> — cross-encoder 精排 top-K，粗排→精排两阶段</div>
      <div class="compact-item"><span class="compact-check green">✓</span><strong>chunk 正式启用</strong> — 静止帧跳过，帧差阈值判定</div>
      <div class="compact-item"><span class="compact-check blue">✓</span><strong>维数截断</strong> — 2048→1024 评估，为 HNSW 腾空间</div>
      <div class="compact-item"><span class="compact-check green">✓</span><strong>模型升级</strong> — SenseVoice(1-2d) / 32B MoE(3-5d) / Emb-8B(1-2d)</div>
    </div>
  </div>
</div>
""")

# ================================================================
#  SLIDE 23 — Mid-Long Term
# ================================================================
S("three-card", "中长期升级 — 3-12 个月", lambda: """
<div class="slide-content three-card-layout">
  <div class="section-header">
    <p class="section-label">ROADMAP</p>
    <h2>中长期升级与深挖</h2>
  </div>
  <div class="cards-row">
    <div class="info-card">
      <div class="card-accent blue-accent"></div>
      <h3>🏗️ 生产级改造</h3>
      <p><strong>容错队列</strong> — Celery/ARQ 持久化，失败重试，断点续跑</p>
      <p><strong>数据库升级</strong> — pgvector → LanceDB/Qdrant 评估</p>
      <p><strong>模型持续跟踪</strong> — 建立定期评估节奏，Qwen/DeepSeek 升级</p>
    </div>
    <div class="info-card">
      <div class="card-accent green-accent"></div>
      <h3>🔬 深挖方向</h3>
      <p><strong>Highlights / 异常检测</strong> — VLM 直接判断「有什么不寻常事件」</p>
      <p><strong>REID 跨镜追踪</strong> — OSNet/CLIP-ReID 开源起步</p>
      <p><strong>动态聚档</strong> — 基于时序聚类生成目标时间线</p>
      <p><strong>多源接入</strong> — RTSP 实时流 → GB28181</p>
    </div>
    <div class="info-card">
      <div class="card-accent" style="background:linear-gradient(135deg,#1a65e1,#34d399)"></div>
      <h3>🎯 对标参考</h3>
      <p>绝影的 60-360x 倍速不仅是模型快，更是工程调度成熟——容错队列是前提。</p>
      <p>Highlights 走 VLM 路线绕开传统 CV 规则，差异化切入。</p>
      <p>REID 是最难的但对标绝影必须迈过的坎。</p>
    </div>
  </div>
</div>
""")

# ================================================================
#  SLIDE 24 — Summary / Closing
# ================================================================
S("summary-close", "总结", lambda: """
<div class="slide-content summary-close-layout">
  <div class="blob-blue" style="top:-10%;right:-5%;width:50%;height:100%"></div>
  <div class="blob-green" style="bottom:-10%;right:-5%;width:45%;height:60%"></div>
  <div class="blob-left" style="top:5%;left:-2%;width:25%;height:90%"></div>
  <div class="close-content">
    <h2>Cerno</h2>
    <p class="close-tagline">完全本地部署的、声明式 DAG 驱动的、3 路并行语义编码的视频理解与检索系统。</p>
    <div class="close-counters">
      <div class="close-stat"><span class="close-num">10</span><span class="close-label">操作 × DAG<br>新增模块引擎零改动</span></div>
      <div class="close-stat"><span class="close-num">3</span><span class="close-label">路并行检索<br>帧级 + chunk + 文本互补</span></div>
      <div class="close-stat"><span class="close-num">5</span><span class="close-label">模块全量选型<br>枚举→排除→benchmark 定量</span></div>
      <div class="close-stat"><span class="close-num">77.8</span><span class="close-label">MMEB-V2 第一<br>公开 benchmark 可验证</span></div>
    </div>
    <p class="close-footer">
      融合 Twelve Labs 的语义搜索产品思路、AirFlow 的 DAG 编排理念、RAG 的多路召回范式、绝影V3.0 的产品化深度参考，在<strong>「全本地 + 全开源 + 深度语义搜索」</strong>这一交叉点上，目前没有对手站在同一个位置。
    </p>
  </div>
</div>
""")

# ================================================================
#  BUILD HTML
# ================================================================

# Start building
html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cerno · 视频语义分析引擎</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

*, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }

body {
  font-family: 'Inter', -apple-system, sans-serif;
  background: #1a1d23;
  overflow: hidden;
  width: 100vw;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  user-select: none;
}

/* ── Slide Container ── */
#presentation {
  position: relative;
  width: min(1024px, 95vw);
  aspect-ratio: 16 / 9;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 25px 80px -12px rgba(0,0,0,0.5);
}

.slide {
  position: absolute;
  inset: 0;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.4s ease;
  background: linear-gradient(135deg, #e4eaf4 0%, #d8e5ef 20%, #e6f0ed 50%, #f4f5f7 100%);
  display: flex;
  flex-direction: column;
}
.slide.active {
  opacity: 1;
  pointer-events: auto;
  z-index: 2;
}

/* ── Fluid Blobs (shared) ── */
.blob-blue {
  position: absolute; z-index: 0; pointer-events: none;
  background: radial-gradient(circle at 40% 45%, rgba(135,178,245,0.35) 0%, rgba(135,178,245,0) 60%);
  filter: blur(70px);
}
.blob-green {
  position: absolute; z-index: 0; pointer-events: none;
  background: radial-gradient(circle at 50% 40%, rgba(144,212,194,0.45) 0%, rgba(144,212,194,0) 55%);
  filter: blur(50px);
}
.blob-left {
  position: absolute; z-index: 0; pointer-events: none;
  background: radial-gradient(circle at 30% 50%, rgba(26,101,225,0.20) 0%, rgba(26,101,225,0) 60%);
  filter: blur(80px);
}
.blob-right {
  position: absolute; z-index: 0; pointer-events: none;
  background: radial-gradient(circle at 50% 40%, rgba(52,211,153,0.25) 0%, rgba(52,211,153,0) 55%);
  filter: blur(60px);
}

/* ── Shared Text Styles ── */
.section-label {
  font-size: 11px; font-weight: 600; color: #1a65e1;
  text-transform: uppercase; letter-spacing: 0.08em;
  margin-bottom: 8px;
}
h2 {
  font-size: clamp(22px, 3vw, 32px); font-weight: 700; color: #111827;
  line-height: 1.2; margin-bottom: 12px;
}
.body-text { font-size: clamp(12px, 1.3vw, 14px); color: #4b5563; line-height: 1.6; }
.glass-card {
  background: linear-gradient(135deg, rgba(255,255,255,0.7) 0%, rgba(255,255,255,0.5) 100%);
  backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255,255,255,0.6);
  border-radius: 14px;
  padding: 18px 22px;
  box-shadow: 0 4px 24px -6px rgba(0,0,0,0.04);
}
.card-accent {
  height: 3px; border-radius: 3px 3px 0 0; margin: -1px -1px 12px -1px;
}
.blue-accent { background: #1a65e1; }
.green-accent { background: #34d399; }

/* ── Navigation ── */
#nav {
  position: fixed;
  bottom: 30px; left: 50%; transform: translateX(-50%);
  display: flex; align-items: center; gap: 16px;
  z-index: 100;
  background: rgba(26,29,35,0.8);
  backdrop-filter: blur(12px);
  padding: 10px 20px;
  border-radius: 30px;
  border: 1px solid rgba(255,255,255,0.1);
}
#nav button {
  width: 36px; height: 36px; border-radius: 50%;
  border: 1px solid rgba(255,255,255,0.2);
  background: transparent; color: white;
  cursor: pointer; font-size: 16px;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.2s;
}
#nav button:hover { background: rgba(255,255,255,0.1); border-color: rgba(255,255,255,0.4); }
#nav button:disabled { opacity: 0.3; cursor: default; }
#page-indicator {
  color: rgba(255,255,255,0.7);
  font-size: 13px; font-weight: 500;
  min-width: 60px; text-align: center;
  font-variant-numeric: tabular-nums;
}
#page-progress {
  width: 120px; height: 3px;
  background: rgba(255,255,255,0.15);
  border-radius: 3px; overflow: hidden;
}
#page-progress-bar {
  height: 100%; background: #1a65e1;
  transition: width 0.3s ease;
  border-radius: 3px;
}

/* ── SLIDE CONTENT ── */
.slide-content {
  position: relative; z-index: 1;
  padding: clamp(24px, 4vw, 48px) clamp(28px, 4.5vw, 56px);
  height: 100%;
  display: flex; flex-direction: column;
}

/* Cover */
.cover-layout { align-items: center; justify-content: center; text-align: center; }
.cover-layout .logo { height: clamp(36px, 5vw, 56px); margin-bottom: clamp(16px, 2.5vw, 28px); }
.cover-layout h1 {
  font-size: clamp(28px, 4.5vw, 52px); font-weight: 800;
  color: #1a65e1; letter-spacing: -0.02em; line-height: 1.1;
  margin-bottom: 12px;
}
.cover-layout .subtitle {
  font-size: clamp(13px, 1.6vw, 20px); font-weight: 400;
  color: #6b7280; letter-spacing: 0.02em;
}
.cover-layout .tagline-row { display: flex; gap: clamp(8px, 1.5vw, 16px); justify-content: center; margin-top: clamp(20px, 3vw, 32px); flex-wrap: wrap; }
.cover-layout .tag {
  font-size: clamp(11px, 1.1vw, 13px); font-weight: 500;
  color: #6b7280;
  padding: 6px 16px;
  background: linear-gradient(135deg, rgba(255,255,255,0.7), rgba(255,255,255,0.5));
  backdrop-filter: blur(20px);
  border-radius: 20px;
  border: 1px solid rgba(255,255,255,0.6);
}
.cover-layout .version { margin-top: clamp(28px, 4vw, 48px); font-size: clamp(11px, 1vw, 13px); color: #9ca3af; }

/* Two Column */
.two-col-layout { flex-direction: row !important; gap: clamp(16px, 2.5vw, 32px); }
.two-col-layout .col-left { flex: 1; display: flex; flex-direction: column; justify-content: center; }
.two-col-layout .col-right { flex: 1; display: flex; flex-direction: column; gap: 12px; justify-content: center; }
.lead-text { font-size: clamp(14px, 1.6vw, 18px); font-weight: 500; color: #111827; line-height: 1.4; margin-bottom: 12px; }

.feature-card {
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  border-radius: 14px; padding: 18px 20px;
  box-shadow: 0 2px 8px -2px rgba(0,0,0,0.10), 0 8px 24px -6px rgba(0,0,0,0.12), 0 16px 48px -12px rgba(0,0,0,0.08);
}
.feature-card .card-icon { font-size: 24px; margin-bottom: 6px; }
.feature-card h3 { font-size: clamp(13px, 1.2vw, 15px); font-weight: 700; color: #1a65e1; margin-bottom: 6px; }
.feature-card p { font-size: clamp(11px, 1vw, 13px); color: #4b5563; line-height: 1.5; }

/* Three Card Layout */
.three-card-layout .section-header { margin-bottom: clamp(8px, 1.2vw, 14px); }
.cards-row { display: flex; gap: clamp(10px, 1.5vw, 18px); flex:1; }
.info-card {
  flex: 1;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  border-radius: 14px; padding: 18px 18px;
  box-shadow: 0 2px 8px -2px rgba(0,0,0,0.10), 0 8px 24px -6px rgba(0,0,0,0.12);
  display: flex; flex-direction: column;
}
.info-card h3 { font-size: clamp(12px, 1.2vw, 15px); font-weight: 700; color: #111827; margin-bottom: 8px; }
.info-card p { font-size: clamp(10px, 0.95vw, 12px); color: #4b5563; line-height: 1.5; }
.three-wide { display: flex; gap: clamp(10px, 1.5vw, 18px); flex:1; }

/* Quadrant Layout */
.quadrant-layout .top-row { display: flex; gap: 14px; margin-bottom: 12px; }
.stat-box { flex:1; text-align:center; background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%); border-radius: 12px; padding: 14px 8px; box-shadow: 0 2px 6px -2px rgba(0,0,0,0.08); }
.stat-num { display:block; font-size:clamp(18px,2vw,26px); font-weight:800; color:#1a65e1; line-height:1.1; }
.stat-label { display:block; font-size:clamp(9px,0.9vw,11px); color:#6b7280; margin-top:4px; }
.main-area { flex:1; display:flex; gap:14px; min-height:0; }
.quadrant-chart { flex:1; min-height:0; }
.quadrant-note { width:200px; flex-shrink:0; display:flex; align-items:center; }
.quadrant-note p { font-size:12px; color:#374151; line-height:1.5; }

/* Three Stack (competitors) */
.three-stack-layout .stack-row { display:flex; gap:clamp(10px,1.5vw,18px); margin-bottom:16px; }
.mini-card { flex:1; background:linear-gradient(180deg,#ffffff 0%,#f8fafc 100%); border-radius:12px; padding:14px 16px; box-shadow:0 2px 6px -2px rgba(0,0,0,0.08); }
.mini-card h3 { font-size:14px; font-weight:700; color:#111827; margin-bottom:4px; }
.mini-tag { display:inline-block; font-size:9px; font-weight:600; color:#1a65e1; background:rgba(26,101,225,0.1); padding:2px 8px; border-radius:6px; margin-bottom:6px; }
.mini-card p { font-size:11px; color:#4b5563; line-height:1.5; }
.diff-section h3 { font-size:16px; font-weight:700; color:#111827; margin-bottom:10px; }
.diff-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.diff-item { display:flex; align-items:flex-start; gap:10px; }
.diff-num { width:22px; height:22px; border-radius:50%; background:#1a65e1; color:white; font-size:11px; font-weight:700; display:flex; align-items:center; justify-content:center; flex-shrink:0; }
.diff-item strong { display:block; font-size:12px; color:#111827; }
.diff-desc { display:block; font-size:10px; color:#6b7280; margin-top:2px; }

/* Split Layout */
.split-layout { flex-direction:row !important; gap:clamp(16px,2.5vw,32px); }
.split-left { flex:1; display:flex; flex-direction:column; }
.split-right { flex:1; display:flex; flex-direction:column; gap:12px; }
.engine-list { display:flex; flex-direction:column; gap:10px; margin-top:12px; }
.engine-item { display:flex; align-items:flex-start; gap:8px; font-size:11px; color:#4b5563; line-height:1.5; }
.engine-dot { width:8px; height:8px; border-radius:50%; flex-shrink:0; margin-top:4px; }
.highlight-card { background:linear-gradient(180deg,#ffffff 0%,#f8fafc 100%); border-radius:12px; padding:14px 16px; box-shadow:0 2px 6px -2px rgba(0,0,0,0.08); }
.highlight-card h3 { font-size:13px; font-weight:700; color:#111827; margin-bottom:8px; }
.metric-row { display:flex; gap:12px; }
.metric-row > div { text-align:center; flex:1; }
.metric-num { display:block; font-size:18px; font-weight:800; color:#1a65e1; }
.metric-lbl { display:block; font-size:9px; color:#6b7280; margin-top:2px; }
.moat-card { background:linear-gradient(180deg,#ffffff 0%,#f8fafc 100%); border-radius:12px; padding:14px 16px; box-shadow:0 2px 6px -2px rgba(0,0,0,0.08); }
.moat-card h3 { font-size:13px; font-weight:700; color:#111827; margin-bottom:6px; }
.moat-card p { font-size:11px; color:#4b5563; line-height:1.5; }
.learn-tag { display:inline-block; font-size:10px; color:#1a65e1; background:rgba(26,101,225,0.08); padding:4px 10px; border-radius:8px; margin-top:8px; }

/* Top Title Layout */
.top-title-layout .model-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.model-family { background:linear-gradient(180deg,#ffffff 0%,#f8fafc 100%); border-radius:10px; padding:12px 14px; box-shadow:0 1px 4px -1px rgba(0,0,0,0.06); }
.fam-header { font-size:12px; font-weight:700; color:#111827; margin-bottom:4px; display:flex; align-items:center; gap:6px; }
.fam-dot { width:8px; height:8px; border-radius:50%; display:inline-block; flex-shrink:0; }
.model-family p { font-size:11px; color:#4b5563; line-height:1.5; }
.model-family.selected { border-left:3px solid #1a65e1; }
.model-family.excluded { opacity:0.5; }
.note-bar { background:rgba(255,255,255,0.6); border-radius:8px; padding:8px 14px; font-size:11px; color:#6b7280; margin-top:8px; }

/* Funnel */
.funnel-layout .funnel-svg-wrap { flex:1; min-height:0; display:flex; }

/* Tier Layout */
.tier-layout .tier-row { display:flex; gap:12px; flex:1; align-items:stretch; }
.tier-card { flex:1; background:linear-gradient(180deg,#ffffff 0%,#f8fafc 100%); border-radius:14px; padding:16px; box-shadow:0 2px 8px -2px rgba(0,0,0,0.10); display:flex; flex-direction:column; position:relative; overflow:hidden; }
.tier-badge { display:inline-block; font-size:9px; font-weight:600; padding:3px 10px; border-radius:10px; margin-bottom:8px; align-self:flex-start; }
.l1 .tier-badge { background:rgba(52,211,153,0.15); color:#34d399; }
.l2 .tier-badge { background:rgba(26,101,225,0.12); color:#1a65e1; }
.l3 .tier-badge { background:rgba(79,147,237,0.12); color:#4f93ed; }
.l4 .tier-badge { background:rgba(103,196,192,0.12); color:#67c4c0; }
.tier-card h3 { font-size:15px; font-weight:700; color:#111827; }
.tier-cost { font-size:28px; font-weight:800; color:#1a65e1; margin:4px 0 8px; }
.tier-card p { font-size:11px; color:#4b5563; line-height:1.5; flex:1; }

/* Model Summary 5 */
.summary-5-layout .summary-5-grid { display:flex; gap:12px; flex:1; align-items:stretch; }
.s5-card { flex:1; background:linear-gradient(180deg,#ffffff 0%,#f8fafc 100%); border-radius:12px; padding:14px 12px; box-shadow:0 2px 6px -2px rgba(0,0,0,0.08); text-align:center; display:flex; flex-direction:column; }
.s5-icon { font-size:22px; margin-bottom:4px; }
.s5-card h3 { font-size:12px; font-weight:700; color:#111827; }
.s5-model { font-size:11px; font-weight:600; color:#1a65e1; margin:4px 0; }
.s5-reason { font-size:10px; color:#6b7280; line-height:1.4; flex:1; }
.methodology-bar { background:rgba(255,255,255,0.6); border-radius:10px; padding:10px 16px; font-size:11px; color:#4b5563; text-align:center; margin-top:8px; }

/* DAG Layout */
.dag-layout { flex-direction:row !important; gap:clamp(16px,2.5vw,32px); }
.dag-left { flex:1; display:flex; flex-direction:column; }
.dag-right { flex:1; min-height:0; display:flex; align-items:center; }
.dag-benefits { margin-top:10px; display:flex; flex-direction:column; gap:8px; }
.dag-benefit { font-size:12px; color:#374151; line-height:1.4; }
.dag-check { margin-right:6px; }

/* Search Flow */
.search-flow-layout .search-body { flex:1; display:flex; flex-direction:column; gap:12px; }
.search-query { text-align:center; font-size:14px; color:#374151; }
.search-paths { display:flex; gap:10px; flex:1; }
.path-card { flex:1; border-radius:12px; padding:12px 14px; display:flex; flex-direction:column; }
.path-frame { background:linear-gradient(180deg,rgba(79,147,237,0.08),rgba(79,147,237,0.02)); border:1px solid rgba(79,147,237,0.2); }
.path-chunk { background:linear-gradient(180deg,rgba(96,201,168,0.08),rgba(96,201,168,0.02)); border:1px solid rgba(96,201,168,0.2); }
.path-text { background:linear-gradient(180deg,rgba(103,196,192,0.08),rgba(103,196,192,0.02)); border:1px solid rgba(103,196,192,0.2); }
.path-label { background:linear-gradient(180deg,rgba(156,163,175,0.08),rgba(156,163,175,0.02)); border:1px solid rgba(156,163,175,0.2); }
.path-head { font-size:13px; font-weight:700; color:#111827; margin-bottom:4px; }
.path-detail { font-size:11px; color:#4b5563; }
.path-precision { font-size:10px; margin:4px 0; }
.path-precision span { font-weight:600; }
.path-frame .path-precision span { color:#4f93ed; }
.path-chunk .path-precision span { color:#60c9a8; }
.path-text .path-precision span { color:#67c4c0; }
.search-merge { text-align:center; font-size:13px; color:#374151; }

/* Param System */
.param-layout .param-body { display:flex; gap:16px; flex:1; }
.index-section { display:flex; flex-direction:column; gap:10px; flex:1; }
.index-card { display:flex; align-items:flex-start; gap:10px; background:linear-gradient(180deg,#ffffff 0%,#f8fafc 100%); border-radius:12px; padding:14px 16px; box-shadow:0 2px 6px -2px rgba(0,0,0,0.08); }
.idx-num { width:26px; height:26px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:13px; font-weight:700; color:white; flex-shrink:0; }
.idx-frame .idx-num { background:#4f93ed; }
.idx-text .idx-num { background:#67c4c0; }
.idx-chunk .idx-num { background:#34d399; }
.index-card h3 { font-size:14px; font-weight:700; color:#111827; }
.index-card p { font-size:11px; color:#6b7280; line-height:1.4; }
.param-pyramid { flex:1; display:flex; align-items:center; }

/* Tech Stack */
.tech-layout .tech-body { flex:1; display:flex; flex-direction:column; gap:12px; }
.tech-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
.tech-item { display:flex; align-items:center; gap:8px; background:rgba(255,255,255,0.6); border-radius:8px; padding:8px 12px; font-size:11px; color:#374151; }
.tech-cat { font-weight:700; color:#1a65e1; white-space:nowrap; font-size:10px; background:rgba(26,101,225,0.1); padding:2px 8px; border-radius:6px; }
.status-cols { display:flex; gap:16px; flex:1; }
.status-col { flex:1; background:linear-gradient(180deg,#ffffff 0%,#f8fafc 100%); border-radius:12px; padding:14px 16px; box-shadow:0 2px 6px -2px rgba(0,0,0,0.08); }
.status-col h3 { font-size:13px; font-weight:700; color:#111827; margin-bottom:8px; }
.status-col ul { list-style:none; font-size:11px; color:#4b5563; line-height:1.8; }
.status-col ul li::before { content:"▸ "; color:#34d399; }
.road-item { font-size:11px; color:#374151; margin-bottom:6px; line-height:1.4; padding-left:4px; }
.road-prio { display:inline-block; font-size:9px; font-weight:700; padding:1px 6px; border-radius:4px; margin-right:4px; }
.p0 { background:rgba(52,211,153,0.15); color:#34d399; }
.p1 { background:rgba(26,101,225,0.12); color:#1a65e1; }
.p2 { background:rgba(156,163,175,0.2); color:#6b7280; }

/* VS Layout */
.vs-layout .vs-body { display:flex; gap:12px; flex:1; }
.vs-col { flex:1; border-radius:12px; padding:14px 16px; display:flex; flex-direction:column; }
.vs-red { background:linear-gradient(180deg,rgba(239,68,68,0.05),rgba(239,68,68,0.01)); border:1px solid rgba(239,68,68,0.12); }
.vs-blue { background:linear-gradient(180deg,rgba(26,101,225,0.05),rgba(26,101,225,0.01)); border:1px solid rgba(26,101,225,0.12); }
.vs-mid { background:linear-gradient(180deg,rgba(103,196,192,0.05),rgba(103,196,192,0.01)); border:1px solid rgba(103,196,192,0.12); }
.vs-col h3 { font-size:15px; font-weight:700; margin-bottom:10px; }
.vs-red h3 { color:#dc2626; }
.vs-blue h3 { color:#1a65e1; }
.vs-mid h3 { color:#67c4c0; }
.vs-col ul { list-style:none; font-size:11px; color:#374151; line-height:1.9; }
.vs-col ul li::before { content:"• "; margin-right:4px; }
.vs-red ul li::before { color:#dc2626; }
.vs-blue ul li::before { color:#1a65e1; }
.vs-col p { font-size:11px; color:#4b5563; line-height:1.5; }
.vs-mid-title { font-size:11px; font-weight:700; color:#374151; margin-top:4px; }

/* Compact List (roadmap) */
.compact-list { display:flex; flex-direction:column; gap:8px; }
.compact-item { display:flex; align-items:flex-start; gap:6px; font-size:11px; color:#374151; line-height:1.4; }
.compact-check { width:18px; height:18px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:10px; flex-shrink:0; }
.compact-check.green { background:rgba(52,211,153,0.15); color:#34d399; }
.compact-check.blue { background:rgba(26,101,225,0.12); color:#1a65e1; }

/* Paradigm Grid */
.paradigm-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; flex:1; }
.paradigm-card { border-radius:10px; overflow:hidden; box-shadow:0 2px 6px -2px rgba(0,0,0,0.08); }
.para-header { color:white; font-size:12px; font-weight:700; padding:8px 12px; }
.para-body { background:white; padding:10px 12px; }
.para-example { font-size:11px; font-weight:600; color:#1a65e1; margin-bottom:4px; }
.para-body p { font-size:11px; color:#4b5563; line-height:1.5; }
.paradigm-card.highlighted { box-shadow:0 0 0 2px #1a65e1; }

/* Route list */
.route-list { display:flex; flex-direction:column; gap:8px; margin:8px 0; }
.route-item { display:flex; align-items:center; gap:8px; font-size:12px; color:#374151; }
.route-badge { font-size:9px; font-weight:700; color:white; padding:3px 8px; border-radius:6px; white-space:nowrap; }

/* Bench compare */
.bench-compare { display:flex; flex-direction:column; gap:8px; margin-top:12px; }
.bench-row { display:flex; align-items:center; gap:8px; }
.bench-model { width:130px; font-size:11px; color:#374151; text-align:right; }
.bench-bar { flex:1; height:18px; background:#f3f4f6; border-radius:9px; overflow:hidden; }
.bench-bar > div { height:100%; border-radius:9px; }
.bench-score { width:30px; font-size:12px; font-weight:700; color:#1a65e1; }

/* Summary Close */
.summary-close-layout { position:relative; }
.close-content { position:relative; z-index:1; flex:1; display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; }
.close-content h2 { font-size:clamp(28px,4vw,44px); font-weight:800; color:#1a65e1; margin-bottom:8px; }
.close-tagline { font-size:clamp(14px,1.5vw,18px); font-weight:500; color:#111827; max-width:700px; line-height:1.4; margin-bottom:clamp(20px,3vw,36px); }
.close-counters { display:flex; gap:clamp(16px,2.5vw,32px); margin-bottom:clamp(20px,3vw,36px); }
.close-stat { text-align:center; }
.close-num { display:block; font-size:clamp(28px,3.5vw,42px); font-weight:800; color:#1a65e1; line-height:1; }
.close-label { display:block; font-size:clamp(9px,1vw,12px); color:#6b7280; margin-top:4px; line-height:1.3; }
.close-footer { font-size:clamp(11px,1.1vw,14px); color:#4b5563; max-width:800px; line-height:1.6; }

/* Responsive text size tweaks for small screens */
@media (max-width: 600px) {
  .two-col-layout { flex-direction:column !important; }
  .cards-row { flex-direction:column; }
  .tier-row { flex-direction:column; }
  .summary-5-grid { flex-direction:column; }
  .search-paths { flex-direction:column; }
  .vs-body { flex-direction:column; }
  .paradigm-grid { grid-template-columns:1fr; }
  .status-cols { flex-direction:column; }
  .model-grid { grid-template-columns:1fr; }
  .three-wide { flex-direction:column; }
  .three-stack-layout .stack-row { flex-direction:column; }
  .main-area { flex-direction:column; }
  .param-body { flex-direction:column; }
  .diff-grid { grid-template-columns:1fr; }
  .split-layout { flex-direction:column !important; }
  .dag-layout { flex-direction:column !important; }
  .quadrant-note { width:100%; }
  .close-counters { flex-wrap:wrap; justify-content:center; }
}
</style>
</head>
<body>

<div id="presentation">
"""

# Generate slides
for i, s in enumerate(slides):
    active = ' active' if i == 0 else ''
    slide_classes = f"slide{active}"
    html += f'<div class="{slide_classes}" data-index="{i}">\n'

    # Add blobs to slides that don't already have them positioned
    layout = s["layout"]
    if layout != "summary-close":  # close slide has its own blobs
        html += '  <div class="blob-blue" style="top:-5%;right:-5%;width:45%;height:80%"></div>\n'
        html += '  <div class="blob-green" style="bottom:-5%;right:-5%;width:40%;height:55%"></div>\n'
        # Add left blur for variety on some slides
        if i % 3 == 1:
            html += '  <div class="blob-left" style="top:10%;left:-2%;width:20%;height:80%"></div>\n'
        if i % 4 == 2:
            html += '  <div class="blob-right" style="bottom:0;right:0;width:25%;height:45%"></div>\n'

    html += s["content"]()
    html += '</div>\n'

# Navigation
html += """
</div>

<div id="nav">
  <button id="prev-btn" onclick="goSlide(-1)" disabled>‹</button>
  <span id="page-indicator">1 / %d</span>
  <div id="page-progress"><div id="page-progress-bar" style="width:%.1f%%"></div></div>
  <button id="next-btn" onclick="goSlide(1)">›</button>
</div>

<script>
const total = %d;
let current = 0;

function updateNav() {
  document.getElementById('page-indicator').textContent = (current+1) + ' / ' + total;
  document.getElementById('page-progress-bar').style.width = ((current+1)/total*100) + '%%';
  document.querySelectorAll('.slide').forEach((el, i) => {
    el.classList.toggle('active', i === current);
  });
  document.getElementById('prev-btn').disabled = current === 0;
  document.getElementById('next-btn').disabled = current === total-1;
}

function goSlide(delta) {
  const next = current + delta;
  if (next < 0 || next >= total) return;
  current = next;
  updateNav();
}

document.addEventListener('keydown', function(e) {
  if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'ArrowDown') {
    e.preventDefault(); goSlide(1);
  } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
    e.preventDefault(); goSlide(-1);
  }
});

// Touch support
let touchStartX = 0, touchStartY = 0;
document.addEventListener('touchstart', function(e) {
  touchStartX = e.changedTouches[0].screenX;
  touchStartY = e.changedTouches[0].screenY;
});
document.addEventListener('touchend', function(e) {
  const dx = e.changedTouches[0].screenX - touchStartX;
  const dy = e.changedTouches[0].screenY - touchStartY;
  if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 40) {
    goSlide(dx < 0 ? 1 : -1);
  }
});
</script>
</body>
</html>
""" % (len(slides), 100.0/len(slides), len(slides))

# Write output
output_path = '/home/jayden/cerno/docs/cerno-ppt.html'
with open(output_path, 'w') as f:
    f.write(html)

print(f"✅ Generated {len(slides)} slides → {output_path}")
print(f"   File size: {len(html):,} bytes")
