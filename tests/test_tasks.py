from datetime import date

from jarvis.routine import TaskManager
from jarvis.storage import JsonStore


def test_add_complete_and_persist(tmp_path):
    path = tmp_path / "t.json"
    tm = TaskManager(JsonStore(path))
    tm.add("Desayuno", date(2026, 1, 1), "08:00")
    tm.add("Sin hora", date(2026, 1, 1))
    tm.complete(1)

    reloaded = TaskManager(JsonStore(path))
    day = reloaded.for_day(date(2026, 1, 1))
    assert [t.title for t in day] == ["Desayuno", "Sin hora"]
    assert day[0].done and not day[1].done
