"""绿植更换记录接口测试。"""


def replacement_payload(space_id, **overrides):
    payload = {
        "green_space_id": space_id,
        "plant_name": "红叶石楠",
        "plant_category": "shrub",
        "spec": "冠幅 80-100cm",
        "quantity": 24,
        "unit": "plant",
        "reason": "dead",
        "old_plant_status": "dead",
        "replace_date": "2026-03-16",
        "supplier": "萧山苗木合作社",
        "unit_price": 88.5,
        "operator": "王海涛",
    }
    payload.update(overrides)
    return payload


def test_create_replacement_computes_amount(api, make_space):
    space = make_space()
    data = api.data(api.post("/api/v1/plant-replacements", replacement_payload(space.id)), 201)
    assert data["replacement_no"].startswith("PR-")
    assert data["quantity"] == 24.0
    assert data["amount"] == 2124.0
    assert data["plant_category_label"] == "灌木"
    assert data["reason_label"] == "枯死更换"
    assert data["unit_label"] == "株"


def test_amount_is_empty_without_unit_price(api, make_space):
    space = make_space()
    data = api.data(api.post("/api/v1/plant-replacements",
                             replacement_payload(space.id, unit_price=None)), 201)
    assert data["unit_price"] is None
    assert data["amount"] is None


def test_quantity_and_category_are_validated(api, make_space):
    space = make_space()
    response = api.post("/api/v1/plant-replacements",
                        replacement_payload(space.id, quantity=0, plant_category="bonsai"))
    assert response.status_code == 422
    details = response.get_json()["data"]
    assert "quantity" in details and "plant_category" in details


def test_record_must_belong_to_same_green_space(api, make_record, make_space):
    record = make_record()
    other_space = make_space(name="无关绿地")
    response = api.post("/api/v1/plant-replacements",
                        replacement_payload(other_space.id, maintenance_record_id=record.id))
    assert response.status_code == 422
    assert "不属于所选绿地" in response.get_json()["data"]["maintenance_record_id"]


def test_update_recomputes_amount(api, make_replacement):
    replacement = make_replacement()
    data = api.data(api.put(f"/api/v1/plant-replacements/{replacement.id}", {
        "green_space_id": replacement.green_space_id,
        "plant_name": replacement.plant_name,
        "plant_category": replacement.plant_category,
        "quantity": 50,
        "unit": "plant",
        "reason": replacement.reason,
        "replace_date": "2026-03-20",
        "unit_price": 10,
    }))
    assert data["quantity"] == 50.0
    assert data["amount"] == 500.0
    assert data["replace_date"] == "2026-03-20"


def test_summary_groups_by_category_and_reason(api, make_replacement):
    make_replacement(quantity=10, unit_price=100, plant_category="tree", reason="dead")
    make_replacement(quantity=20, unit_price=50, plant_category="tree", reason="aging")
    make_replacement(quantity=5, unit_price=20, plant_category="shrub", reason="dead")

    data = api.data(api.get("/api/v1/plant-replacements/summary"))
    assert data["total_count"] == 3
    assert data["total_quantity"] == 35.0
    assert data["total_amount"] == 2100.0

    by_category = {item["value"]: item for item in data["by_category"]}
    assert by_category["tree"]["count"] == 2
    assert by_category["tree"]["quantity"] == 30.0
    assert by_category["shrub"]["amount"] == 100.0

    by_reason = {item["value"]: item for item in data["by_reason"]}
    assert by_reason["dead"]["count"] == 2
    assert by_reason["aging"]["quantity"] == 20.0


def test_list_filters_by_green_space_and_reason(api, make_replacement, make_space):
    space = make_space(name="目标绿地")
    make_replacement(space=space, reason="dead")
    make_replacement(space=space, reason="upgrade")
    make_replacement()

    data = api.data(api.get("/api/v1/plant-replacements", green_space_id=space.id,
                            reason="upgrade"))
    assert data["meta"]["total"] == 1
    assert data["items"][0]["reason"] == "upgrade"


def test_delete_replacement(api, make_replacement):
    replacement = make_replacement()
    api.delete(f"/api/v1/plant-replacements/{replacement.id}")
    assert api.get(f"/api/v1/plant-replacements/{replacement.id}").status_code == 404


# ------------------------------------------------------------ 批量补价


def test_price_fill_propagates_to_all_statistics(api, make_replacement, make_space):
    space = make_space(name="补价绿地")
    first = make_replacement(space=space, quantity=10, unit_price=None, reason="dead")
    second = make_replacement(space=space, quantity=4, unit_price=None, reason="upgrade",
                              plant_category="shrub")
    make_replacement(space=space, quantity=1, unit_price=100, reason="dead")

    before = api.data(api.get("/api/v1/plant-replacements/summary"))
    assert before["total_amount"] == 100.0

    result = api.data(api.post("/api/v1/plant-replacements/price-fill", {
        "items": [
            {"id": first.id, "unit_price": 50},
            {"id": second.id, "unit_price": 25.5},
        ],
    }))
    assert result["filled_count"] == 2
    assert result["skipped_count"] == 0
    assert result["filled_amount"] == 602.0  # 10×50 + 4×25.5

    # 明细金额
    detail = api.data(api.get(f"/api/v1/plant-replacements/{first.id}"))
    assert detail["unit_price"] == 50.0
    assert detail["amount"] == 500.0

    # 按植物类别 / 更换原因的合计
    summary = api.data(api.get("/api/v1/plant-replacements/summary"))
    assert summary["total_amount"] == 702.0
    by_category = {item["value"]: item for item in summary["by_category"]}
    assert by_category["tree"]["amount"] == 600.0
    assert by_category["shrub"]["amount"] == 102.0
    by_reason = {item["value"]: item for item in summary["by_reason"]}
    assert by_reason["dead"]["amount"] == 600.0
    assert by_reason["upgrade"]["amount"] == 102.0

    # 总览累计投入
    overview = api.data(api.get("/api/v1/statistics/overview"))
    assert overview["replacement"]["total_amount"] == 702.0

    # 绿地档案更换投入
    archive = api.data(api.get(f"/api/v1/green-spaces/{space.id}/profile"))
    assert archive["statistics"]["replacement_amount"] == 702.0
    archive_reasons = {item["reason"]: item for item in archive["replacement_summary"]}
    assert archive_reasons["upgrade"]["amount"] == 102.0


def test_price_fill_repeat_submission_only_applies_once(api, make_replacement):
    replacement = make_replacement(quantity=10, unit_price=None)
    batch = {"items": [{"id": replacement.id, "unit_price": 88.5}]}

    first = api.data(api.post("/api/v1/plant-replacements/price-fill", batch))
    assert first["filled_count"] == 1
    assert first["filled_amount"] == 885.0

    second = api.data(api.post("/api/v1/plant-replacements/price-fill", batch))
    assert second["filled_count"] == 0
    assert second["filled_amount"] == 0
    assert second["skipped"] == [
        {"id": replacement.id, "replacement_no": replacement.replacement_no,
         "reason": "already_priced"}
    ]

    summary = api.data(api.get("/api/v1/plant-replacements/summary"))
    assert summary["total_amount"] == 885.0  # 没有累加两遍


def test_price_fill_skips_duplicate_unknown_and_priced(api, make_replacement):
    pending = make_replacement(quantity=2, unit_price=None)
    priced = make_replacement(quantity=3, unit_price=10)

    result = api.data(api.post("/api/v1/plant-replacements/price-fill", {
        "items": [
            {"id": pending.id, "unit_price": 30},
            {"id": pending.id, "unit_price": 99},   # 批内重复，只生效第一次
            {"id": priced.id, "unit_price": 50},    # 已有单价
            {"id": 999999, "unit_price": 10},       # 不存在
        ],
    }))
    assert result["filled_count"] == 1
    assert result["filled_amount"] == 60.0
    reasons = [item["reason"] for item in result["skipped"]]
    assert reasons == ["duplicate_in_batch", "already_priced", "not_found"]

    detail = api.data(api.get(f"/api/v1/plant-replacements/{pending.id}"))
    assert detail["amount"] == 60.0
    untouched = api.data(api.get(f"/api/v1/plant-replacements/{priced.id}"))
    assert untouched["unit_price"] == 10.0
    assert untouched["amount"] == 30.0


def test_price_fill_validates_payload(api, make_replacement):
    replacement = make_replacement(unit_price=None)

    response = api.post("/api/v1/plant-replacements/price-fill", {"items": []})
    assert response.status_code == 422

    response = api.post("/api/v1/plant-replacements/price-fill", {
        "items": [{"id": replacement.id, "unit_price": -1}],
    })
    assert response.status_code == 422
    assert "items.0" in response.get_json()["data"]

    response = api.post("/api/v1/plant-replacements/price-fill", {
        "items": [{"id": replacement.id}],
    })
    assert response.status_code == 422

    # 校验失败不产生任何写入
    detail = api.data(api.get(f"/api/v1/plant-replacements/{replacement.id}"))
    assert detail["unit_price"] is None
    assert detail["amount"] is None
