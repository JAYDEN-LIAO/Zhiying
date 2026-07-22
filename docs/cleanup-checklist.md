# 部署前清理清单

> 按优先级排列。标注「⚠️ 确认」表示请确认后再删。

## 一、必须处理

- [ ] `data/videos/`（137 个视频，运行时产生，全量约 10-50 GB）
- [ ] `data/artifacts/`（关键帧缩略图等 artifact）
- [ ] `frontend/node_modules/`（本地开发依赖，部署机应 `npm install` 重新生成）
- [ ] `frontend/dist/`（如有预构建需求则保留，否则可删除后重新 build）
- [ ] 所有 `__pycache__/` 目录（15 个目录，Python 缓存的字节码）

## 二、建议处理

- [ ] `models/reid.onnx`（9.5 MB，未引用，之前 ReID 实验残留）⚠️ 确认
- [ ] `models/yolo11n.pt`（5.4 MB，未在配置中引用，实验残留）⚠️ 确认
- [ ] `models/yolo26n-cls.pt`（5.6 MB，已从 git 删除，本地残留）⚠️ 确认
- [ ] `models/models/` 下完整模型缓存（约 20 GB，部署机需重新下载或手动拷贝）
- [ ] `.env`（含 API Key，不应随代码分发，需单独管理）
- [ ] `待测试.md`（如果磁盘上还有残留）

## 三、选读文件（非项目核心）

- [ ] `CLAUDE.md`（AI agent 上下文文件，部署机不需要）⚠️ 确认
- [ ] `docs/` 下的 `.html` 和 `.py` 文件（演示 PPT 及构建脚本）⚠️ 确认

## 四、架构/配置遗留

- [ ] `yolo26n-cls.pt` 已从 git 中删除，`config/botsort.yaml` 中对该文件的引用已注释
- [ ] 无 `.dockerignore` → Docker build 会复制 `models/`(20G) + `data/` + `.venv/` 等
- [ ] `config/secrets.yaml` 不存在（API key 管理通过 `.env` + 环境变量）
