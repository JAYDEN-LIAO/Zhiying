# 素材库（ImageLibrary）v0.6 — 后端实现规格（阶段 ②）

> 本文件是**阶段②：后端 subjects 实现**的施工规格（全新开发，非合并）。阶段①前端合并见 `docs/image-library-integration.md`。
> 定位：给干活 agent 的头实现规格——表结构、路由、检索复用、存储卫生、验收。**实现细节由 agent 按本仓库现有惯例开发**（表定义参考 `core/models.py`、检索参考 `core/search.py`、路由参考 `api/router.py` / `api/search_routes.py`）。
> 后端当前**无任何 subjects 代码**，本章全部为新增。

## 决策约束（与阶段①共享）

- **A 归属**：接口仅服务桌面前端；**不接入服务器前端**（但接口仍在同一 FastAPI 服务，`/api/v1/subjects` 全局可路由）。
- **C 检索分轨**：目标种类 `person` / `other` 两态。
  - `person` → **ArcFace 512**（复用现有人脸编码，人强调人脸）
  - `other` → **Qwen3-VL**（复用现成图搜编码）
  - 两态向量**分表存储**（法 A），因维度不同（512 vs 4096/2048）不能同列。
- **D 版本**：v0.6。
- **E 告警红点**：**本期不做** `subject_alerts`、不做 `/subjects/{id}/alerts`、不做命中告警生成。前端 `SubjectAlert` 类型/空壳保留但无对应后端。

## 一、数据模型（新增 3 表）

> 加进 `core/models.py`，pragma 对齐现有表（`__tablename__`/`id`/时间戳/relationship 惯例）。

| 表 | 关键列 | 说明 |
|---|---|---|
| `image_subjects` | id, kind(`person`/`other`), name, tags(JSONB), photo_count, created_at, updated_at | 关注目标；`photo_count` 非权威值，可由照片数派生或维护 |
| `subject_photos` | id, subject_id FK(级联删除), file_path, crop(JSONB 归一化 0~1), is_primary, source(`upload`/`case`/`track`/`search`), source_video_id, created_at | 底库照片 |
| `subject_photo_embedding` | photo_id FK(唯一,级联), kind, embedding | 向量列：`kind=person` → `Vector(512)`；`kind=other` → `EmbedVector()`（4096/2048 随 `embedding_profile`） |

- 级联：删 subject → 删其 photos + embeddings + 磁盘文件；删 photo → 删其 embedding + 文件。
- `crop`/`source`/`source_video_id` 契约与前端 `Frontend-shared/types.ts` 一致，勿改字段名。

## 二、路由（`api/subjects_routes.py`，注册进 `api/router.py`）

```
GET    /subjects?kind=&tag=&search=          列表过滤
GET    /subjects/tags                        全库标签集合
POST   /subjects                             新建（kind/name/tags）
GET    /subjects/{id}                        详情
PUT    /subjects/{id}                        改名/改标签
DELETE /subjects/{id}                        删除（级联）
GET    /subjects/{id}/photos                 照片列表
POST   /subjects/{id}/photos                上传（multipart files[], source）
POST   /subjects/{id}/photos/import-case-asset  案例库转存（group_id, asset_id）
PUT    /subjects/{id}/photos/{photoId}       crop / is_primary
DELETE /subjects/{id}/photos/{photoId}       删照片
POST   /subjects/merge                       target 吸收 source 后删 source
GET    /subjects/{id}/primary-photo          主图文件
GET    /subjects/{id}/photos/{photoId}/file  照片文件
POST   /search/subjects                      素材库检索（阶段②核心）
```

- 照片文件落盘：新增目录（如 `subject_photos/`），**登记进 `core/storage_manager.py`**（存储卫生规矩）。
- 删除一律走 `repository.delete_*`（级联+清盘），勿直接删行。
- `merge`：把 source 的所有照片的 `subject_id` 改到 target，合并 tags，删 source；并发下需锁或事务。

## 三、检索实现（阶段②核心，person/other 分轨）

**不能直接调用** `core/search.py` 的 `face_identity_search` / `frame_vector_search`——那俩查的是**全局视频库表**（`face_identities`/`frame_embeddings`），不是素材库向量表。正确做法：

- **新建** `_subject_embedding_search(session, query_vec, kind, **)`：查 `subject_photo_embedding` 表，`kind=person` 用 `embedding`(512) 列、`kind=other` 用 `embedding`(4096/2048) 列，`1 - cosine_distance` 排序。**结构参考上面两个函数的写法**（`select + .label("sim") + order_by desc`）。
- 入参 `query`：
  - `person` → 走**人脸编码**：复用现有 InsightFace/ArcFace 编码 query 图或人脸 emb，得到 512 向量。
  - `other` → 走**图搜文本/图编码**：复用现有 Qwen3-VL embedder（`text_encode`/`image_encode`），得到 EmbedVector 维度向量。
- 返回：命中照片 → 关联 `subject_photos` + `image_subjects`，回填 `matched_subject?`（`{subject_id, subject_name, subject_kind}`）到检索结果（与前端 `SearchResultItem.matched_subject` 契约对齐）。
- 顶 K / min_similarity 参数与前端 `searchSubjects(query, {video_ids, top_k, min_similarity})` 契约一致（`top_k` 默认 20，`min_similarity` 默认 0.3）。

## 四、沉淀对接（source 溯源）

- `source="track"`：从 `tracks`/`frame_detections` 取该 track 缩略图落盘为底图，记录 `source_video_id`。
- `source="search"`：从图搜结果取对应帧/缩略图落盘。
- `source="case"`：`import-case-asset` 把 `case_assets` 的图按 assetId 引用转存为底图（复制文件到 subject_photos 目录）。
- 落盘后**顺手编码向量**入 `subject_photo_embedding`（懒加载，加图时编码一次）。
- 存储删除/登记遵循阶段⑤卫生规矩。

## 五、验收（阶段②通过标准）

1. 表：建表成功（PG17/pgvector），`subject_photo_embedding` 两态维度正确（512 vs 4096/2048）。
2. 接口：上述 16 个接口（除告警）经 curl 通；CRUD/裁剪/合并/上传/案例转存全通。
3. 检索：`person` 底图向量 → 命中正确 person 目标；`other` 底图 → 命中正确 other 目标；`matched_subject` 回填正确。
4. 溯源：`source_video_id` 存在时，前端「溯源」跳工作台命中该视频。
5. 存储卫生：删目标/照片 = 级联删 DB + 清磁盘文件；新增目录已在 `storage_manager.py` 登记。
6. 回归：现有 face/plate/ocr/search 相关功能不回归（新表/新路由不侵入现有查询）。
7. 版本一致 v0.6。

## 六、施工顺序

1. 建 3 表（`core/models.py` + 迁移）
2. 新增 `subject_photos` 落盘目录并登记 `storage_manager.py`
3. `api/subjects_routes.py` CRUD/照片/合并路由 + 注册 `router.py`
4. `subject_photo_embedding` 编码落库 + 检索路由（person/other 分轨）
5. 沉淀/溯源对接
6. 跑【五】全项 + 阶段①回归
7. commit/tag/push —— **事前征得用户同意**，作者 `JAYDEN-LIAO`

## 遗留（本期明确不做）

- `subject_alerts` / `/subjects/{id}/alerts` / 命中告警生成 / 侧栏红点后端（E，下一阶段）
- 服务器前端接入（A）
- `other` 类目下若未来要细分车辆等，不在此期。
