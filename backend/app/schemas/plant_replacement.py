"""绿植更换记录校验规则。"""

from ..constants import MEASURE_UNIT, OLD_PLANT_STATUS, PLANT_CATEGORY, REPLACEMENT_REASON
from ..errors import ValidationError
from ..utils.numbers import to_decimal
from .common import PayloadValidator


def validate_plant_replacement(payload):
    return (
        PayloadValidator(payload)
        .integer("green_space_id", "所属绿地", required=True, min_value=1)
        .integer("maintenance_record_id", "关联养护记录", min_value=1)
        .string("plant_name", "植株名称", required=True, max_length=96)
        .enum("plant_category", "植物类别", group=PLANT_CATEGORY, required=True)
        .string("spec", "规格", max_length=64)
        .number("quantity", "更换数量", required=True, min_value=0.01, max_value=999999)
        .enum("unit", "计量单位", group=MEASURE_UNIT, default="plant")
        .enum("reason", "更换原因", group=REPLACEMENT_REASON, required=True)
        .enum("old_plant_status", "原植株状况", group=OLD_PLANT_STATUS)
        .date("replace_date", "更换日期", required=True)
        .string("supplier", "供苗单位", max_length=96)
        .number("unit_price", "单价", min_value=0, max_value=99999999)
        .string("operator", "登记人", max_length=64)
        .text("remark", "备注", max_length=2000)
        .done()
    )


# 批量补价单次最多处理的明细条数
PRICE_FILL_MAX_ITEMS = 200


def validate_price_fill(payload):
    """批量补价：批次号 + 补价明细列表。

    批次号是幂等键：客户端在一批补价发起前生成一次，重试时原样携带；
    明细逐条校验，全部通过才进入业务层，保证整批要么全部生效、要么全部不生效。
    """

    data = (
        PayloadValidator(payload)
        .string("batch_no", "批次号", required=True, max_length=64)
        .string("operator", "操作人", max_length=64)
        .done()
    )

    raw_items = (payload or {}).get("items")
    errors = {}
    items = []
    if not isinstance(raw_items, list) or not raw_items:
        errors["items"] = "补价明细不能为空"
    elif len(raw_items) > PRICE_FILL_MAX_ITEMS:
        errors["items"] = f"单次补价不能超过 {PRICE_FILL_MAX_ITEMS} 条"
    else:
        seen_ids = set()
        for index, raw in enumerate(raw_items):
            label = f"第 {index + 1} 条明细"
            if not isinstance(raw, dict):
                errors[f"items.{index}"] = f"{label}格式不正确"
                continue
            try:
                record_id = int(str(raw.get("id")).strip())
                if record_id < 1:
                    raise ValueError
            except (TypeError, ValueError):
                errors[f"items.{index}.id"] = f"{label}的记录 ID 不合法"
                continue
            if record_id in seen_ids:
                errors[f"items.{index}.id"] = f"记录 #{record_id} 在批次中重复"
                continue
            try:
                unit_price = to_decimal(raw.get("unit_price"), f"{label}的单价")
            except ValueError as exc:
                errors[f"items.{index}.unit_price"] = str(exc)
                continue
            if unit_price is None:
                errors[f"items.{index}.unit_price"] = f"{label}的单价不能为空"
                continue
            if unit_price < 0:
                errors[f"items.{index}.unit_price"] = f"{label}的单价不能小于 0"
                continue
            if unit_price > 99999999:
                errors[f"items.{index}.unit_price"] = f"{label}的单价不能大于 99999999"
                continue
            seen_ids.add(record_id)
            items.append({"id": record_id, "unit_price": unit_price})

    if errors:
        raise ValidationError("补价数据未通过校验", details=errors)
    data["items"] = items
    return data
