# Desplegar Jarvis con Firebase (sin costos fijos de cómputo)

```
teléfono ─▶ Firebase Hosting (la app)
                │  /api/**
                ▼
           Cloud Run "jarvis"  ── escala a CERO: no hay instancia encendida cuando no lo usas
             │    ▲   │
             │    │   └─▶ API de Claude
  encola     │    │ llama a /internal/process/<visita> con un token firmado
             ▼    │
           Cloud Tasks (cola "jarvis-process": 5 intentos, espera creciente)

  Visitas ─▶ Firestore          Audio (temporal) ─▶ Cloud Storage       Claves ─▶ Secret Manager
```

**Qué pasa en una visita:** mientras grabas, el teléfono envía trozos de audio al servicio (se guardan en Cloud Storage). Al terminar, `finish` solo **encola una tarea** y responde al instante. Cloud Tasks despierta el servicio, que transcribe, genera el informe con Claude, lo guarda en Firestore y borra el audio. Si falla, Cloud Tasks reintenta; si agota los intentos, la visita queda en «error» con el motivo y un botón **Reintentar**.

## Una aclaración importante
Cloud Tasks y Firestore **no reemplazan a Cloud Run**: Cloud Tasks solo encola trabajos y Firestore solo guarda datos; algo tiene que ejecutar el código. Lo que elimina el costo fijo es usar Cloud Run **sin instancia mínima** (la versión anterior mantenía una siempre encendida), con Cloud Tasks para que el informe se genere dentro de una petición en vez de en un hilo de fondo.

## Costos: qué esperar
- **No hay cómputo encendido**: Cloud Run cobra solo mientras atiende peticiones. Durante una visita, los trozos de audio (uno cada ~10 s) mantienen una instancia activa brevemente, y luego se suma la transcripción. Sigue siendo un costo **por uso**, no fijo.
- **Casi nada fijo**: la imagen de contenedor ocupa espacio en Artifact Registry y los secretos tienen una tarifa mínima. Son centavos, pero no es cero.
- Hosting, Firestore, Cloud Storage, Cloud Tasks y Cloud Run tienen cuotas gratuitas; con un solo usuario suele bastar, pero **consulta los precios y cuotas vigentes** y pon una **alerta de presupuesto** en la consola de facturación.
- El gasto principal real es la **API de Claude**, que no depende de Firebase.

## Pasos
1. Crea un proyecto en la [consola de Firebase](https://console.firebase.google.com) y activa el plan Blaze (facturación; sin él no se puede usar Cloud Run).
2. Instala y autentica las herramientas:
   ```bash
   gcloud auth login
   npm install -g firebase-tools && firebase login
   ```
3. Desde la raíz del repositorio:
   ```bash
   scripts/deploy_firebase.sh ID_DE_TU_PROYECTO
   ```
   Habilita las APIs, crea Firestore, el bucket y la cola, guarda los secretos, da permisos, despliega Cloud Run y luego Hosting. Te pedirá la `ANTHROPIC_API_KEY` y **mostrará una sola vez la contraseña de la app**: guárdala.
4. Abre `https://ID_DE_TU_PROYECTO.web.app` en el teléfono, inicia sesión e instálala:
   **iPhone (Safari)**: Compartir → «Añadir a pantalla de inicio». **Android (Chrome)**: menú → «Instalar app».

## Estado de verificación
| Pieza | Verificado |
|---|---|
| App, API, flujo de grabación por trozos, informe | ✅ tests + navegador con micrófono simulado |
| Almacén en Firestore (CRUD, concurrencia, toma exclusiva del trabajo) | ✅ contra el **emulador oficial** de Firestore |
| Reintentos de Cloud Tasks (fallo → 500 → reintento; último intento → error; tarea duplicada; token) | ✅ tests con la cola simulada |
| Solicitud que se envía a Cloud Tasks (URL, token OIDC, plazo) | ✅ comprobada contra un cliente simulado |
| Nombres de comandos y banderas de `gcloud` del script | ✅ comprobados con la ayuda de `gcloud` instalada |
| Cloud Storage real, Cloud Tasks real, token OIDC real, Cloud Run, Hosting, la imagen Docker | ❌ **no probado**: no hay acceso a Google Cloud aquí ni daemon de Docker |

Lo que queda sin probar es justo la parte que solo se comprueba desplegando. Los puntos con más riesgo de fallar la primera vez: permisos de IAM (el script los otorga, pero Google puede exigir alguno más), la URL del servicio usada como destino y audiencia del token, y los tiempos de transcripción (abajo). Si algo falla, los registros de Cloud Run (`gcloud run services logs read jarvis --region REGION`) dicen qué; pega el error y se corrige.

## Tiempos: lo primero que debes medir
- **Cloud Tasks admite como máximo 30 minutos por intento.** Si transcribir una visita larga tarda más, el intento se corta y se reintenta (hasta 5 veces) sin terminar nunca. No sé cuánto tarda el modelo `small` con 4 CPU en Cloud Run; **mide con una grabación de 10 minutos** antes de confiar en visitas de una hora. Si va lento, cambia `ARG WHISPER_MODEL=small` por `base` en el `Dockerfile` (más rápido, algo menos preciso con términos técnicos) y vuelve a desplegar.
- **Arranque en frío**: tras un rato sin uso, la primera petición tarda unos segundos más (arranca el contenedor). Los trozos de audio se reintentan solos, así que no se pierde nada.
- Una visita en cola o procesando más de 90 minutos se muestra como error para que no quede colgada.

## Seguridad
- **`--allow-unauthenticated`**: Hosting necesita llamar al servicio. La app está protegida por la contraseña (cabecera `X-Jarvis-Token`; sin ella, 401). `/internal/process` exige además el token OIDC de Cloud Tasks de esa cuenta de servicio específica.
- Firestore tiene reglas que **niegan todo acceso directo** desde navegadores (`firestore.rules`); solo el servidor accede.
- El audio se borra tras transcribir, y una regla del bucket borra cualquier resto a los 2 días. La transcripción y el informe quedan en Firestore hasta que borres la visita en la app.
- Es un servicio de **un solo usuario**: una contraseña compartida, sin cuentas.

## Mantenimiento
- **Actualizar**: vuelve a ejecutar `scripts/deploy_firebase.sh ID_DE_TU_PROYECTO`.
- **Cambiar la contraseña**: `printf %s "NUEVA" | gcloud secrets versions add jarvis-token --data-file=-` y vuelve a desplegar.
- **Ver la cola**: `gcloud tasks queues describe jarvis-process --location REGION`.
- **Región**: `us-central1` por defecto; si usas otra, cámbiala en `firebase.json` y exporta `REGION=...` al correr el script.
