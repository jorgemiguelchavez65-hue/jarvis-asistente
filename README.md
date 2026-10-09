# Jarvis

Asistente personal en Python.

## Funciones
- **Rutina diaria**: tareas con hora (`jarvis agregar`, `jarvis hoy`, `jarvis hecho`).
- **Informes de visitas médicas**: genera Markdown en `informes/` (`jarvis informe`).
- **Claude (fase 2)**: `jarvis preguntar "..."` — requiere `ANTHROPIC_API_KEY`.

## Estructura
```
src/jarvis/
  cli.py          comandos
  config.py       rutas y variables de entorno
  storage.py      persistencia JSON
  routine/        tareas y rutina
  reports/        informes médicos
  ai/             cliente de Claude
tests/
data/             datos locales (ignorado por git)
```

## Inicio rápido
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'          # añade ',ai' para Claude
pytest
jarvis agregar "Tomar medicación" --hora 08:00
jarvis hoy
jarvis informe --medico "Dra. Pérez" --especialidad Cardiología --motivo Control
```

`data/` e `informes/` están en `.gitignore` porque contienen datos personales y médicos.
