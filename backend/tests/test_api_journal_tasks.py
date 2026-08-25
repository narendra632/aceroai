"""REST API for tasks & journal: auth required, CRUD happy paths, cross-user blocked,
domain errors mapped to HTTP."""

from app.services import tasks as tasks_svc


def test_endpoints_require_auth(client):
    assert client.get("/api/tasks").status_code == 401
    assert client.post("/api/tasks", json={"title": "x"}).status_code == 401
    assert client.get("/api/journal").status_code == 401
    assert client.post("/api/journal", json={"content": "x"}).status_code == 401


def test_tasks_crud(auth_client):
    created = auth_client.post("/api/tasks", json={"title": "pay rent", "priority": 1})
    assert created.status_code == 201
    task_id = created.json()["id"]

    listed = auth_client.get("/api/tasks").json()
    assert [t["title"] for t in listed] == ["pay rent"]

    auth_client.patch(f"/api/tasks/{task_id}", json={"notes": "before the 5th"})
    assert auth_client.post(f"/api/tasks/{task_id}/complete").json()["status"] == "done"

    assert auth_client.get("/api/tasks").json() == []  # done drops out of active list
    assert len(auth_client.get("/api/tasks?status=done").json()) == 1

    assert auth_client.delete(f"/api/tasks/{task_id}").status_code == 204


def test_journal_crud(auth_client):
    created = auth_client.post("/api/journal", json={"content": "good day", "mood": 4})
    assert created.status_code == 201
    entry_id = created.json()["id"]

    assert [e["content"] for e in auth_client.get("/api/journal").json()] == ["good day"]
    assert auth_client.patch(f"/api/journal/{entry_id}", json={"mood": 5}).json()["mood"] == 5
    assert auth_client.delete(f"/api/journal/{entry_id}").status_code == 204


def test_cannot_touch_other_users_task(auth_client, db, other_user):
    task = tasks_svc.create_task(db, other_user.id, title="theirs")
    assert auth_client.patch(f"/api/tasks/{task.id}", json={"title": "hijack"}).status_code == 404
    assert auth_client.post(f"/api/tasks/{task.id}/complete").status_code == 404
    assert auth_client.delete(f"/api/tasks/{task.id}").status_code == 404
    # unchanged for the real owner
    assert tasks_svc.get_task(db, other_user.id, task.id).title == "theirs"


def test_domain_errors_map_to_http(auth_client):
    # empty title passes schema (a str) but the service rejects it -> 400
    assert auth_client.post("/api/tasks", json={"title": "   "}).status_code == 400
    # mood out of range is caught by the schema -> 422
    assert auth_client.post("/api/journal", json={"content": "x", "mood": 9}).status_code == 422


# --- briefings can be removed (migration 012) ------------------------------------------


def _briefing(db, user, content="An account of a day."):
    import datetime as dt

    from app.db.models import GeneratedReview

    row = GeneratedReview(
        user_id=user.id,
        kind="daily",
        period_start=dt.datetime.now(dt.UTC),
        period_end=dt.datetime.now(dt.UTC),
        content=content,
        delivered_to=[],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_a_briefing_can_be_removed_and_restored(auth_client, db, user):
    row = _briefing(db, user)
    assert len(auth_client.get("/api/journal/briefings").json()) == 1

    assert auth_client.request("DELETE", f"/api/journal/briefings/{row.id}").status_code == 204
    assert auth_client.get("/api/journal/briefings").json() == []

    assert auth_client.post(f"/api/journal/briefings/{row.id}/restore").status_code == 200
    assert len(auth_client.get("/api/journal/briefings").json()) == 1


def test_another_users_briefing_cannot_be_removed(auth_client, db, user):
    from app.core.security import hash_password
    from app.db.models import User

    from .conftest import OTHER_EMAIL

    other = User(email=OTHER_EMAIL, password_hash=hash_password("x"))
    db.add(other)
    db.commit()
    theirs = _briefing(db, other, content="Not yours.")

    assert auth_client.request("DELETE", f"/api/journal/briefings/{theirs.id}").status_code == 404
