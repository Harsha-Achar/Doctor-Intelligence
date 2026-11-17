def test_patient_routes(client):
    overview = client.get("/api/patients/overview")
    assert overview.status_code == 200
    body = overview.json()
    assert body["patients"] == 30
    assert body["needs_review"] == 3
    listing = client.get("/api/patients")
    assert listing.status_code == 200
    assert listing.json()["total"] == 30
    privacy = client.get("/api/patients/privacy")
    assert privacy.status_code == 200
    analytics = client.get("/api/patients/analytics")
    assert analytics.status_code == 200
    body = analytics.json()
    assert body["banner"] == "Small-cell rule off for synthetic demo data"
    assert body["kpis"]["discontinued"] == 1
    assert body["kpis"]["dispensed"] == 27
    assert body["kpis"]["discontinuation_pct"] == 4
    claims_only = [row for row in body["journeys"] if row["status"] == "Claims only"]
    assert claims_only and all(row["dispensed"] is False for row in claims_only)
    commercial = client.get("/api/patients/analytics", params={"brand": "Brand A", "payer": "Commercial"})
    assert commercial.status_code == 200
    assert commercial.json()["kpis"]["discontinued"] == 1
    medicare = client.get("/api/patients/analytics", params={"payer": "Medicare"})
    assert medicare.status_code == 200
    assert medicare.json()["kpis"]["discontinued"] == 0
