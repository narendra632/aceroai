"""Journal service: CRUD, mood validation, multiple-per-day, user scoping."""

import datetime as dt

import pytest

from app.services import journal as svc
from app.services.errors import Invalid, NotFound


def test_add_and_defaults(db, user):
    entry = svc.add_entry(db, user.id, content="  good day  ", mood=4, tags=["win"])
    assert entry.content == "good day"  # trimmed
    assert entry.mood == 4
    assert entry.tags == ["win"]
    assert entry.channel == "web"
    assert entry.entry_date is not None


def test_content_and_mood_validation(db, user):
    with pytest.raises(Invalid):
        svc.add_entry(db, user.id, content="   ")
    with pytest.raises(Invalid):
        svc.add_entry(db, user.id, content="x", mood=6)


def test_multiple_entries_same_day(db, user):
    today = dt.date.today()
    svc.add_entry(db, user.id, content="one", entry_date=today)
    svc.add_entry(db, user.id, content="two", entry_date=today)
    entries = svc.list_entries(db, user.id)
    assert {e.content for e in entries} == {"one", "two"}


def test_list_is_most_recent_first_and_scoped(db, user, other_user):
    svc.add_entry(db, user.id, content="mine-1")
    svc.add_entry(db, user.id, content="mine-2")
    svc.add_entry(db, other_user.id, content="theirs")

    contents = [e.content for e in svc.list_entries(db, user.id)]
    assert contents == ["mine-2", "mine-1"]  # newest first
    assert "theirs" not in contents


def test_scoping_foreign_entry_is_not_found(db, user, other_user):
    entry = svc.add_entry(db, user.id, content="mine")
    with pytest.raises(NotFound):
        svc.get_entry(db, other_user.id, entry.id)
    with pytest.raises(NotFound):
        svc.delete_entry(db, other_user.id, entry.id)


def test_update_and_delete(db, user):
    entry = svc.add_entry(db, user.id, content="draft")
    updated = svc.update_entry(db, user.id, entry.id, content="final", mood=5)
    assert updated.content == "final"
    assert updated.mood == 5
    svc.delete_entry(db, user.id, entry.id)
    with pytest.raises(NotFound):
        svc.get_entry(db, user.id, entry.id)
