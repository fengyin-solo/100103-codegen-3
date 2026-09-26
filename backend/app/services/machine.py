"""养护机械业务规则：年检判定、状态流转、字段校验与筛选口径都收在这里。

年检口径说明：
- 年检日期即年检有效期至（到期日）；同一机械编号在年检记录里出现多次时，以最近一次为准。
- 到期日距今天不足班组阈值天数的机械自动标为「待年检」；阈值按所属班组区分，默认 30 天。
- 维修中、已停用（含已报废）的机械不参与到期判定。
- 超过有效期仍处于使用状态（可用、出勤中）的机械标记异常，并禁止再调度出勤。
- 列表、详情、动作拦截共用 evaluate_inspection 这一套结论，保证台账与详情口径一致。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.store import store

MODULE = "machine"
INSPECTION_MODULE = "machine_inspection"

REQUIRED_FIELDS = ["机械编号", "机械名称", "规格型号"]
STATUS_ORDER = ["可用", "出勤中", "维修中", "已报废"]
ACTION_RULES = {"调度出勤": "出勤中", "维修登记": "维修中", "申请报废": "已报废"}
INSPECTION_ACTION = "登记年检"

# 年检预警阈值（天）按所属班组区分；未列出的班组走默认 30 天
DEFAULT_THRESHOLD_DAYS = 30
TEAM_THRESHOLD_DAYS = {
    "机械一班": 30,
    "机械二班": 60,
    "桥梁机械班": 45,
}

# 维修中、已停用（含已报废）的机械不参与到期判定
EXEMPT_STATUSES = {"维修中", "已报废", "已停用"}
# 可用、出勤中属于使用状态，超过有效期必须拦下
USING_STATUSES = {"可用", "出勤中"}

CONCLUSION_OK = "正常"
CONCLUSION_DUE = "待年检"
CONCLUSION_EXPIRED = "已过期"
CONCLUSION_EXEMPT = "无需判定"
CONCLUSION_MISSING = "未登记年检"

_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d")


def _parse_date(raw: Any) -> date | None:
    """把台账里的日期文本解析成 date；空值或格式不识别时返回 None。"""
    text = str(raw or "").strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _threshold_for(team: str) -> int:
    """所属班组配置了阈值就用班组的，否则用默认 30 天。"""
    return TEAM_THRESHOLD_DAYS.get(team, DEFAULT_THRESHOLD_DAYS)


def _latest_inspection(machine_code: str) -> dict[str, Any] | None:
    """同一机械编号在年检记录里出现多次时，以最近一次（id 最大）为准。"""
    records = [
        row
        for row in store.rows(INSPECTION_MODULE)
        if str(row.get("机械编号", "")).strip() == machine_code
    ]
    if not records:
        return None
    return max(records, key=lambda row: int(row.get("id", 0)))


def evaluate_inspection(entry: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """按年检口径给单台机械下结论；台账列表、详情、动作拦截都走这里。"""
    today = today or date.today()
    status = str(entry.get("status") or "").strip()
    team = str(entry.get("所属班组") or "").strip()
    threshold = _threshold_for(team)
    result: dict[str, Any] = {
        "conclusion": CONCLUSION_OK,
        "message": "",
        "threshold": threshold,
        "inspection_date": None,
        "days_left": None,
    }
    if status in EXEMPT_STATUSES:
        result["conclusion"] = CONCLUSION_EXEMPT
        result["message"] = f"机械处于「{status}」状态，不参与年检到期判定"
        return result
    code = str(entry.get("机械编号") or "").strip()
    record = _latest_inspection(code)
    raw_due = record.get("年检日期") if record else entry.get("年检日期")
    due = _parse_date(raw_due)
    if due is None:
        result["conclusion"] = CONCLUSION_MISSING
        result["message"] = "未登记有效年检日期，请补录年检记录"
        return result
    days_left = (due - today).days
    result["inspection_date"] = due.isoformat()
    result["days_left"] = days_left
    if days_left < 0:
        result["conclusion"] = CONCLUSION_EXPIRED
        result["message"] = f"年检已于 {due.isoformat()} 到期，超期 {-days_left} 天"
    elif days_left < threshold:
        result["conclusion"] = CONCLUSION_DUE
        result["message"] = (
            f"年检 {due.isoformat()} 到期，剩余 {days_left} 天，"
            f"低于{team or '所属'}班组阈值 {threshold} 天"
        )
    else:
        result["message"] = f"年检 {due.isoformat()} 到期，剩余 {days_left} 天"
    return result


def refresh_entry(entry: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """把年检结论写回机械行，台账列表与详情读到的是同一份结论。"""
    result = evaluate_inspection(entry, today)
    entry["年检结论"] = result["conclusion"]
    entry["年检提示"] = result["message"]
    entry["年检阈值"] = result["threshold"]
    entry["剩余天数"] = result["days_left"]
    conclusion = result["conclusion"]
    entry["pending"] = conclusion in {CONCLUSION_DUE, CONCLUSION_EXPIRED, CONCLUSION_MISSING}
    entry["abnormal"] = (
        conclusion == CONCLUSION_EXPIRED and str(entry.get("status") or "").strip() in USING_STATUSES
    )
    return entry


class MachineService:
    def __init__(self) -> None:
        # 规则上线即按新口径把既有机械重标一遍
        self.rescale_all()

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        for row in rows:
            refresh_entry(row)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("机械编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is not None:
            refresh_entry(entry)
        return entry

    def list_inspections(self, keyword: str | None = None) -> list[dict[str, Any]]:
        """年检记录列表：同一机械编号出现多次时，判定以最近一次（id 最大）为准。"""
        records = store.rows(INSPECTION_MODULE)
        if keyword:
            records = [row for row in records if keyword in str(row.get("机械编号", ""))]
        return sorted(records, key=lambda row: int(row.get("id", 0)))

    def rescale_all(self, today: date | None = None) -> int:
        """按最新年检口径重标全部既有机械，返回重标数量。"""
        rows = store.rows(MODULE)
        for row in rows:
            refresh_entry(row, today)
        return len(rows)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        purchase = _parse_date(values.get("购置日期"))
        inspection = _parse_date(values.get("年检日期"))
        if str(values.get("购置日期") or "").strip() and purchase is None:
            return None, "购置日期格式无法识别，请按 YYYY-MM-DD 填写"
        if str(values.get("年检日期") or "").strip() and inspection is None:
            return None, "年检日期格式无法识别，请按 YYYY-MM-DD 填写"
        if purchase and inspection and purchase > inspection:
            return None, (
                f"购置日期 {purchase.isoformat()} 晚于年检日期 {inspection.isoformat()}，"
                "机械尚未购置不可能已完成年检，数据不允许保存"
            )
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for field in ("所属班组", "购置日期", "年检日期", "操作人员"):
            if values.get(field) is not None:
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["机械状态"] = STATUS_ORDER[0]
        refresh_entry(entry)
        rows.append(entry)
        return entry, None

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"养护机械 {entry_id} 不存在或已归档"
        if action == INSPECTION_ACTION:
            return self._register_inspection(entry, values or {})
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于养护机械可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        refresh_entry(entry)
        if target in USING_STATUSES and entry.get("年检结论") == CONCLUSION_EXPIRED:
            return None, (
                f"机械{entry.get('机械编号')}年检已过期（{entry.get('年检提示')}），"
                f"禁止{action}，请先{INSPECTION_ACTION}"
            )
        entry["status"] = target
        entry["机械状态"] = target
        refresh_entry(entry)
        return entry, f"养护机械已{action}"

    def _register_inspection(
        self,
        entry: dict[str, Any],
        values: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str]:
        status = str(entry.get("status") or "").strip()
        if status in {"已报废", "已停用"}:
            return None, f"机械{entry.get('机械编号')}处于「{status}」状态，无需登记年检"
        due = _parse_date(values.get("年检日期"))
        if due is None:
            return None, "登记年检需提供有效的新年检日期（格式如 2027-09-30）"
        purchase = _parse_date(entry.get("购置日期"))
        if purchase and purchase > due:
            return None, (
                f"新年检日期 {due.isoformat()} 早于购置日期 {purchase.isoformat()}，不允许登记"
            )
        records = store.rows(INSPECTION_MODULE)
        record = {
            "id": max((int(row.get("id", 0)) for row in records), default=0) + 1,
            "机械编号": entry.get("机械编号"),
            "年检日期": due.isoformat(),
            "经办人": str(values.get("经办人") or entry.get("操作人员") or "").strip(),
        }
        records.append(record)
        entry["年检日期"] = due.isoformat()  # 台账同步最近一次年检结论
        refresh_entry(entry)
        return entry, f"机械{entry.get('机械编号')}已登记年检，有效期至 {due.isoformat()}"
