"""养护机械接口：维护养护机械，覆盖调度出勤、维修登记、停用登记、申请报废等动作。

年检相关：
- GET  /api/machine/inspection-thresholds 查看按班组区分的到期阈值
- GET  /api/machine/inspection-records     年检记录（同编号多次时以最近一次为准）
- POST /api/machine/inspection-records     登记一次年检
- POST /api/machine/reinspect              按新口径重标全部既有机械
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.inspection_rules import DEFAULT_WARNING_DAYS, WARNING_DAYS_BY_TEAM
from app.services.machine import MachineInspectionService, MachineService

router = APIRouter(prefix="/api/machine", tags=["养护机械"])

service = MachineService()
inspection_service = MachineInspectionService()

LIST_FIELDS = ["机械编号", "机械名称", "规格型号", "所属班组", "购置日期", "年检日期", "操作人员", "机械状态"]
STATUSES = ["可用", "出勤中", "维修中", "已停用", "已报废"]
INSPECTION_RESULTS = ["正常", "待年检", "已过期", "免检", "未登记年检"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按机械编号检索"),
    status: str | None = Query(default=None, description="可用、出勤中、维修中、已停用、已报废"),
    inspection: str | None = Query(default=None, description="年检结论：正常、待年检、已过期、免检"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按机械编号、状态与年检结论过滤养护机械列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if inspection and inspection not in INSPECTION_RESULTS:
        raise HTTPException(
            status_code=400,
            detail=f"年检结论仅支持：{'、'.join(INSPECTION_RESULTS)}",
        )
    items, total = service.list_entries(
        keyword=keyword, status=status, inspection=inspection, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/inspection-thresholds")
def inspection_thresholds() -> dict[str, Any]:
    """到期阈值口径：按所属班组区分，未配置班组回落默认阈值。"""
    return {
        "默认阈值天数": DEFAULT_WARNING_DAYS,
        "班组阈值天数": WARNING_DAYS_BY_TEAM,
        "免检状态": ["维修中", "已停用", "已报废"],
        "在用状态": ["可用", "出勤中"],
    }


@router.get("/inspection-records")
def list_inspection_records(
    keyword: str | None = Query(default=None, description="按机械编号检索"),
) -> dict[str, Any]:
    """年检记录列表，按年检日期倒序；同一机械编号多次出现时判定以最近一次为准。"""
    items = inspection_service.list_records(keyword)
    return {"total": len(items), "items": items}


@router.post("/inspection-records", response_model=ActionResult)
def create_inspection_record(payload: EntryPayload) -> ActionResult:
    """登记一次年检；购置日期晚于年检日期等非法口径会被拦下并说明原因。"""
    record, errors = inspection_service.create_record(payload.values)
    if errors and record is None:
        return ActionResult(ok=False, message="；".join(errors))
    if errors:
        # 记录已保存，但该机械已超期且仍在使用：明确提示必须拦停处置
        return ActionResult(ok=True, message=f"年检记录已登记，但该机械需立即拦停：{errors[0]}", entry=record)
    return ActionResult(ok=True, message="年检记录已登记，到期结论已按新口径刷新", entry=record)


@router.post("/reinspect", response_model=ActionResult)
def reinspect_all() -> ActionResult:
    """规则上线后把既有机械按新口径重新标一遍。"""
    counters = service.reapply_all()
    summary = "、".join(f"{label}{count}台" for label, count in counters.items() if count)
    return ActionResult(ok=True, message=f"存量机械已按新口径重标：{summary}")


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出养护机械清单：返回全量数据，结论与台账、详情保持一致。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "machine", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条养护机械明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"养护机械 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条养护机械，缺字段或日期口径非法时说明原因而不是静默丢弃。"""
    entry, errors = service.create_entry(payload.values)
    if errors:
        return ActionResult(ok=False, message="；".join(errors))
    return ActionResult(ok=True, message="养护机械已登记", entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """编辑养护机械；购置日期晚于年检日期、超期在用等情况不允许保存并说明原因。"""
    entry, errors = service.update_entry(entry_id, payload.values)
    if errors:
        return ActionResult(ok=False, message="；".join(errors))
    return ActionResult(ok=True, message="养护机械已保存，年检结论已同步刷新", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条养护机械执行调度出勤、维修登记、停用登记、申请报废；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
