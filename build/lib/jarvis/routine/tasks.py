"""Gestión de la rutina diaria: tareas con hora opcional."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date

from jarvis.storage import JsonStore


@dataclass
class Task:
    id: int
    title: str
    day: str  # ISO: AAAA-MM-DD
    time: str | None = None  # HH:MM
    done: bool = False


@dataclass
class TaskManager:
    store: JsonStore
    tasks: list[Task] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.tasks = [Task(**t) for t in self.store.load([])]

    def _save(self) -> None:
        self.store.save([asdict(t) for t in self.tasks])

    def add(self, title: str, day: date | None = None, time: str | None = None) -> Task:
        next_id = max((t.id for t in self.tasks), default=0) + 1
        task = Task(next_id, title, (day or date.today()).isoformat(), time)
        self.tasks.append(task)
        self._save()
        return task

    def complete(self, task_id: int) -> Task:
        task = self._get(task_id)
        task.done = True
        self._save()
        return task

    def for_day(self, day: date | None = None) -> list[Task]:
        iso = (day or date.today()).isoformat()
        return sorted(
            (t for t in self.tasks if t.day == iso),
            key=lambda t: (t.time is None, t.time or "", t.id),
        )

    def _get(self, task_id: int) -> Task:
        for t in self.tasks:
            if t.id == task_id:
                return t
        raise KeyError(f"No existe la tarea {task_id}")
