"""批量补价：金额贯通各处统计、重复提交只生效一次。"""

import pytest

BASE = "/api/v1/plant-replacements"


def _fill(api, batch_no, items, expected_status=200, **extra):
    response = api.post(f"{BASE}/price-fill", json={"batch_no": batch_no, "items": items, **extra})
    return api.data(response, expected_status)


def _overview_amount(api):
    return api.data(api.get("/api/v1/statistics/overview"))["replacement"]


def _profile_amount(api, space_id):
    return api.data(api.get(f"/api/v1/green-spaces/{space_id}/profile"))["statistics"]


def test_price_fill_propagates_to_all_statistics(api, make_space, make_replacement):
    space = make_space()
    first = make_replacement(space=space, unit_price=None, quantity=10,
                             plant_category="tree", reason="dead")
    second = make_replacement(space=space, unit_price=None, quantity=4,
                              plant_category="shrub", reason="aging")

    result = _fill(api, "BATCH-001", [
        {"id": first.id, "unit_price": 12.5},
        {"id": second.id, "unit_price": 25},
    ])

    assert result["deduplicated"] is False
    assert result["applied_count"] == 2
    assert result["skipped_count"] == 0
    assert result["amount_total"] == pytest.approx(225.0)

    # 明细金额
    assert api.data(api.get(f"{BASE}/{first.id}"))["amount"] == pytest.approx(125.0)
    assert api.data(api.get(f"{BASE}/{second.id}"))["amount"] == pytest.approx(100.0)

    # 更换汇总：按类别与原因的合计同步更新
    summary = api.data(api.get(f"{BASE}/summary"))
    assert summary["total_amount"] == pytest.approx(225.0)
    assert summary["pending_price_count"] == 0
    by_category = {row["value"]: row["amount"] for row in summary["by_category"]}
    by_reason = {row["value"]: row["amount"] for row in summary["by_reason"]}
    assert by_category == {"tree": 125.0, "shrub": 100.0}
    assert by_reason == {"dead": 125.0, "aging": 100.0}

    # 总览累计投入
    replacement = _overview_amount(api)
    assert replacement["total_amount"] == pytest.approx(225.0)
    assert replacement["pending_price_count"] == 0

    # 绿地档案更换投入
    statistics = _profile_amount(api, space.id)
    assert statistics["replacement_amount"] == pytest.approx(225.0)


def test_price_fill_same_batch_replay_is_deduplicated(api, make_replacement):
    record = make_replacement(unit_price=None, quantity=10)
    items = [{"id": record.id, "unit_price": 12.5}]

    first = _fill(api, "BATCH-REPLAY", items)
    replay = _fill(api, "BATCH-REPLAY", items)

    assert replay["deduplicated"] is True
    assert replay["applied_count"] == first["applied_count"] == 1
    # 金额只生效一次
    assert _overview_amount(api)["total_amount"] == pytest.approx(125.0)


def test_price_fill_new_batch_skips_priced_records(api, make_replacement):
    record = make_replacement(unit_price=None, quantity=10)
    items = [{"id": record.id, "unit_price": 12.5}]

    _fill(api, "BATCH-A", items)
    again = _fill(api, "BATCH-B", items)

    assert again["applied_count"] == 0
    assert again["skipped_count"] == 1
    assert again["skipped"][0]["id"] == record.id
    # 换批次号重复提交同样不重复生效
    assert _overview_amount(api)["total_amount"] == pytest.approx(125.0)


def test_price_fill_keeps_existing_price_and_amount(api, make_replacement):
    priced = make_replacement(unit_price=50, quantity=2)
    pending = make_replacement(unit_price=None, quantity=3)

    result = _fill(api, "BATCH-MIXED", [
        {"id": priced.id, "unit_price": 999},
        {"id": pending.id, "unit_price": 10},
    ])

    assert result["applied_count"] == 1
    assert result["skipped_count"] == 1
    # 已定价记录不被补价改写
    detail = api.data(api.get(f"{BASE}/{priced.id}"))
    assert detail["unit_price"] == pytest.approx(50.0)
    assert detail["amount"] == pytest.approx(100.0)
    assert _overview_amount(api)["total_amount"] == pytest.approx(130.0)


def test_price_fill_batch_no_conflict_on_different_items(api, make_replacement):
    first = make_replacement(unit_price=None)
    second = make_replacement(unit_price=None)

    _fill(api, "BATCH-CONFLICT", [{"id": first.id, "unit_price": 10}])
    response = api.post(f"{BASE}/price-fill", json={
        "batch_no": "BATCH-CONFLICT",
        "items": [{"id": second.id, "unit_price": 20}],
    })
    assert response.status_code == 409
    # 冲突批次不生效
    assert api.data(api.get(f"{BASE}/{second.id}"))["amount"] is None


@pytest.mark.parametrize("payload,field", [
    ({"items": [{"id": 1, "unit_price": 1}]}, "batch_no"),
    ({"batch_no": "B", "items": []}, "items"),
    ({"batch_no": "B", "items": [{"id": 1, "unit_price": -1}]}, "items.0.unit_price"),
    ({"batch_no": "B", "items": [{"id": 1}]}, "items.0.unit_price"),
    ({"batch_no": "B", "items": [{"id": 1, "unit_price": 1},
                                  {"id": 1, "unit_price": 2}]}, "items.1.id"),
])
def test_price_fill_validation(api, payload, field):
    response = api.post(f"{BASE}/price-fill", json=payload)
    assert response.status_code == 422
    assert field in response.get_json()["data"]


def test_price_fill_unknown_record_fails_whole_batch(api, make_replacement):
    pending = make_replacement(unit_price=None, quantity=5)
    response = api.post(f"{BASE}/price-fill", json={
        "batch_no": "BATCH-MISSING",
        "items": [
            {"id": pending.id, "unit_price": 10},
            {"id": 999999, "unit_price": 20},
        ],
    })
    assert response.status_code == 422
    # 整批不生效：任何一条失败都不落库
    assert api.data(api.get(f"{BASE}/{pending.id}"))["amount"] is None
    assert _overview_amount(api)["total_amount"] == 0


def test_price_pending_filter_and_counts(api, make_replacement):
    make_replacement(unit_price=80)
    make_replacement(unit_price=None)
    make_replacement(unit_price=None)

    items = api.data(api.get(BASE, price_pending="true"))["items"]
    assert len(items) == 2
    assert all(item["amount"] is None for item in items)

    summary = api.data(api.get(f"{BASE}/summary"))
    assert summary["pending_price_count"] == 2
    assert _overview_amount(api)["pending_price_count"] == 2
