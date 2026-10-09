# Desplegar Jarvis en la nube

Necesitas un servidor con **HTTPS**, **un volumen persistente** y **2 GB de RAM** (el modelo de voz `small` los usa; con `base` bastan 1 GB). La imagen se construye con el `Dockerfile` del repositorio. Los pasos de abajo usan Fly.io como ejemplo; cualquier servicio que ejecute un contenedor con volumen sirve (Railway, Render con disco, un VPS con Caddy…).

> Estos pasos **no se han ejecutado** aún contra un servicio real. Si algún comando ha cambiado, la documentación de tu proveedor manda.

## Reglas que cualquier proveedor debe cumplir
1. **Una sola instancia** (los datos están en un volumen local).
2. **Que no se apague por inactividad** mientras procesa: el informe se genera en segundo plano, sin conexión abierta. Si el proveedor detiene la máquina cuando no hay peticiones, perderás el proceso (la app lo marca como «error» y permite reintentar).
3. El volumen montado en `/data`.

## Ejemplo con Fly.io
```bash
fly launch --no-deploy --name tu-jarvis          # detecta el Dockerfile
fly volumes create jarvis_data --size 3
fly secrets set ANTHROPIC_API_KEY=sk-ant-... JARVIS_ACCESS_TOKEN="$(jarvis token)"
```
Edita el `fly.toml` generado para que incluya:
```toml
[mounts]
  source = "jarvis_data"
  destination = "/data"

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = "off"
  min_machines_running = 1

[[vm]]
  memory = "2gb"
  cpu_kind = "shared"
  cpus = 2
```
```bash
fly deploy
```
Guarda la contraseña que imprimió `jarvis token`: es la que escribirás en la app.

## Instalarla en el teléfono
1. Abre `https://tu-jarvis.fly.dev` en el teléfono e inicia sesión con la contraseña.
2. **iPhone (Safari)**: Compartir → «Añadir a pantalla de inicio». **Android (Chrome)**: menú → «Instalar app».
3. Acepta el permiso de micrófono la primera vez que grabes.

La primera transcripción es lenta: descarga el modelo de voz (queda guardado en el volumen).

## Antes de usarlo en una visita real
Haz una visita de prueba contigo mismo: graba 2 minutos hablando de un equipo inventado, haz una pregunta con foto y revisa el informe. Prueba también con el modo avión durante unos segundos para ver que el audio no se pierde.
