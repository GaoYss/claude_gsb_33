"""绿植更换记录校验规则。"""

from decimal import Decimal

from ..constants import MEASURE_UNIT, OLD_PLANT_STATUS, PLANT_CATEGORY, REPLACEMENT_REASON
from ..errors import ValidationError
from ..utils.numbers import to_decimal
from .common import PayloadValidator

# 单次批量补价的最大条数，防止误操作整表
MAX_PRICE_FILL_BATCH = 200

UNIT_PRICE_MIN = 0
UNIT_PRICE_MAX = 99999999


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


def validate_price_fill(payload):
    """批量补价校验：items 为 [{id, unit_price}]，逐项收集错误。"""

    if not isinstance(payload, dict):
        raise ValidationError("请求体必须是 JSON 对象")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValidationError("提交的数据未通过校验", details={"items": "补价明细不能为空"})
    if len(items) > MAX_PRICE_FILL_BATCH:
        raise ValidationError(
            "提交的数据未通过校验",
            details={"items": f"单次补价不能超过 {MAX_PRICE_FILL_BATCH} 条"},
        )

    errors = {}
    clean = []
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            errors[f"items.{index}"] = {"id": "补价明细格式不正确"}
            continue
        item_errors = {}
        try:
            rid = int(str(raw.get("id")).strip())
            if rid < 1:
                raise ValueError
        except (TypeError, ValueError):
            item_errors["id"] = "记录 id 必须是正整数"
            rid = None
        try:
            price = to_decimal(raw.get("unit_price"), "单价")
            if price is None:
                raise ValueError("单价不能为空")
            if price < Decimal(str(UNIT_PRICE_MIN)):
                raise ValueError(f"单价不能小于 {UNIT_PRICE_MIN}")
            if price > Decimal(str(UNIT_PRICE_MAX)):
                raise ValueError(f"单价不能大于 {UNIT_PRICE_MAX}")
            price = price.quantize(Decimal("0.01"))
        except ValueError as exc:
            item_errors["unit_price"] = str(exc)
            price = None
        if item_errors:
            errors[f"items.{index}"] = item_errors
        else:
            clean.append({"id": rid, "unit_price": price})

    if errors:
        raise ValidationError("提交的数据未通过校验", details=errors)
    return {"items": clean}
