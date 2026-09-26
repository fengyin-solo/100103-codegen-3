"""养护机械接口：维护养护机械，覆盖调度出勤、维修登记、申请报废、登记年检等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.machine import MachineService

router = APIRouter(prefix="/api/machine", tags=["养护机械"])

service = MachineService()

LIST_FIELDS = ["机械编号", "机械名称", "规格型号", "所属班组", "购置日期", "年检日期", "操作人员", "机械状态"]
STATUSES = ["可用", "出勤中", "维修中", "已报废"]


@router.get("/inspections")
def list_inspections(
    keyword: str | None = Query(default=None, description="按机械编号检索年检记录"),
) -> dict[str, Any]:
    """年检记录列表：同一机械编号出现多次时，判定以最近一次为准。"""
    records = service.list_inspections(keyword=keyword)
    return {"module": "machine_inspection", "total": len(records), "items": records}


@router.post("/rescale", response_model=ActionResult)
def rescale_entries() -> ActionResult:
    """按最新年检口径重标全部既有机械；规则调整后手工触发一次即可。"""
    count = service.rescale_all()
    return ActionResult(ok=True, message=f"已按新口径重标 {count} 台养护机械")


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出养护机械清单：返回当前过滤条件下的全量数据，含年检结论。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "machine", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按机械编号检索"),
    status: str | None = Query(default=None, description="可用、出勤中、维修中、已报废"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按机械编号与状态过滤养护机械列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条养护机械明细；年检结论与台账列表同口径。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"养护机械 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条养护机械；缺字段、日期不合法时说明原因而不是静默丢弃。"""
    entry, error = service.create_entry(payload.values)
    if error:
        return ActionResult(ok=False, message=error)
    return ActionResult(ok=True, message="养护机械已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条养护机械执行调度出勤、维修登记、申请报废、登记年检；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
