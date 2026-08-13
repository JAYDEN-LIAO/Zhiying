"""
api/groups_routes.py
═══════════════════════════════════════════════════════════
文件库分组 API（v0.34）— 案例/分组 CRUD（名称/编号/负责人）。

组 = 案例（照智影 v2 demo）：一组视频文件归到一个案例，带 name/number/owner。
删除组 = 清空组内 videos 的 group_id（SET NULL）后删组。
"""

import os
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas import APIResponse
from core.models import Video, VideoGroup
from core.schemas import GroupCreate, VideoGroupResponse

logger = logging.getLogger(__name__)

router = APIRouter()


async def _group_to_dto(session: AsyncSession, g: VideoGroup) -> VideoGroupResponse:
    """组 → DTO（补 file_count = 组内文件数 + video_ids）。"""
    # 文件数 = 组内 distinct 文件（COALESCE(file_id, id)）
    cnt = await session.execute(
        text("""
            SELECT COUNT(DISTINCT COALESCE(file_id, id))
            FROM videos WHERE group_id = :gid
        """),
        {"gid": g.id},
    )
    ids = await session.execute(
        select(Video.id).where(Video.group_id == g.id)
    )
    return VideoGroupResponse(
        id=g.id,
        name=g.name,
        number=g.number,
        owner=g.owner,
        file_count=int(cnt.scalar() or 0),
        video_ids=[r[0] for r in ids.all()],
        created_at=g.created_at,
        updated_at=g.updated_at,
    )


@router.get("/groups", response_model=APIResponse[list[VideoGroupResponse]])
async def list_groups(db: AsyncSession = Depends(get_db)) -> APIResponse[list[VideoGroupResponse]]:
    """文件库分组列表（含 file_count）。"""
    result = await db.execute(
        select(VideoGroup).order_by(VideoGroup.created_at.desc())
    )
    groups = list(result.scalars().all())
    items = [await _group_to_dto(db, g) for g in groups]
    return APIResponse(data=items)


@router.post("/groups", response_model=APIResponse[VideoGroupResponse])
async def create_group(
    payload: GroupCreate,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[VideoGroupResponse]:
    """创建分组（案例）— name 必填，number/owner 可选。"""
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写文件名称")
    g = VideoGroup(name=name, number=payload.number, owner=payload.owner)
    db.add(g)
    await db.commit()
    await db.refresh(g)
    return APIResponse(data=await _group_to_dto(db, g))


@router.put("/groups/{group_id}", response_model=APIResponse[VideoGroupResponse])
async def update_group(
    group_id: uuid.UUID,
    payload: GroupCreate,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[VideoGroupResponse]:
    """更新分组名称/编号/负责人。"""
    g = await db.get(VideoGroup, group_id)
    if g is None:
        raise HTTPException(status_code=404, detail="分组不存在")
    if (payload.name or "").strip():
        g.name = payload.name.strip()
    g.number = payload.number
    g.owner = payload.owner
    await db.commit()
    await db.refresh(g)
    return APIResponse(data=await _group_to_dto(db, g))


@router.delete("/groups/{group_id}", response_model=APIResponse[dict])
async def delete_group(
    group_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    """删除整个案例 — 组内全部视频（含版本链）+ 图片素材 + 组 + 磁盘目录。"""
    import shutil
    from core.config_loader import load_config
    from core.repository import list_file_roots, list_file_versions, delete_video

    g = await db.get(VideoGroup, group_id)
    if g is None:
        raise HTTPException(status_code=404, detail="案例不存在")

    sm = getattr(request.app.state, "storage_manager", None)
    # 1. 删组内全部视频（每个根文件的整个版本链）
    roots = await list_file_roots(db)
    for r in roots:
        if r.get("group_id") != g.id:
            continue
        root_video = await db.get(Video, r["id"])
        if root_video is None:
            continue
        if root_video.file_id is None:
            await delete_video(db, root_video, storage_manager=sm)
        else:
            for v in await list_file_versions(db, root_video.file_id):
                await delete_video(db, v, storage_manager=sm)

    # 2. 图片素材 DB 行随 group CASCADE，清磁盘目录
    artifact_dir = load_config().get("storage", {}).get("artifact_dir", "data/artifacts")
    shutil.rmtree(os.path.join(artifact_dir, "case_assets", str(g.id)), ignore_errors=True)

    # 3. 删组
    await db.delete(g)
    await db.commit()
    return APIResponse(data={"ok": True})


@router.get("/groups/{group_id}/videos", response_model=APIResponse[list])
async def list_group_files(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list]:
    """组内文件列表（每文件一行，根行）。"""
    from core.repository import list_file_roots
    g = await db.get(VideoGroup, group_id)
    if g is None:
        raise HTTPException(status_code=404, detail="分组不存在")
    roots = await list_file_roots(db)
    in_group = [r for r in roots if r.get("group_id") == g.id]
    return APIResponse(data=in_group)


# ═══════════════════════════════════════════════════════════
# 案例素材（图片等非视频）v0.34
# ═══════════════════════════════════════════════════════════

@router.get("/groups/{group_id}/assets", response_model=APIResponse[dict])
async def list_group_assets(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    """案例内容：视频（版本链文件）+ 图片素材。"""
    from core.repository import list_file_roots
    from core.models import CaseAsset
    from core.schemas import CaseAssetItem, FileItem

    g = await db.get(VideoGroup, group_id)
    if g is None:
        raise HTTPException(status_code=404, detail="案例不存在")

    # 视频（版本链文件，取该组根文件）
    roots = await list_file_roots(db)
    videos = [FileItem(
        id=r["id"],
        name=r["file_name"],
        group_id=r.get("group_id"),
        duration=r.get("duration"),
        file_size=r.get("file_size"),
        created_at=r.get("created_at"),
        current_version_no=r.get("current_version_no"),
        current_status=r.get("current_status"),
        current_progress=float(r.get("current_progress") or 0.0),
        current_summary=r.get("current_summary"),
        versions_count=int(r.get("versions_count") or 1),
    ) for r in roots if r.get("group_id") == g.id]

    # 图片素材
    assets = await db.execute(
        select(CaseAsset).where(CaseAsset.group_id == g.id).order_by(CaseAsset.created_at.desc())
    )
    images = [CaseAssetItem.model_validate(a) for a in assets.scalars().all()]
    return APIResponse(data={"videos": videos, "images": images})


@router.post("/groups/{group_id}/assets", status_code=201, response_model=APIResponse[list])
async def upload_group_assets(
    group_id: uuid.UUID,
    request: Request,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list]:
    """上传案例图片素材（multipart, 多文件）。存 artifact_dir/case_assets/{group_id}/。"""
    import os, shutil
    from core.config_loader import load_config
    from core.models import CaseAsset
    from core.schemas import CaseAssetItem

    g = await db.get(VideoGroup, group_id)
    if g is None:
        raise HTTPException(status_code=404, detail="案例不存在")

    artifact_dir = load_config().get("storage", {}).get("artifact_dir", "data/artifacts")
    dest_dir = os.path.join(artifact_dir, "case_assets", str(group_id))
    os.makedirs(dest_dir, exist_ok=True)

    saved: list[CaseAssetItem] = []
    for f in files:
        if not f.filename:
            continue
        uid = uuid.uuid4()
        ext = os.path.splitext(f.filename)[1] or ".bin"
        dest = os.path.join(dest_dir, f"{uid}{ext}")
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)
        asset = CaseAsset(group_id=g.id, kind="image", name=f.filename, path=dest, file_size=os.path.getsize(dest))
        db.add(asset)
        await db.flush()
        saved.append(CaseAssetItem.model_validate(asset))
    await db.commit()
    return APIResponse(data=[s.model_dump() for s in saved])


@router.get("/groups/{group_id}/assets/{asset_id}/file")
async def get_asset_file(
    group_id: uuid.UUID,
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """返回案例图片素材文件（预览用）。"""
    from fastapi.responses import FileResponse
    from core.models import CaseAsset
    asset = await db.get(CaseAsset, asset_id)
    if asset is None or asset.group_id != group_id or not os.path.exists(asset.path):
        raise HTTPException(status_code=404, detail="素材不存在")
    return FileResponse(asset.path, filename=asset.name)


@router.delete("/groups/{group_id}/assets/{asset_id}", response_model=APIResponse[dict])
async def delete_asset(
    group_id: uuid.UUID,
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    """删除案例图片素材（DB 行 + 磁盘文件）。"""
    from core.models import CaseAsset
    asset = await db.get(CaseAsset, asset_id)
    if asset is None or asset.group_id != group_id:
        raise HTTPException(status_code=404, detail="素材不存在")
    if os.path.exists(asset.path):
        try:
            os.remove(asset.path)
        except OSError:
            pass
    await db.delete(asset)
    await db.commit()
    return APIResponse(data={"ok": True})
