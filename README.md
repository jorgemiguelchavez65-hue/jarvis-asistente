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
teléfono (PWA) ─▶ Firebase Hosting ─▶ Cloud Run (escala a cero) ─▶ API de Claude
                                         ▲   │ Whisper en el contenedor (voz a texto)
                       Cloud Tasks ──────┘   ├─ Firestore (visitas)
                                             └─ Cloud Storage (audio temporal)
```
- La **API key de Claude y la contraseña viven solo en el servidor** (Secret Manager); el teléfono nunca ve la key.
- La voz se transcribe en tu propio servicio (faster-whisper), no en un tercero. A Claude solo llega **texto** (y las fotos que tú tomes con el botón 📷).
- El audio se envía por trozos mientras grabas. Si no hay señal, los trozos quedan guardados en el teléfono y se envían solos cuando vuelva la conexión.
- El informe se genera en una tarea de Cloud Tasks (con reintentos), no durante tu petición, y no hay ninguna instancia encendida esperando.

Despliegue con Firebase, costos y qué está verificado: [docs/DEPLOY.md](docs/DEPLOY.md) (`scripts/deploy_firebase.sh`).

## Estructura
```
src/jarvis/
  web/            servidor (FastAPI), almacenes (local / Firestore), cola (Cloud Tasks) y app del teléfono (web/static)
  ai/             Claude: informe de visita y consultas en vivo
  capture/        voz a texto (Whisper)
  reports/        modelo y formato del informe
  routine/        tareas diarias (CLI)
tests/            pytest + e2e_browser.py (Chromium con micrófono simulado)
Dockerfile
```

## Desarrollo local
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest
python tests/e2e_browser.py     # requiere: pip install playwright y Chromium
# contra el emulador de Firestore (requiere Java y firebase-tools):
firebase emulators:exec --only firestore --project demo-jarvis "pytest tests/test_firestore.py"
# servidor completo (necesita .env, ver .env.example):
pip install -e '.[server]' && jarvis servidor
```
Para probar el micrófono en el teléfono hace falta HTTPS (los navegadores bloquean el micrófono en HTTP), así que la prueba real es en la nube o con un túnel HTTPS.

## Privacidad y consentimiento — léelo antes de usarlo con clientes
- **Pide permiso antes de grabar.** En muchos países grabar a otra persona sin su consentimiento es ilegal. La app te obliga a confirmarlo al crear cada visita.
- **Política de tu empresa.** Si trabajas para una empresa, confirma que puedes enviar conversaciones de clientes a servicios externos (Anthropic, tu proveedor de hosting).
- **Datos de pacientes**: Jarvis tiene instrucciones de omitirlos del informe, pero la transcripción completa se guarda en el servidor hasta que borres la visita (botón «Borrar» en la app). El audio se elimina tras transcribir.
- **Contraseña**: `JARVIS_ACCESS_TOKEN` (en Secret Manager) es la única barrera. Usa una larga (`jarvis token`) y no la compartas. Es un servicio de **un solo usuario**.
- **Revisa siempre «Por verificar»**: el reconocimiento de voz y Claude pueden equivocarse en nombres de equipos, referencias y cifras.

## Límites conocidos
- **Pantalla encendida mientras grabas.** Los navegadores del teléfono pueden detener el micrófono si bloqueas la pantalla o cambias de app. La app mantiene la pantalla encendida y avisa si detecta una interrupción, pero no puede evitarla.
- **iPhone**: la grabación usa el formato del navegador (MP4/AAC). Está contemplado pero no se ha probado en un iPhone real; pruébalo antes de depender de él.
- El informe tarda unos minutos en visitas largas (depende del CPU del servidor y del modelo `JARVIS_WHISPER_MODEL`).
