# Jarvis

Asistente personal en Python.

## Funciones
- **Rutina diaria**: tareas con hora (`jarvis agregar`, `jarvis hoy`, `jarvis hecho`).
- **Informes de visitas médicas**: genera Markdown en `informes/` (`jarvis informe`).
- **Copiloto de visita**: `jarvis visita --grabar` graba, transcribe en local (Whisper) y Claude arma el informe, marcando lo dudoso en «Por verificar». También acepta `--audio` o `--transcripcion`.
- **Claude**: `jarvis preguntar "..."` — requiere `ANTHROPIC_API_KEY`.

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
pip install -e '.[dev]'          # extras: ai (Claude), audio (grabar y transcribir)
pytest
jarvis agregar "Tomar medicación" --hora 08:00
jarvis hoy
jarvis informe --medico "Dra. Pérez" --especialidad Cardiología --motivo Control
```

`data/` e `informes/` están en `.gitignore` porque contienen datos personales y médicos.

## Privacidad y consentimiento
- Pide siempre permiso al médico antes de grabar; en muchos países es obligatorio. `--grabar` lo pregunta.
- El audio se transcribe en tu equipo y se borra al terminar (salvo `--conservar-audio`).
- Solo el **texto** de la transcripción se envía a la API de Claude. Revisa la política de datos de tu cuenta de Anthropic antes de usarlo con información médica real.
- Claude puede equivocarse con dosis o nombres de fármacos: revisa siempre la sección «Por verificar».
