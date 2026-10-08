from collectors import sam


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def test_sam_entity_fetch_uses_public_sections_header_and_rate_safe_batches(monkeypatch):
    calls = []

    def fake_get(url, params, headers):
        calls.append((url, params, headers))
        return FakeResponse({"entityData": []})

    monkeypatch.setattr(sam, "get", fake_get)
    monkeypatch.setenv("MOCO_SAM_MAX_REQUESTS", "2")
    sam.fetch_entities([f"UEI{i:09d}" for i in range(25)], api_key="secret")
    assert len(calls) == 2
    assert all(len(params["ueiSAM"].split("~")) == 10 for _, params, _ in calls)
    assert all(params["size"] == 10 for _, params, _ in calls)
    assert all(params["includeSections"] == "entityRegistration,pointsOfContact" for _, params, _ in calls)
    assert all(headers["X-Api-Key"] == "secret" for _, _, headers in calls)
    assert all("api_key" not in params for _, params, _ in calls)
