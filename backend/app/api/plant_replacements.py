"""绿植更换记录接口。"""

from flask import Blueprint, request

from ..schemas import validate_plant_replacement, validate_price_fill
from ..schemas.filters import replacement_filters
from ..services import PlantReplacementService
from ..utils.pagination import paginate, parse_page_args
from ..utils.requests import json_body
from ..utils.responses import created, ok

bp = Blueprint("plant_replacements", __name__)


@bp.get("/plant-replacements")
def list_replacements():
    filters = replacement_filters(request.args)
    page, page_size = parse_page_args()
    query = PlantReplacementService.list_replacements(filters, request.args)
    data = paginate(query, page, page_size)
    data["summary"] = PlantReplacementService.summary(filters)
    return ok(data)


@bp.get("/plant-replacements/summary")
def replacement_summary():
    return ok(PlantReplacementService.summary(replacement_filters(request.args)))


@bp.post("/plant-replacements")
def create_replacement():
    payload = validate_plant_replacement(json_body())
    replacement = PlantReplacementService.create(payload)
    return created(replacement.to_dict(detail=True), message="绿植更换记录登记成功")


@bp.post("/plant-replacements/price-fill")
def price_fill_replacements():
    """批量补价：为单价待补的记录补录单价。

    整批单事务提交，金额实时贯通各处统计；批次号幂等，重复提交只生效一次。
    """

    payload = validate_price_fill(json_body())
    result = PlantReplacementService.price_fill(payload)
    if result["deduplicated"]:
        return ok(result, message="该批次已处理过，本次为重复提交，未重复生效")
    return ok(result, message=f"补价完成：成功 {result['applied_count']} 条，跳过 {result['skipped_count']} 条")


@bp.get("/plant-replacements/<int:replacement_id>")
def get_replacement(replacement_id):
    return ok(PlantReplacementService.detail(replacement_id))


@bp.put("/plant-replacements/<int:replacement_id>")
def update_replacement(replacement_id):
    payload = validate_plant_replacement(json_body())
    replacement = PlantReplacementService.update(replacement_id, payload)
    return ok(replacement.to_dict(detail=True), message="绿植更换记录已更新")


@bp.delete("/plant-replacements/<int:replacement_id>")
def delete_replacement(replacement_id):
    PlantReplacementService.delete(replacement_id)
    return ok(None, message="绿植更换记录已删除")
