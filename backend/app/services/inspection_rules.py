"""养护机械年检判定口径（唯一事实来源）。

台账列表、机械详情、到期拦截、存量重标都走这里，避免各处结论不一致：

- 年检日期以「年检记录」中同一机械编号最近一次为准（见 latest_inspection）；
- 到期阈值按所属班组区分，未配置的班组回落默认阈值 30 天；
- 维修中、已停用、已报废的机械不参与到期判定（免检）；
- 距今天不足阈值 -> 待年检；年检日期已早于今天 -> 已过期；
- 已过期且仍处于在用状态的机械由 assert_can_dispatch 拦下。
"""
from __future__ import annotations

from datetime import date
from typing import Any

# 默认到期预警阈值（天）：年检日期距今天不足该天数即标为待年检
DEFAULT_WARNING_DAYS = 30

# 按所属班组区分的阈值（天）；未命中的班组使用 DEFAULT_WARNING_DAYS
WARNING_DAYS_BY_TEAM: dict[str, int] = {
    "路基养护班": 30,
    "路面养护班": 15,
    "桥隧养护班": 45,
    "应急抢险班": 60,
}

# 不参与到期判定的状态：维修中与已停用（已报废视同停用）
EXEMPT_STATUSES = {"维修中", "已停用", "已报废"}
# 仍在投入使用的状态：这些状态下年检过期必须拦截
IN_USE_STATUSES = {"可用", "出勤中"}

STATUS_OK = "正常"
STATUS_PENDING = "待年检"
STATUS_EXPIRED = "已过期"
STATUS_EXEMPT = "免检"


def parse_date(value: Any) -> date | None:
    """宽松解析 YYYY-MM-DD 日期；解析不掉返回 None，由调用方决定是否报错。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def warning_days(team: Any) -> int:
    """取所属班组的到期阈值；班组未配置时回落默认 30 天。"""
    team_name = str(team or "").strip()
    return WARNING_DAYS_BY_TEAM.get(team_name, DEFAULT_WARNING_DAYS)


def latest_inspection(records: list[dict[str, Any]], machine_no: str) -> dict[str, Any] | None:
    """同一机械编号在年检记录里出现多次时，以年检日期最近一次为准。"""
    candidates = [
        record
        for record in records
        if str(record.get("机械编号", "")).strip() == machine_no
        and parse_date(record.get("年检日期")) is not None
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda record: parse_date(record.get("年检日期")))  # type: ignore[arg-type]


def evaluate(
    machine: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """对一台机械给出口径结论。台账与详情都用本函数，结论天然一致。

    返回字段：
    - 年检结论：正常 / 待年检 / 已过期 / 免检
    - 年检状态：与结论同义，供台账列直接展示
    - 剩余天数：距年检日期的天数（免检或无记录时为 None）
    - 到期阈值：本次判定实际使用的班组阈值
    - 是否在用、参与判定：供拦截与统计复用
    """
    today = today or date.today()
    team = machine.get("所属班组")
    threshold = warning_days(team)
    status = str(machine.get("status") or "").strip()
    exempt = status in EXEMPT_STATUSES
    in_use = status in IN_USE_STATUSES

    machine_no = str(machine.get("机械编号", "")).strip()
    latest = latest_inspection(records, machine_no)
    inspection_raw = latest.get("年检日期") if latest else machine.get("年检日期")
    inspection_day = parse_date(inspection_raw)

    result: dict[str, Any] = {
        "年检结论": STATUS_EXEMPT if exempt else None,
        "年检状态": STATUS_EXEMPT if exempt else "未登记",
        "剩余天数": None,
        "到期阈值": threshold,
        "是否在用": in_use,
        "参与判定": not exempt,
        "最近年检日期": inspection_raw if inspection_day else None,
    }

    if exempt:
        result["年检结论"] = f"{STATUS_EXEMPT}（{status}不参与到期判定）"
        return result

    if inspection_day is None:
        result["年检结论"] = "未登记年检"
        return result

    days_left = (inspection_day - today).days
    result["剩余天数"] = days_left
    if days_left < 0:
        conclusion = STATUS_EXPIRED
    elif days_left < threshold:
        conclusion = STATUS_PENDING
    else:
        conclusion = STATUS_OK
    result["年检结论"] = conclusion
    result["年检状态"] = conclusion
    return result


def assert_can_dispatch(machine: dict[str, Any], records: list[dict[str, Any]]) -> str | None:
    """超过有效期还在使用状态的机械必须拦下；返回 None 表示放行。"""
    result = evaluate(machine, records)
    if result["年检状态"] == STATUS_EXPIRED:
        latest = result["最近年检日期"]
        return (
            f"机械 {machine.get('机械编号')} 年检已于 {latest} 过期，"
            f"当前状态「{machine.get('status')}」仍属在用，禁止调度出勤，请先完成年检"
        )
    return None
