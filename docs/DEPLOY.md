# Desplegar Jarvis con Firebase

```
teléfono ─▶ Firebase Hosting (app, HTTPS, CDN)
                 │  /api/**  (reescritura)
                 ▼
            Cloud Run "jarvis" ─▶ API de Claude
                 │   └─ Whisper (voz a texto) dentro del contenedor
                 ▼
            Cloud Storage (bucket montado en /data: visitas y audio)
            Secret Manager (ANTHROPIC_API_KEY y contraseña de la app)
```
Firebase Hosting sirve la app; todo lo que tiene lógica corre en Cloud Run, que es como Firebase ejecuta contenedores. Por eso hace falta un **proyecto de Firebase en el plan Blaze** (con facturación).

> **Estado:** estos archivos (`firebase.json`, `Dockerfile`, `scripts/deploy_firebase.sh`) **no se han ejecutado contra un proyecto real**; no había acceso a Google Cloud al escribirlos. Lo que sí está probado es la aplicación (tests y un navegador con micrófono simulado). Si un comando falla, pega aquí el error y se corrige.

## Pasos
1. Crea un proyecto en la [consola de Firebase](https://console.firebase.google.com) y activa el plan Blaze.
2. Instala y autentica las dos herramientas:
   ```bash
   gcloud auth login
   npm install -g firebase-tools && firebase login
   ```
3. Desde la raíz del repositorio:
   ```bash
   scripts/deploy_firebase.sh ID_DE_TU_PROYECTO
   ```
   El script habilita las APIs, crea el bucket y los secretos, da permisos, despliega Cloud Run y luego Hosting. Te pedirá la `ANTHROPIC_API_KEY` y **mostrará una sola vez la contraseña de la app**: guárdala.
4. Abre `https://ID_DE_TU_PROYECTO.web.app` en el teléfono, inicia sesión e instálala:
   **iPhone (Safari)**: Compartir → «Añadir a pantalla de inicio». **Android (Chrome)**: menú → «Instalar app».

La primera construcción tarda varios minutos (descarga el modelo de voz y lo guarda dentro de la imagen).

## Por qué está configurado así
- **Una instancia, siempre encendida, con CPU permanente** (`--min-instances 1 --max-instances 1 --no-cpu-throttling`): el informe se genera en segundo plano después de responder a la app. Con el comportamiento por defecto de Cloud Run (CPU solo durante las peticiones) ese proceso se congelaría. **Esto tiene un costo continuo** aunque no uses la app: revisa los precios de Cloud Run antes de dejarlo activo.
- **Bucket montado en `/data`**: Cloud Run no tiene disco permanente, y así el código guarda visitas y audio igual que en local. Es un sistema de archivos sobre Cloud Storage, no un disco: sirve para este volumen de datos con un solo usuario, no para mucha concurrencia.
- **Audio por trozos mientras grabas**: Firebase Hosting corta las peticiones a los 60 s, y subir un audio entero al final, con mala señal, podría pasarse. Por eso el teléfono envía trozos de ~10 s durante la grabación y al terminar solo falta enviar lo último.
- **`--allow-unauthenticated`**: Hosting necesita poder llamar al servicio. La protección es la contraseña de la app (cabecera `X-Jarvis-Token`); sin ella la API responde 401. Los datos no son públicos, pero **la URL de Cloud Run sí es alcanzable**, así que usa una contraseña larga.
- **Región**: `us-central1` por defecto. Si usas otra, cámbiala en `firebase.json` y exporta `REGION=...` al correr el script. Elige una región cercana a ti por latencia.

## Verificar
```bash
curl -s https://ID_DE_TU_PROYECTO.web.app/api/ping -H "X-Jarvis-Token: TU_CONTRASEÑA"   # {"ok":true}
curl -s -o /dev/null -w "%{http_code}\n" https://ID_DE_TU_PROYECTO.web.app/api/visits     # 401
```
Después haz una visita de prueba contigo mismo: graba 2 minutos hablando de un equipo inventado, haz una pregunta con foto y revisa el informe. Prueba también el modo avión unos segundos mientras grabas: el audio debe enviarse solo al volver la señal.

## Mantenimiento
- **Actualizar**: vuelve a ejecutar `scripts/deploy_firebase.sh ID_DE_TU_PROYECTO`.
- **Cambiar la contraseña**: `printf %s "NUEVA" | gcloud secrets versions add jarvis-token --data-file=-` y vuelve a desplegar.
- **Borrar datos**: botón «Borrar» en cada visita, o vaciar el bucket `ID_DE_TU_PROYECTO-jarvis-data`.
- **Costo y datos**: el audio se borra tras transcribir, pero la transcripción y el informe quedan en el bucket hasta que borres la visita.
