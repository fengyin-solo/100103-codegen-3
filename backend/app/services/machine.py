"""养护机械业务规则：状态流转、字段校验、年检口径与筛选都收在这里。

年检相关结论一律取自 app.services.inspection_rules，台账与详情共用，
保证机械台账与详情给出的结论一致。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.services import inspection_rules as rules
from app.store import store

MODULE = "machine"
INSPECTION_MODULE = "machine_inspection"
REQUIRED_FIELDS = ["机械编号", "机械名称", "规格型号"]
# 登记/编辑时允许写入的字段（机械编号为业务主键，不在此列，避免口径错乱）
EDITABLE_FIELDS = ["机械名称", "规格型号", "所属班组", "购置日期", "年检日期", "操作人员", "机械状态"]
DATE_FIELDS = ["购置日期", "年检日期"]
STATUS_ORDER = ["可用", "出勤中", "维修中", "已停用", "已报废"]
ACTION_RULES = {"调度出勤": "出勤中", "维修登记": "维修中", "停用登记": "已停用", "申请报废": "已报废"}
NEGATIVE_ACTIONS = []


class MachineService:
    # ---- 读取：统一附加年检结论 ------------------------------------------

    def _decorate(self, row: dict[str, Any]) -> dict[str, Any]:
        """给机械数据附加年检口径结论。台账与详情都走这里，结论一致。"""
        verdict = rules.evaluate(row, store.rows(INSPECTION_MODULE))
        decorated = dict(row)
        decorated["年检结论"] = verdict["年检结论"]
        decorated["年检状态"] = verdict["年检状态"]
        decorated["剩余天数"] = verdict["剩余天数"]
        decorated["到期阈值"] = verdict["到期阈值"]
        # 台账上的年检日期以年检记录最近一次为准，记录缺失时回落机械自身字段
        if verdict["最近年检日期"] is not None:
            decorated["年检日期"] = verdict["最近年检日期"]
        return decorated

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        inspection: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("机械编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        decorated = [self._decorate(row) for row in rows]
        if inspection:
            decorated = [row for row in decorated if row.get("年检状态") == inspection]
        total = len(decorated)
        start = max(page - 1, 0) * size
        return decorated[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return self._decorate(row) if row else None

    # ---- 写入：字段口径校验 ----------------------------------------------

    def _validate_dates(self, values: dict[str, Any]) -> list[str]:
        """校验日期格式与购置/年检先后顺序，返回可读的拒绝原因。"""
        errors: list[str] = []
        parsed: dict[str, Any] = {}
        for field in DATE_FIELDS:
            raw = values.get(field)
            if raw is None or str(raw).strip() == "":
                continue
            day = rules.parse_date(raw)
            if day is None:
                errors.append(f"{field}「{raw}」不是合法日期，需为 YYYY-MM-DD 格式")
            else:
                parsed[field] = day
        purchase_day = parsed.get("购置日期")
        inspection_day = parsed.get("年检日期")
        if purchase_day and inspection_day and purchase_day > inspection_day:
            errors.append(
                f"购置日期 {purchase_day.isoformat()} 晚于年检日期 {inspection_day.isoformat()}，"
                "机械不可能在购置之前完成年检，请核对后再保存"
            )
        return errors

    def _assert_not_expired_in_use(self, values: dict[str, Any]) -> str | None:
        """超过有效期还处于在用状态的机械不允许保存/出勤，必须拦下。"""
        probe = dict(values)
        verdict = rules.evaluate(probe, store.rows(INSPECTION_MODULE))
        if verdict["年检状态"] == rules.STATUS_EXPIRED and verdict["是否在用"]:
            return (
                f"机械 {values.get('机械编号')} 年检已于 {verdict['最近年检日期']} 过期，"
                f"当前状态「{values.get('status')}」仍属在用，禁止保存为在用状态；"
                "请先完成年检，或将机械转为维修中/已停用"
            )
        return None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, [f"缺少必填字段：{'、'.join(missing)}"]
        errors = self._validate_dates(values)
        if errors:
            return None, errors
        rows = store.rows(MODULE)
        machine_no = str(values.get("机械编号")).strip()
        if any(str(row.get("机械编号", "")).strip() == machine_no for row in rows):
            return None, [f"机械编号 {machine_no} 已存在，重复登记会导致年检口径错乱"]
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        fields = REQUIRED_FIELDS + [field for field in EDITABLE_FIELDS if field not in REQUIRED_FIELDS]
        entry.update({field: values.get(field) for field in fields})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        block = self._assert_not_expired_in_use(entry)
        if block:
            return None, [block]
        rows.append(entry)
        return self._decorate(entry), []

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """编辑机械：购置日期晚于年检日期等非法口径直接拒保并说明原因。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, [f"养护机械 {entry_id} 不存在或已归档"]
        errors = self._validate_dates(values)
        if errors:
            return None, errors
        merged = dict(entry)
        for field in EDITABLE_FIELDS:
            if field in values and str(values.get(field) or "").strip() != "":
                merged[field] = values.get(field)
        block = self._assert_not_expired_in_use(merged)
        if block:
            return None, [block]
        entry.update({field: merged[field] for field in EDITABLE_FIELDS})
        return self._decorate(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"养护机械 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于养护机械可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        # 超过有效期还在使用状态的机械必须拦下：调度出勤前先卡年检口径
        if action == "调度出勤":
            reason = rules.assert_can_dispatch(entry, store.rows(INSPECTION_MODULE))
            if reason:
                return None, reason
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return self._decorate(entry), f"养护机械已{action}"

    # ---- 存量重标 --------------------------------------------------------

    def reapply_all(self) -> dict[str, int]:
        """规则上线后按新口径把既有机械重新标一遍，台账与详情结论随之统一。"""
        counters = {"正常": 0, "待年检": 0, "已过期": 0, "免检": 0, "未登记年检": 0}
        for row in store.rows(MODULE):
            verdict = rules.evaluate(row, store.rows(INSPECTION_MODULE))
            row["年检结论"] = verdict["年检结论"]
            row["年检状态"] = verdict["年检状态"]
            row["剩余天数"] = verdict["剩余天数"]
            row["到期阈值"] = verdict["到期阈值"]
            if verdict["最近年检日期"] is not None:
                row["年检日期"] = verdict["最近年检日期"]
            row["abnormal"] = verdict["年检状态"] == rules.STATUS_EXPIRED
            counters[verdict["年检状态"]] = counters.get(verdict["年检状态"], 0) + 1
        return counters


class MachineInspectionService:
    """年检记录：同一机械编号可登记多次，判定时以最近一次为准。"""

    REQUIRED = ["机械编号", "年检日期"]
    OPTIONAL = ["检验机构", "经办人", "备注"]

    def list_records(self, machine_no: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(INSPECTION_MODULE)
        if machine_no:
            rows = [row for row in rows if machine_no in str(row.get("机械编号", ""))]
        return sorted(
            rows,
            key=lambda row: rules.parse_date(row.get("年检日期")) or date.min,
            reverse=True,
        )

    def create_record(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in self.REQUIRED if not str(values.get(field) or "").strip()]
        if missing:
            return None, [f"缺少必填字段：{'、'.join(missing)}"]
        machine_no = str(values.get("机械编号")).strip()
        machine = next(
            (row for row in store.rows(MODULE) if str(row.get("机械编号", "")).strip() == machine_no),
            None,
        )
        if machine is None:
            return None, [f"机械编号 {machine_no} 不在机械台账中，无法登记年检记录"]
        inspection_day = rules.parse_date(values.get("年检日期"))
        if inspection_day is None:
            return None, [f"年检日期「{values.get('年检日期')}」不是合法日期，需为 YYYY-MM-DD 格式"]
        purchase_day = rules.parse_date(machine.get("购置日期"))
        if purchase_day and inspection_day < purchase_day:
            return None, [
                f"年检日期 {inspection_day.isoformat()} 早于购置日期 {purchase_day.isoformat()}，"
                "机械不可能在购置之前完成年检，请核对后再保存"
            ]
        rows = store.rows(INSPECTION_MODULE)
        record: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        record["机械编号"] = machine_no
        record["年检日期"] = inspection_day.isoformat()
        for field in self.OPTIONAL:
            record[field] = values.get(field)
        rows.append(record)
        # 登记后同步最近年检日期到机械行，供不依赖记录的展示兜底
        latest = rules.latest_inspection(rows, machine_no)
        if latest:
            machine["年检日期"] = latest["年检日期"]
        # 新记录生效后若机械已超期且仍在使用，必须拦下并引导处置
        block = rules.assert_can_dispatch(machine, rows)
        if block:
            return record, [block]
        return record, []
