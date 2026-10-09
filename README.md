# Jarvis

Asistente personal en Python.

## Funciones
- **Rutina diaria**: tareas con hora (`jarvis agregar`, `jarvis hoy`, `jarvis hecho`).
- **Informes de visitas médicas**: genera Markdown en `informes/` (`jarvis informe`).
- **Copiloto de visita**: `jarvis visita --grabar` graba, transcribe en local (Whisper) y Claude arma el informe, marcando lo dudoso en «Por verificar». También acepta `--audio` o `--transcripcion`.
- **Consultas en vivo**: `jarvis copiloto --lan` abre una página para el teléfono (mismo Wi-Fi) donde escribes o fotografías un equipo/reactivo y Jarvis responde al momento. Las consultas se añaden solas al informe de `jarvis visita` de ese día.
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

### Copiloto en el teléfono
- `--lan` abre el puerto a tu red Wi-Fi; el enlace lleva un token aleatorio y cambia cada vez. Úsalo solo en redes de confianza (no en el Wi-Fi público del hospital).
- La página usa HTTP, así que el micrófono del navegador no está disponible: usa el dictado del teclado del teléfono.
- Las fotos se reducen y se envían a Claude. Evita fotografiar documentos con tus datos personales.
- Jarvis explica equipos y términos; no da diagnósticos ni sustituye al médico.
