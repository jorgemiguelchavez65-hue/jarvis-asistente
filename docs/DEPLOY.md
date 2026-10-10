# Desplegar Jarvis en Render (plan gratis)

```
teléfono ─▶ Render (servicio web gratuito: la app + la API) ─▶ API de Claude
                │                                          └─▶ servicio de voz a texto (API)
                └─▶ Postgres externo (visitas y audio temporal)
```

## Qué cambia respecto a Google Cloud, y por qué
El plan gratis de Render es muy pequeño (según lo que sé: ~512 MB de RAM, 0.1 CPU) y **no tiene disco permanente**. De eso salen tres decisiones:

| Necesidad | Antes | Ahora | Por qué |
|---|---|---|---|
| Voz a texto | Whisper dentro del servidor | **API externa** (`JARVIS_STT=api`) | Whisper no cabe en 512 MB / 0.1 CPU |
| Guardar visitas | Firestore | **Postgres externo** (Neon, Supabase…) | sin disco permanente, y el Postgres gratis de Render caduca |
| Informe | Cloud Tasks | **hilo en el servidor** + retoma al arrancar | no hay cola; el estado vive en la base de datos |

> **Privacidad — decisión tuya:** con esto, **el audio de la visita sale de tu servidor hacia el proveedor de voz** (antes se transcribía en tu propio servicio). Es lo que hay que ceder para usar el plan gratis. Lee los términos de datos del proveedor que elijas (retención, uso para entrenar) y comprueba que tu empresa lo permite. Si no es aceptable, necesitas una máquina propia con `pip install '.[server]'` y `JARVIS_STT=local`.

## Lo que necesitas (todo con plan gratuito, salvo Claude)
1. **Cuenta en Render** y este repositorio conectado desde GitHub.
2. **Postgres gratis**: crea una base en [Neon](https://neon.tech) (o Supabase) y copia su cadena de conexión (`postgresql://…`). No uses el Postgres gratis de Render: caduca a los 30 días y se borra.
3. **Un servicio de voz compatible con la API de OpenAI.** `render.yaml` viene configurado para **Groq** (`https://api.groq.com/openai/v1`, modelo `whisper-large-v3-turbo`), que tiene nivel gratuito con límites; crea una clave en su consola. Para usar **OpenAI**, cambia `JARVIS_STT_BASE_URL` a `https://api.openai.com/v1` y `JARVIS_STT_MODEL` a `whisper-1` (de pago por minuto). **Comprueba los precios, límites y condiciones vigentes**: no los he podido verificar.
4. **Clave de la API de Claude** (`ANTHROPIC_API_KEY`). Es el único gasto real del sistema y no es gratis.

## Pasos
1. Sube esta rama a GitHub (o únela a `main`). En Render: **New → Blueprint** y elige el repositorio y la rama: leerá `render.yaml`.
2. Render te pedirá los valores que no se guardan en el repositorio:
   - `DATABASE_URL` → la cadena de Neon (debe incluir `sslmode=require`).
   - `JARVIS_STT_API_KEY` → la clave de Groq/OpenAI.
   - `ANTHROPIC_API_KEY` → tu clave de Claude.
3. Espera al despliegue. La **contraseña de la app** la genera Render: está en el servicio → **Environment** → `JARVIS_ACCESS_TOKEN`.
4. Abre `https://jarvis-XXXX.onrender.com` (la URL aparece arriba en el panel del servicio), inicia sesión e instálala:
   **iPhone (Safari)**: Compartir → «Añadir a pantalla de inicio». **Android (Chrome)**: menú → «Instalar app».

## Si creaste el servicio a mano (sin Blueprint)
`render.yaml` **solo se lee con New → Blueprint**. En un servicio creado con **New → Web Service**, Render usa lo que haya en los campos del panel, y nada de `render.yaml` se aplica (ni los comandos ni las variables). Configura esto en el servicio (**Settings**):

| Campo | Valor |
|---|---|
| Language / Runtime | `Python 3` |
| Branch | `main` |
| **Build Command** | `pip install ".[render]"` (equivale a `pip install -r requirements.txt`) |
| **Start Command** | `jarvis-server` |
| Health Check Path | `/healthz` |
| Instance Type | Free |

Y en **Environment**, **las 8 variables a mano** (en un Blueprint 5 vienen ya puestas):

| Variable | Valor |
|---|---|
| `JARVIS_BACKEND` | `postgres` |
| `DATABASE_URL` | cadena de Neon (con `sslmode=require`) |
| `JARVIS_STT` | `api` |
| `JARVIS_STT_BASE_URL` | `https://api.groq.com/openai/v1` |
| `JARVIS_STT_MODEL` | `whisper-large-v3-turbo` |
| `JARVIS_STT_API_KEY` | clave de Groq |
| `ANTHROPIC_API_KEY` | clave de Claude |
| `JARVIS_ACCESS_TOKEN` | una contraseña larga inventada por ti (`jarvis token` genera una) |

Errores típicos:
- **`can't open file '.../app.py'`**: el Start Command es `python app.py` (el valor por defecto de algunos servicios). Ponlo en `jarvis-server`. Desde esta versión, además, existe un `app.py` en la raíz que arranca el servidor, así que ese comando también funciona.
- **`ModuleNotFoundError` (fastapi, psycopg…)**: el Build Command no instaló los extras. Un `poetry install` o un `pip install .` a secas **no** los instalan; usa `pip install ".[render]"`. Render no necesita Poetry ni el `poetry.lock`.
- **«Falta faster-whisper» al generar el informe** (o, en versiones nuevas, el servidor ni arranca con ese mensaje): `JARVIS_STT` no está definida y por defecto vale `local`, que usa Whisper dentro del servidor, algo que el plan gratis no puede. Define `JARVIS_STT=api` junto con `JARVIS_STT_BASE_URL`, `JARVIS_STT_MODEL` y `JARVIS_STT_API_KEY`, guarda (Render redespliega) y pulsa **Reintentar** en la visita: el audio sigue guardado, no hace falta grabar de nuevo.
- **`Faltan variables para JARVIS_STT=api` / `Falta DATABASE_URL`**: faltan variables en Environment (tabla de arriba).
- **El servicio no pasa el health check**: mira **Logs**; casi siempre es una variable faltante.

## Límites del plan gratis que vas a notar
- **El servicio se duerme tras ~15 min sin tráfico y tarda hasta ~1 min en despertar.** **Abre la app 2 minutos antes de entrar a la visita.** Durante una grabación, los trozos de audio (uno cada ~10 s) lo mantienen despierto. La app avisa «Conectando…» mientras despierta.
- **Si cierras la app justo al terminar**, el informe se genera en segundo plano, pero la instancia puede dormirse antes de acabar. No se pierde nada: el estado está en Postgres y **al volver a abrir la app el servicio despierta y retoma el trabajo** pendiente. Para visitas importantes, espera a ver «informe listo».
- **Recursos justos**: cada petición de audio es pequeña (trozos de ~40 KB) y el procesamiento pesado lo hace el proveedor de voz, no tu servidor.
- **Una grabación continua de más de ~90 minutos** supera el límite de archivo habitual de estas APIs (25 MB). Si pasa, la app lo dice; detén la grabación y empieza otra (se suman al mismo informe).
- **Neon gratis** (0.5 GB): el audio ocupa espacio solo hasta transcribirse y luego se borra. La transcripción y el informe de cada visita son texto y pesan poco.

## Estado de verificación
| Pieza | Verificado |
|---|---|
| API, flujo de grabación por trozos, informe, app en Chromium con micrófono simulado | ✅ tests y prueba de navegador |
| Almacén Postgres (concurrencia, toma exclusiva del trabajo, tope de audio, persistencia tras reiniciar) | ✅ contra **PostgreSQL 16 real** |
| Servidor real de punta a punta (Postgres + SDK de Anthropic + transcriptor por API) con servicios falsos por HTTP, **matándolo a mitad del trabajo y reiniciándolo** | ✅ el informe se completa tras el reinicio |
| Transcriptor por API: formato de la petición, reintentos, errores permanentes, archivo demasiado grande | ✅ tests |
| `render.yaml` es YAML válido; la instalación `.[render]` no trae Whisper ni torch | ✅ |
| **Render real, Neon real, Groq/OpenAI real, API real de Claude** (¿acepta mi petición tal cual?) | ❌ **no probado**: aquí no hay acceso a esos servicios |

El primer despliegue es donde puede aparecer algo: la sintaxis exacta de `render.yaml` (Render cambia campos), la versión de Python de Render, o que Groq rechace el formato del audio del teléfono. Si algo falla, los registros del servicio en Render (pestaña **Logs**) dicen qué; pega el error y se corrige.

## Probar antes de usarlo en una visita real
1. Abre la app, crea una visita de prueba, graba 2 minutos hablando de un equipo inventado.
2. Haz una pregunta con foto de cualquier etiqueta.
3. Pulsa «Terminar» y mide cuánto tarda el informe.
4. Prueba también el modo avión unos segundos mientras grabas: el audio debe enviarse solo al volver la señal.
5. Deja la app 20 minutos sin usar y vuelve a abrirla para ver el tiempo de despertar.

## Seguridad
- La app está protegida por una contraseña larga (cabecera `X-Jarvis-Token`; sin ella la API responde 401). Es un servicio de **un solo usuario**.
- Las claves viven como variables de entorno de Render, nunca en el repositorio ni en el teléfono.
- El audio se borra de la base al transcribir. La transcripción y el informe quedan hasta que borres la visita en la app.

## Mantenimiento
- **Actualizar**: haz push a la rama conectada; Render redespliega.
- **Cambiar la contraseña**: edita `JARVIS_ACCESS_TOKEN` en Environment (y vuelve a iniciar sesión en el teléfono).
- **Volver a Google Cloud (Firebase + Cloud Tasks + Firestore)**: ese despliegue está en el commit `cf84c9e` del historial.
