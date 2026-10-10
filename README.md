# Jarvis

Asistente personal en Python. Su función principal: **copiloto de visitas** a médicos y laboratorios, desde el teléfono y sin computadora.

## Qué hace
En el teléfono (app web instalable, funciona en iPhone y Android):
1. **Grabas la visita** (con pausa). El audio se guarda en el teléfono mientras grabas, por trozos.
2. **Preguntas en el momento**: escribes o fotografías un equipo/reactivo y Jarvis te explica qué es.
3. **Terminas** y Jarvis transcribe el audio, junta transcripción + notas + consultas y genera el **informe**: resumen, equipos y reactivos tratados, necesidades, compromisos, próximos pasos y una sección «Por verificar» con lo dudoso.
4. Copias, compartes o descargas el informe.

Además, en la línea de comandos: rutina diaria (`jarvis agregar`, `jarvis hoy`, `jarvis hecho`).

## Cómo está armado
```
teléfono (PWA) ─▶ Render (servicio web gratuito) ─▶ API de Claude (consultas e informe)
                        │                       └─▶ API de voz a texto (Groq / OpenAI…)
                        └─▶ Postgres (Neon…): visitas y audio temporal
```
- La **API key de Claude y la contraseña viven solo en el servidor** (variables de entorno de Render); el teléfono nunca ve la key.
- El audio se envía por trozos mientras grabas. Si no hay señal, los trozos quedan guardados en el teléfono y se envían solos cuando vuelva la conexión.
- El informe se genera en segundo plano; el estado vive en Postgres, así que si el servicio gratuito se duerme o se reinicia, **retoma el trabajo pendiente** al volver a arrancar.
- **El audio sale hacia el proveedor de voz** que elijas (el plan gratis no tiene capacidad para transcribir en el propio servidor). Con una máquina propia se puede transcribir en local (`JARVIS_STT=local`, extra `server`).

Despliegue en Render, límites del plan gratis y qué está verificado: [docs/DEPLOY.md](docs/DEPLOY.md).

## Estructura
```
app.py             arranque de compatibilidad (`python app.py` / `uvicorn app:app`)
requirements.txt   instala `.[render]` para hostings que usan `pip install -r`
src/jarvis/
  web/            servidor (FastAPI), almacenes (local / Postgres) y app del teléfono (web/static)
  ai/             Claude: informe de visita y consultas en vivo
  capture/        voz a texto: por API (Render) o Whisper local
  reports/        modelo y formato del informe
  routine/        tareas diarias (CLI)
tests/            pytest + e2e_browser.py (Chromium) + smoke_server.py (servidor real con servicios falsos)
render.yaml       configuración de Render
```

## Desarrollo local
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest
python tests/e2e_browser.py     # requiere: pip install playwright y Chromium
# contra un Postgres real (opcional):
TEST_DATABASE_URL=postgresql://usuario@localhost/base pytest tests/test_postgres.py
# servidor real de punta a punta con servicios falsos (necesita Postgres):
DATABASE_URL=postgresql://usuario@localhost/base python tests/smoke_server.py
```
Para probar el micrófono en el teléfono hace falta HTTPS (los navegadores bloquean el micrófono en HTTP), así que la prueba real es en la nube o con un túnel HTTPS.

## Privacidad y consentimiento — léelo antes de usarlo con clientes
- **Pide permiso antes de grabar.** En muchos países grabar a otra persona sin su consentimiento es ilegal. La app te obliga a confirmarlo al crear cada visita.
- **Política de tu empresa.** Si trabajas para una empresa, confirma que puedes enviar conversaciones de clientes a servicios externos (Anthropic, tu proveedor de hosting).
- **Datos de pacientes**: Jarvis tiene instrucciones de omitirlos del informe, pero la transcripción completa se guarda en el servidor hasta que borres la visita (botón «Borrar» en la app). El audio se elimina tras transcribir.
- **Contraseña**: `JARVIS_ACCESS_TOKEN` (variable de entorno de Render) es la única barrera. Usa una larga (`jarvis token`) y no la compartas. Es un servicio de **un solo usuario**.
- **Revisa siempre «Por verificar»**: el reconocimiento de voz y Claude pueden equivocarse en nombres de equipos, referencias y cifras.

## Límites conocidos
- **Pantalla encendida mientras grabas.** Los navegadores del teléfono pueden detener el micrófono si bloqueas la pantalla o cambias de app. La app mantiene la pantalla encendida y avisa si detecta una interrupción, pero no puede evitarla.
- **iPhone**: la grabación usa el formato del navegador (MP4/AAC). Está contemplado pero no se ha probado en un iPhone real; pruébalo antes de depender de él.
- **El plan gratis de Render se duerme** tras ~15 min sin uso y tarda hasta ~1 min en despertar: abre la app antes de la visita.
- El informe tarda unos minutos en visitas largas.
