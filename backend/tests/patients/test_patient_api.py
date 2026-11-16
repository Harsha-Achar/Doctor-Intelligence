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
    assert analytics.json()["banner"] == "Small-cell rule off for synthetic demo data"
