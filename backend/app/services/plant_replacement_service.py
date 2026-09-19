"""绿植更换记录业务逻辑。"""

import hashlib
import json
from decimal import Decimal

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from ..constants import ENUM_GROUPS
from ..errors import ConflictError, ValidationError
from ..extensions import db
from ..models import GreenSpace, MaintenanceRecord, PlantReplacement, PriceFillBatch
from ..utils.numbers import to_float
from ..utils.sorting import parse_sort
from .base_service import BaseService
from .code_generator import daily_prefix


class PlantReplacementService(BaseService):
    """绿植更换记录：登记更换明细并自动核算金额。"""

    model = PlantReplacement
    label = "绿植更换记录"
    code_field = "replacement_no"
    code_width = 3

    SORTABLE = {
        "replace_date": PlantReplacement.replace_date,
        "quantity": PlantReplacement.quantity,
        "amount": PlantReplacement.amount,
        "created_at": PlantReplacement.created_at,
    }

    @classmethod
    def code_prefix(cls):
        return daily_prefix("PR")

    # ------------------------------------------------------------ 校验与派生
    @classmethod
    def prepare_instance(cls, instance, payload):
        green_space_id = payload.get("green_space_id", instance.green_space_id)
        space = db.session.get(GreenSpace, green_space_id) if green_space_id else None
        if space is None:
            raise ValidationError("登记失败", details={"green_space_id": "所选绿地不存在"})

        record_id = payload.get("maintenance_record_id", instance.maintenance_record_id)
        if record_id:
            record = db.session.get(MaintenanceRecord, record_id)
            if record is None:
                raise ValidationError(
                    "登记失败", details={"maintenance_record_id": "关联的养护记录不存在"}
                )
            if record.green_space_id != space.id:
                raise ValidationError(
                    "登记失败",
                    details={"maintenance_record_id": "关联的养护记录不属于所选绿地"},
                )

        replace_date = payload.get("replace_date", instance.replace_date)
        if replace_date and space.established_date and replace_date < space.established_date:
            raise ValidationError(
                "登记失败",
                details={"replace_date": f"更换日期不能早于该绿地建成日期 {space.established_date}"},
            )

    @classmethod
    def apply_derived(cls, instance):
        """金额 = 数量 × 单价；未填单价时留空，由前端提示补录。"""

        if instance.unit_price is None:
            instance.amount = None
        else:
            instance.amount = (
                Decimal(str(instance.quantity or 0)) * Decimal(str(instance.unit_price))
            ).quantize(Decimal("0.01"))

    # ------------------------------------------------------------ 批量补价
    @staticmethod
    def _price_fill_hash(items):
        """补价明细的指纹：同批次号但明细不同视为冲突。"""

        normalized = [
            {"id": item["id"], "unit_price": str(item["unit_price"])} for item in items
        ]
        blob = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @classmethod
    def price_fill(cls, payload):
        """批量补价：为单价待补的记录补录单价并核算金额。

        贯通与幂等设计：
        - 整批在同一个事务内提交；各处统计（类别/原因汇总、总览累计投入、
          绿地档案更换投入）都是对 amount 的实时聚合，提交瞬间自然一致，
          不存在需要逐处同步的冗余合计；
        - 金额按「数量 × 单价」绝对值重算，不做增量累加，重复执行不会翻倍；
        - 只作用于仍待补的记录（unit_price 为空），已补过的一律跳过，
          因此同一批记录无论提交多少次，效果等同于第一次；
        - 批次号全库唯一：同一批次号的重复提交直接返回首次处理结果。
        """

        batch_no = payload["batch_no"]
        request_hash = cls._price_fill_hash(payload["items"])

        existing = db.session.query(PriceFillBatch).filter_by(batch_no=batch_no).first()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ConflictError(
                    f"补价批次号 {batch_no} 已使用且明细不一致，请重新生成批次号后提交"
                )
            result = existing.result_payload()
            result["deduplicated"] = True
            return result

        # 先整批校验、再统一改写：任何一条记录不存在，整批不落库
        records = []
        for item in payload["items"]:
            replacement = db.session.get(PlantReplacement, item["id"])
            if replacement is None:
                raise ValidationError(
                    "补价失败", details={"items": f"更换记录 #{item['id']} 不存在或已被删除"}
                )
            records.append((replacement, item["unit_price"]))

        applied, skipped = [], []
        amount_total = Decimal("0")
        for replacement, unit_price in records:
            if replacement.unit_price is not None:
                skipped.append(
                    {
                        "id": replacement.id,
                        "replacement_no": replacement.replacement_no,
                        "reason": "已补过单价，本次跳过",
                        "unit_price": to_float(replacement.unit_price),
                        "amount": to_float(replacement.amount),
                    }
                )
                continue
            replacement.unit_price = unit_price
            cls.apply_derived(replacement)
            amount_total += Decimal(str(replacement.amount or 0))
            applied.append(
                {
                    "id": replacement.id,
                    "replacement_no": replacement.replacement_no,
                    "unit_price": to_float(replacement.unit_price),
                    "amount": to_float(replacement.amount),
                }
            )

        result = {
            "batch_no": batch_no,
            "applied_count": len(applied),
            "skipped_count": len(skipped),
            "amount_total": to_float(amount_total) or 0,
            "applied": applied,
            "skipped": skipped,
            "deduplicated": False,
        }
        batch = PriceFillBatch(
            batch_no=batch_no,
            request_hash=request_hash,
            item_count=len(payload["items"]),
            applied_count=len(applied),
            skipped_count=len(skipped),
            amount_total=result["amount_total"],
            operator=payload.get("operator"),
            result=json.dumps(result, ensure_ascii=False),
        )
        db.session.add(batch)
        try:
            db.session.commit()
        except IntegrityError as exc:
            # 并发下同批次号已被其他请求写入：返回首次处理结果，保证只生效一次
            db.session.rollback()
            existing = db.session.query(PriceFillBatch).filter_by(batch_no=batch_no).first()
            if existing is not None and existing.request_hash == request_hash:
                result = existing.result_payload()
                result["deduplicated"] = True
                return result
            raise ConflictError(
                f"补价批次号 {batch_no} 已使用且明细不一致，请重新生成批次号后提交"
            ) from exc
        except Exception:
            # 任何意外失败都显式回滚，避免部分改写残留在会话中
            db.session.rollback()
            raise
        return result

    # ------------------------------------------------------------ 查询
    @classmethod
    def _apply_filters(cls, query, filters):
        if filters.get("green_space_id"):
            query = query.filter(PlantReplacement.green_space_id == filters["green_space_id"])
        if filters.get("maintenance_record_id"):
            query = query.filter(
                PlantReplacement.maintenance_record_id == filters["maintenance_record_id"]
            )
        if filters.get("plant_category"):
            query = query.filter(PlantReplacement.plant_category == filters["plant_category"])
        if filters.get("reason"):
            query = query.filter(PlantReplacement.reason == filters["reason"])
        if filters.get("date_from"):
            query = query.filter(PlantReplacement.replace_date >= filters["date_from"])
        if filters.get("date_to"):
            query = query.filter(PlantReplacement.replace_date <= filters["date_to"])
        if filters.get("price_pending"):
            query = query.filter(PlantReplacement.unit_price.is_(None))
        keyword = filters.get("keyword")
        if keyword:
            like = f"%{keyword}%"
            query = query.filter(
                or_(
                    PlantReplacement.replacement_no.like(like),
                    PlantReplacement.plant_name.like(like),
                    PlantReplacement.spec.like(like),
                    PlantReplacement.supplier.like(like),
                    PlantReplacement.operator.like(like),
                )
            )
        return query

    @classmethod
    def list_replacements(cls, filters, args):
        query = cls._apply_filters(db.session.query(PlantReplacement), filters)
        return query.order_by(
            parse_sort(args, cls.SORTABLE, PlantReplacement.replace_date.desc())
        )

    @classmethod
    def detail(cls, obj_id):
        return cls.get(obj_id).to_dict(detail=True)

    @classmethod
    def summary(cls, filters):
        """更换汇总：按植物类别与更换原因统计数量、金额。"""

        def _group(column, group_key):
            rows = (
                cls._apply_filters(
                    db.session.query(
                        column,
                        func.count(PlantReplacement.id),
                        func.coalesce(func.sum(PlantReplacement.quantity), 0),
                        func.coalesce(func.sum(PlantReplacement.amount), 0),
                    ),
                    filters,
                )
                .group_by(column)
                .all()
            )
            return [
                {
                    "value": value,
                    "label": ENUM_GROUPS[group_key].label(value),
                    "count": count,
                    "quantity": to_float(quantity) or 0,
                    "amount": to_float(amount) or 0,
                }
                for value, count, quantity, amount in rows
            ]

        totals = cls._apply_filters(
            db.session.query(
                func.count(PlantReplacement.id),
                func.coalesce(func.sum(PlantReplacement.quantity), 0),
                func.coalesce(func.sum(PlantReplacement.amount), 0),
            ),
            filters,
        ).one()
        pending_price_count = (
            cls._apply_filters(db.session.query(func.count(PlantReplacement.id)), filters)
            .filter(PlantReplacement.unit_price.is_(None))
            .scalar()
            or 0
        )

        return {
            "total_count": totals[0] or 0,
            "total_quantity": to_float(totals[1]) or 0,
            "total_amount": to_float(totals[2]) or 0,
            "pending_price_count": pending_price_count,
            "by_category": _group(PlantReplacement.plant_category, "plant_category"),
            "by_reason": _group(PlantReplacement.reason, "replacement_reason"),
        }
