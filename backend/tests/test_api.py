import io
import zipfile

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_upload_edit_export(legacy_pbix):
    r = client.post("/api/upload", files={"file": ("sales.pbix", legacy_pbix)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["format"] == "legacy" and body["hasSecurityBindings"]
    assert body["model"]["tables"][0]["name"] == "Sales"
    sid, pages = body["session"], body["report"]["pages"]

    pages[0]["visuals"][0]["x"] = 640
    r = client.post(f"/api/session/{sid}/export", json={"pages": pages})
    assert r.status_code == 200
    assert 'filename="sales-edited.pbix"' in r.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert "DataModel" in z.namelist() and "SecurityBindings" not in z.namelist()

    r = client.post(f"/api/session/{sid}/preview", json={"fields": [
        {"role": "Values", "kind": "measure", "table": "Sales", "name": "Total Sales"}]})
    assert r.json()["data"]["value"] == 5550.5


def test_rejects_non_pbix():
    r = client.post("/api/upload", files={"file": ("x.pbix", b"not a zip")})
    assert r.status_code == 400
    r = client.post("/api/upload", files={"file": ("x.txt", b"hi")})
    assert r.status_code == 400


def test_expired_session():
    assert client.post("/api/session/nope/export", json={"pages": []}).status_code == 404
