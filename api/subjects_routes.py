"""
api/subjects_routes.py
═══════════════════════════════════════════════════════════
图片素材库 API（v0.6）— 关注目标（人/其他）底库照片的 CRUD + 检索。

核心原则：
  - 底库维护完全人工，无任何自动去重；合并也是纯手动。
  - 检索分轨（决策 C）：person → ArcFace 512（人脸照片）；other → Qwen3-VL（通用图搜）。
  - 照片落盘 artifact_dir/subject_photos/{subject_id}/（storage_manager 登记）。
  - 告警（subject_alerts）本期不做（决策 E）。

检索为「图片检索」：上传一张照片，person 走人脸模型、other 走通用图搜——
与现有 api/search_routes.py 的 /search/face、/search/image 同构。
"""

import io
import os
import uuid
import shutil
import logging

import numpy as np
from PIL import Image
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from sqlalchemy import select, func, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas import APIResponse
from core.models import ImageSubject, SubjectPhoto, SubjectPhotoEmbedding
from core.schemas import (
    ImageSubjectCreate, ImageSubjectUpdate, ImageSubjectItem,
    SubjectPhotoItem, SubjectPhotoUpdate, MergeSubjectsRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _dto_image_subject(s: ImageSubject) -> ImageSubjectItem:
    return ImageSubjectItem(
        id=s.id, kind=s.kind, name=s.name,
        tags=list(s.tags or []), photo_count=s.photo_count or 0,
        created_at=s.created_at, updated_at=s.updated_at,
    )


def _dto_photo(p: SubjectPhoto) -> SubjectPhotoItem:
    return SubjectPhotoItem(
        id=p.id, subject_id=p.subject_id, file_path=p.file_path,
        crop=p.crop, is_primary=p.is_primary or False,
        source=p.source, source_video_id=p.source_video_id,
        created_at=p.created_at,
    )


async def _recount_photos(db: AsyncSession, subject_id: uuid.UUID) -> None:
    """重算目标照片数 + 若无主图则自动设第一张为主图。"""
    cnt = int((await db.execute(select(func.count()).select_from(SubjectPhoto).where(SubjectPhoto.subject_id == subject_id))).scalar() or 0)
    await db.execute(
        sa_update(ImageSubject).where(ImageSubject.id == subject_id).values(photo_count=cnt)
    )
    if cnt > 0:
        has_primary = (await db.execute(
            select(SubjectPhoto.id).where(SubjectPhoto.subject_id == subject_id, SubjectPhoto.is_primary.is_(True)).limit(1)
        )).scalar()
        if has_primary is None:
            first = (await db.execute(
                select(SubjectPhoto).where(SubjectPhoto.subject_id == subject_id).order_by(SubjectPhoto.created_at).limit(1)
            )).scalar_one()
            first.is_primary = True
    await db.flush()


async def _embed_photo(request: Request, db: AsyncSession, photo: SubjectPhoto, subject: ImageSubject) -> None:
    """落盘后编码照片向量入库（person→ArcFace 512 / other→Qwen3-VL）。

    编码失败不阻断（照片已存，向量可后续补）；与 search_routes 检索编码同构。
    """
    try:
        if not os.path.exists(photo.file_path):
            return
        with open(photo.file_path, "rb") as fp:
            contents = fp.read()
        image = np.array(Image.open(io.BytesIO(contents)).convert("RGB"))
        row = SubjectPhotoEmbedding(photo_id=photo.id, kind=subject.kind)
        if subject.kind == "person":
            face_recognizer = getattr(request.app.state, "face_recognizer", None)
            if face_recognizer is None:
                return
            vec = await face_recognizer.extract_best_embedding(image)
            if vec is None:
                return
            row.face_embedding = vec
        else:
            embedder = getattr(request.app.state, "embedder", None)
            if embedder is None:
                return
            row.other_embedding = await embedder.encode_image(image)
        db.add(row)
        await db.flush()
    except Exception as e:  # noqa: BLE001
        logger.warning("素材库照片编码入库失败（底图已保存）: %s", e)


# ─────────────── 关注目标 CRUD ───────────────

@router.get("/subjects", response_model=APIResponse[list[ImageSubjectItem]])
async def list_subjects(
    kind: str | None = None,
    tag: str | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[ImageSubjectItem]]:
    """关注目标列表（kind/tag/search 过滤）。"""
    stmt = select(ImageSubject).order_by(ImageSubject.created_at.desc())
    if kind:
        stmt = stmt.where(ImageSubject.kind == kind)
    if tag:
        stmt = stmt.where(ImageSubject.tags.contains([tag]))
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(ImageSubject.name.ilike(like))
    rows = (await db.execute(stmt)).scalars().all()
    return APIResponse(data=[_dto_image_subject(s) for s in rows])


@router.get("/subjects/tags", response_model=APIResponse[list[str]])
async def list_subject_tags(db: AsyncSession = Depends(get_db)) -> APIResponse[list[str]]:
    """全库标签集合（去重）。"""
    rows = (await db.execute(select(ImageSubject.tags))).scalars().all()
    tags: set[str] = set()
    for r in rows:
        if r:
            tags.update(r)
    return APIResponse(data=sorted(tags))


@router.post("/subjects", response_model=APIResponse[ImageSubjectItem])
async def create_subject(
    payload: ImageSubjectCreate,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[ImageSubjectItem]:
    """新建关注目标（kind: person/other）。"""
    s = ImageSubject(kind=payload.kind, name=payload.name.strip(), tags=payload.tags or [])
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return APIResponse(data=_dto_image_subject(s))


@router.get("/subjects/{subject_id}", response_model=APIResponse[ImageSubjectItem])
async def get_subject(
    subject_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[ImageSubjectItem]:
    s = await db.get(ImageSubject, subject_id)
    if s is None:
        raise HTTPException(status_code=404, detail="目标不存在")
    return APIResponse(data=_dto_image_subject(s))


@router.put("/subjects/{subject_id}", response_model=APIResponse[ImageSubjectItem])
async def update_subject(
    subject_id: uuid.UUID,
    payload: ImageSubjectUpdate,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[ImageSubjectItem]:
    """更新目标名称/标签。"""
    s = await db.get(ImageSubject, subject_id)
    if s is None:
        raise HTTPException(status_code=404, detail="目标不存在")
    if payload.name is not None:
        s.name = payload.name.strip()
    if payload.tags is not None:
        s.tags = payload.tags
    await db.commit()
    await db.refresh(s)
    return APIResponse(data=_dto_image_subject(s))


@router.delete("/subjects/{subject_id}", response_model=APIResponse[dict])
async def delete_subject(
    subject_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    """删除目标 — 级联删照片文件 + DB 行 + 向量 + 目录。"""
    s = await db.get(ImageSubject, subject_id)
    if s is None:
        raise HTTPException(status_code=404, detail="目标不存在")
    sm = getattr(request.app.state, "storage_manager", None)
    if sm is not None:
        shutil.rmtree(sm.subject_photo_dir(subject_id), ignore_errors=True)
    await db.delete(s)
    await db.commit()
    return APIResponse(data={"ok": True})


# ─────────────── 底库照片 ───────────────

@router.get("/subjects/{subject_id}/photos", response_model=APIResponse[list[SubjectPhotoItem]])
async def list_subject_photos(
    subject_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[SubjectPhotoItem]]:
    if await db.get(ImageSubject, subject_id) is None:
        raise HTTPException(status_code=404, detail="目标不存在")
    rows = (await db.execute(
        select(SubjectPhoto).where(SubjectPhoto.subject_id == subject_id).order_by(SubjectPhoto.created_at)
    )).scalars().all()
    return APIResponse(data=[_dto_photo(p) for p in rows])


@router.post("/subjects/{subject_id}/photos", response_model=APIResponse[list[SubjectPhotoItem]])
async def upload_subject_photos(
    subject_id: uuid.UUID,
    request: Request,
    files: list[UploadFile] = File(...),
    source: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[SubjectPhotoItem]]:
    """上传底库照片（multipart 多文件）。落盘 subject_photos/{subject_id}/。"""
    s = await db.get(ImageSubject, subject_id)
    if s is None:
        raise HTTPException(status_code=404, detail="目标不存在")
    sm = getattr(request.app.state, "storage_manager", None)
    from core.paths import project_root
    dest_dir = sm.subject_photo_dir(subject_id) if sm else str(project_root() / "data" / "artifacts" / "subject_photos" / str(subject_id))
    os.makedirs(dest_dir, exist_ok=True)
    src = source or "upload"

    saved: list[SubjectPhotoItem] = []
    for f in files:
        if not f.filename:
            continue
        ext = os.path.splitext(f.filename)[1] or ".jpg"
        uid = uuid.uuid4()
        dest = os.path.join(dest_dir, f"{uid}{ext}")
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)
        p = SubjectPhoto(subject_id=subject_id, file_path=dest, source=src)
        db.add(p)
        await db.flush()
        await _embed_photo(request, db, p, s)
        saved.append(_dto_photo(p))
    await _recount_photos(db, subject_id)
    await db.commit()
    return APIResponse(data=saved)


@router.post("/subjects/{subject_id}/photos/import-case-asset", response_model=APIResponse[SubjectPhotoItem])
async def import_case_asset_photo(
    subject_id: uuid.UUID,
    request: Request,
    group_id: uuid.UUID = Form(...),
    asset_id: uuid.UUID = Form(...),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[SubjectPhotoItem]:
    """把案例库图片素材转存为目标底库照片（复制文件）。"""
    from core.models import CaseAsset
    s = await db.get(ImageSubject, subject_id)
    if s is None:
        raise HTTPException(status_code=404, detail="目标不存在")
    asset = await db.get(CaseAsset, asset_id)
    if asset is None or asset.group_id != group_id or not asset.path:
        raise HTTPException(status_code=404, detail="案例素材不存在")
    src_abs = _resolve_legacy_path(asset.path)  # 历史行可能存相对路径
    if not os.path.exists(src_abs):
        raise HTTPException(status_code=404, detail="案例素材不存在")
    sm = getattr(request.app.state, "storage_manager", None)
    from core.paths import project_root
    dest_dir = sm.subject_photo_dir(subject_id) if sm else str(project_root() / "data" / "artifacts" / "subject_photos" / str(subject_id))
    os.makedirs(dest_dir, exist_ok=True)
    ext = os.path.splitext(src_abs)[1] or ".jpg"
    dest = os.path.join(dest_dir, f"{uuid.uuid4()}{ext}")
    shutil.copyfile(src_abs, dest)
    p = SubjectPhoto(subject_id=subject_id, file_path=dest, source="case")
    db.add(p)
    await db.flush()
    await _embed_photo(request, db, p, s)
    await _recount_photos(db, subject_id)
    await db.commit()
    return APIResponse(data=_dto_photo(p))


@router.put("/subjects/{subject_id}/photos/{photo_id}", response_model=APIResponse[SubjectPhotoItem])
async def update_subject_photo(
    subject_id: uuid.UUID,
    photo_id: uuid.UUID,
    payload: SubjectPhotoUpdate,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[SubjectPhotoItem]:
    """裁剪 / 设主图。"""
    p = await db.get(SubjectPhoto, photo_id)
    if p is None or p.subject_id != subject_id:
        raise HTTPException(status_code=404, detail="照片不存在")
    # 仅当显式传了 crop 才改（区分「设主图未带 crop」与「清除裁剪 crop=null」）
    if "crop" in payload.model_fields_set:
        p.crop = payload.crop
    if payload.is_primary:
        # 取消本目标其它主图（排除当前照片），再设当前为主图
        await db.execute(
            sa_update(SubjectPhoto)
            .where(SubjectPhoto.subject_id == subject_id, SubjectPhoto.id != photo_id)
            .values(is_primary=False)
            .execution_options(synchronize_session=False)
        )
        p.is_primary = True
    await db.commit()
    await db.refresh(p)
    return APIResponse(data=_dto_photo(p))


@router.delete("/subjects/{subject_id}/photos/{photo_id}", response_model=APIResponse[dict])
async def delete_subject_photo(
    subject_id: uuid.UUID,
    photo_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    """删除底库照片 — 删 DB 行 + 向量 + 磁盘文件。"""
    p = await db.get(SubjectPhoto, photo_id)
    if p is None or p.subject_id != subject_id:
        raise HTTPException(status_code=404, detail="照片不存在")
    if os.path.exists(p.file_path):
        try:
            os.remove(p.file_path)
        except OSError:
            pass
    await db.execute(SubjectPhotoEmbedding.__table__.delete().where(SubjectPhotoEmbedding.photo_id == photo_id))
    await db.delete(p)
    await _recount_photos(db, subject_id)
    await db.commit()
    return APIResponse(data={"ok": True})


# ─────────────── 合并 ───────────────

def _resolve_legacy_path(p: str) -> str:
    """历史行可能存相对路径（CWD 恰好=项目根才碰巧可用）→ 收敛到项目根绝对路径。"""
    if os.path.isabs(p):
        return p
    from core.paths import project_root
    return str(project_root() / p)


@router.post("/subjects/merge", response_model=APIResponse[dict])
async def merge_subjects(
    payload: MergeSubjectsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    """手动合并：把 source 的全部照片并入 target，合并标签，删除 source。

    ⚠️ 实现要点（v0.6.2 修复）：照片文件按「每目标一目录」落盘，必须先把文件
    从 source 目录**搬到 target 目录并重写 file_path**，否则直接删源目录会把
    刚并入的照片全部变成死链。此前的实现还缺 `request` 参数声明 → 必然
    NameError 500，该接口整体不可用。

    顺序：搬文件 → 改行 → 清残留目录 → commit。中途崩溃的孤儿文件由
    sweep 的 subject_photo_files 类目兜底回收。
    """
    if payload.target_subject_id == payload.source_subject_id:
        raise HTTPException(status_code=400, detail="不能合并到自身")
    target = await db.get(ImageSubject, payload.target_subject_id)
    source = await db.get(ImageSubject, payload.source_subject_id)
    if target is None or source is None:
        raise HTTPException(status_code=404, detail="目标不存在")

    sm = getattr(request.app.state, "storage_manager", None)

    def _photo_dir(sid: uuid.UUID) -> str:
        return sm.subject_photo_dir(sid) if sm else _resolve_legacy_path(
            os.path.join("data", "artifacts", "subject_photos", str(sid))
        )

    src_dir = _photo_dir(source.id)
    dest_dir = _photo_dir(target.id)
    os.makedirs(dest_dir, exist_ok=True)

    # 1. 逐张搬文件 + 重写 file_path（uuid 文件名天然不冲突；撞名兜底换名）
    rows = (await db.execute(
        select(SubjectPhoto).where(SubjectPhoto.subject_id == source.id)
    )).scalars().all()
    moved_skipped = 0
    for p in rows:
        if not p.file_path:
            moved_skipped += 1
            continue
        src_abs = _resolve_legacy_path(p.file_path)
        if not os.path.exists(src_abs):
            moved_skipped += 1  # 文件已丢：保留行挂在新目标下至少可见损坏状态
            p.file_path = os.path.join(dest_dir, "missing_" + os.path.basename(src_abs))
            continue
        dest = os.path.join(dest_dir, os.path.basename(src_abs))
        if os.path.abspath(dest) == os.path.abspath(src_abs):
            continue
        if os.path.exists(dest):  # 极小概率撞名（理论仅手工拷贝同 uid）
            dest = os.path.join(
                dest_dir, f"{uuid.uuid4()}{os.path.splitext(src_abs)[1]}"
            )
        shutil.move(src_abs, dest)
        p.file_path = dest

    # 2. 合并标签 + 计数
    merged_tags = list(dict.fromkeys(list(target.tags or []) + list(source.tags or [])))
    target.tags = merged_tags
    for p in rows:
        p.subject_id = target.id
    await _recount_photos(db, target.id)

    # 3. 源目录此刻应只剩空壳/无引用残留 → 清掉（即便有漏网也有 sweep 兜底）
    if sm is not None:
        shutil.rmtree(src_dir, ignore_errors=True)

    await db.delete(source)
    await db.commit()
    if moved_skipped:
        logger.warning("[Subjects] merge %s -> %s: %d photo files were missing on disk",
                       source.id, target.id, moved_skipped)
    return APIResponse(data={"ok": True, "target_subject_id": str(target.id)})


# ─────────────── 文件服务 ───────────────

@router.get("/subjects/{subject_id}/primary-photo")
async def get_primary_photo(
    subject_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """目标主图文件（列表头像）。"""
    from fastapi.responses import FileResponse
    p = (await db.execute(
        select(SubjectPhoto).where(SubjectPhoto.subject_id == subject_id)
        .order_by(SubjectPhoto.is_primary.desc(), SubjectPhoto.created_at).limit(1)
    )).scalar_one_or_none()
    if p is None or not os.path.exists(p.file_path):
        raise HTTPException(status_code=404, detail="无主图")
    return FileResponse(p.file_path)


@router.get("/subjects/{subject_id}/photos/{photo_id}/file")
async def get_photo_file(
    subject_id: uuid.UUID,
    photo_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """底库照片文件（详情/裁剪）。"""
    from fastapi.responses import FileResponse
    p = await db.get(SubjectPhoto, photo_id)
    if p is None or p.subject_id != subject_id or not os.path.exists(p.file_path):
        raise HTTPException(status_code=404, detail="照片不存在")
    return FileResponse(p.file_path)


# ─────────────── 检索（图片检索，核心） ───────────────

@router.post("/search/subjects")
async def search_subjects(
    request: Request,
    file: UploadFile = File(...),
    kind: str | None = Form(None),
    top_k: int = Form(20),
    min_similarity: float = Form(0.3),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    """素材库图片检索 — 上传一张照片，person 走人脸、other 走通用图搜。

    person：face_recognizer.extract_best_embedding → ArcFace 512 比对 face_embedding 列
    other ：embedder.encode_image → Qwen3-VL 比对 other_embedding 列
    按 kind 决定分轨；kind 未指定时两种都查（各自比对对应向量集）。
    """
    import time
    t0 = time.monotonic()
    try:
        contents = await file.read()
        img = Image.open(io.BytesIO(contents)).convert("RGB")
        image = np.array(img)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {e}")

    from core.search import subject_embedding_search

    hits: list[dict] = []
    # kind=other 或未指定且能编码一般图 → 通用图搜
    if kind != "person":
        embedder = getattr(request.app.state, "embedder", None)
        if embedder is not None:
            try:
                other_vec = await embedder.encode_image(image)
                other_hits = await subject_embedding_search(db, None, other_vec, "other", limit=top_k, min_similarity=min_similarity, kind_filter="other")
                hits.extend(other_hits)
            except Exception as e:
                logger.warning("素材库 other 检索失败: %s", e)
    # kind=person 或未指定 → 人脸
    if kind != "other":
        face_recognizer = getattr(request.app.state, "face_recognizer", None)
        if face_recognizer is not None:
            try:
                face_vec = await face_recognizer.extract_best_embedding(image)
                if face_vec is not None:
                    face_hits = await subject_embedding_search(db, face_vec, None, "person", limit=top_k, min_similarity=min_similarity, kind_filter="person")
                    hits.extend(face_hits)
            except Exception as e:
                logger.warning("素材库 person 检索失败: %s", e)

    items: list[dict] = []
    for p, sim in hits:
        subj = await db.get(ImageSubject, p.subject_id)
        items.append({
            "subject_id": str(p.subject_id),
            "subject_name": subj.name if subj else "",
            "subject_kind": subj.kind if subj else "other",
            "photo_id": str(p.id),
            "similarity": round(float(sim), 4),
            "is_primary": p.is_primary or False,
            "photo_url": f"/api/v1/subjects/{p.subject_id}/photos/{p.id}/file",
        })
    items.sort(key=lambda x: x["similarity"], reverse=True)
    items = items[:top_k]
    return APIResponse(data={
        "results": items,
        "total": len(items),
        "query_time_ms": (time.monotonic() - t0) * 1000,
    })
