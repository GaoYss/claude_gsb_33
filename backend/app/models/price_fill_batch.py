"""绿植更换批量补价批次台账。"""

import json

from ..extensions import db
from ..utils.dates import format_datetime
from ..utils.numbers import to_float
from .mixins import TimestampMixin, amount_column


class PriceFillBatch(TimestampMixin, db.Model):
    """一次批量补价的处理台账。

    批次号（batch_no）由客户端在发起一批补价前生成，全库唯一：
    同一批次号重复提交时直接返回首次处理结果，保证只生效一次；
    台账同时记录补价条数与金额，作为对外口径调整的核对凭据。
    """

    __tablename__ = "price_fill_batch"

    id = db.Column(db.Integer, primary_key=True)
    batch_no = db.Column(db.String(64), nullable=False, unique=True, index=True)
    request_hash = db.Column(db.String(64), nullable=False)
    item_count = db.Column(db.Integer, nullable=False, default=0)
    applied_count = db.Column(db.Integer, nullable=False, default=0)
    skipped_count = db.Column(db.Integer, nullable=False, default=0)
    amount_total = db.Column(amount_column(), nullable=False, default=0)
    operator = db.Column(db.String(64))
    result = db.Column(db.Text, nullable=False, default="{}")

    def result_payload(self):
        return json.loads(self.result or "{}")

    def to_dict(self):
        return {
            "id": self.id,
            "batch_no": self.batch_no,
            "item_count": self.item_count,
            "applied_count": self.applied_count,
            "skipped_count": self.skipped_count,
            "amount_total": to_float(self.amount_total) or 0,
            "operator": self.operator,
            "created_at": format_datetime(self.created_at),
        }
