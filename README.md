# Sistema de monitoreo de mesas en restaurante con visión por computadora

Proyecto de curso (Construcción de Software, UNEMI) basado en el artículo indexado
en Scopus *"Real-Time Table Availability Detection in Dynamic Dining Environments
Using YOLOv8 and Geometric Overlap Analysis"* (Risaldi et al., PETI, vol. 32, 2026,
DOI 10.46604/peti.2026.15704).

## Contexto real

Se aplica a un restaurante real de encebollados/picantería cerca de la universidad,
con acceso confirmado a sus cámaras de seguridad (feed en vivo y grabaciones). En
este negocio el cliente pide y paga en caja, elige mesa libremente, y el personal
lleva el pedido — no hay atención de mesa tradicional ni uniforme distintivo.
Restricción dura del proyecto: **no hay ninguna interacción en vivo del personal
con apps** — todo debe resolverse solo con análisis de video.

## Las 3 métricas obligatorias

El profesor exige que el sistema entregue, como mínimo:

1. **Temporizador de tiempo de espera por mesa** — `GET /api/metricas/tiempo-espera/`
2. **Qué empleado atiende más mesas** — `GET /api/metricas/empleados/`
3. **Qué mesas se usan más y cuáles menos** — `GET /api/metricas/uso-mesas/`

Las tres se calculan agregando sobre el modelo de datos descrito abajo; no requieren
tablas nuevas, solo `Count`/`Avg`/`Max` sobre `EventoOcupacion` y `EventoEntrega`.

## Arquitectura

```
restaurante_api/        Proyecto Django (settings, urls raíz)
monitoreo/               App Django + DRF: modelo de datos, API REST, métricas
requirements.txt         Dependencias de la API (Django + DRF + driver Postgres)
.env.example              Variables de entorno (dev y AWS)
```

El **microservicio de visión** (OpenCV + YOLOv8 + DeepSORT) vive en su **propio
repositorio**, independiente de este. Los dos componentes se comunican solo por
HTTP/JSON: el microservicio de visión nunca toca la base de datos directamente,
siempre reporta a través de la API REST de este repo. Esto respeta la arquitectura
de microservicios pedida y permite correr el microservicio de visión en una máquina
distinta (ej. un mini-PC junto a las cámaras) apuntando a la API en EC2.

Conexión entre repos en desarrollo:

1. Este repo (API): `python manage.py runserver` (puerto 8000).
2. Repo del microservicio: `.env` con `RESTAURANTE_API_URL=http://localhost:8000/api`.
3. Correr el pipeline del microservicio sobre una grabación y ver los registros en
   `GET /api/ocupaciones/` de esta API.

### Modelo de datos (`monitoreo/models.py`)

- **Mesa** — mesa física + su zona fija (polígono) en el video de una cámara,
  capacidad, y mesas adyacentes (para la heurística de fusión).
- **Personal** — persona del staff identificada solo por un `codigo_tracking`
  persistente (re-identificación por apariencia vía DeepSORT), nunca por nombre
  real ni apariencia manual.
- **EventoOcupacion** — ciclo de vida de una mesa ocupada: inicio, fin, cantidad
  de personas, confianza de detección, posible fusión con otra mesa, y
  `clip_s3_key` (referencia al clip de evidencia en S3; `clip_s3_url` es la URL
  pública derivada, solo lectura).
- **EventoEntrega** — cada entrega individual dentro de una ocupación (aperitivo,
  bebida, plato principal, cuenta), con su propio tiempo de espera respecto al
  inicio de la ocupación. El pedido no siempre llega junto, así que el promedio
  de espera de una ocupación se calcula sobre **todas** sus entregas
  (`EventoOcupacion.tiempo_espera_promedio_segundos`).

### Decisiones de diseño clave

> Los módulos mencionados (`occupancy_engine`, `geometry`, `staff_heuristic`,
> `table_fusion`, `clip_recorder`, `evidence_storage`) viven en el **repo del
> microservicio de visión**; se documentan aquí porque definen el comportamiento
> que esta API registra.

- **Ocupación por zona fija + overlap geométrico + período de gracia**
  (microservicio de visión, `occupancy_engine.py`, `geometry.py`): una mesa no se marca
  libre ni ocupada al primer frame — se exige presencia/ausencia sostenida por
  un período de gracia configurable (`mesas_zonas.json`,
  `periodo_gracia_segundos`, default 45s) para no confundir una ausencia
  temporal (baño, caja) con mesa libre, ni a alguien que solo pasa cerca con
  una mesa ocupada.
- **Timeout específico para objetos abandonados sin persona**
  (`occupancy_engine.py`, parámetro `timeout_objeto_abandonado_segundos`,
  default **120s**): el pipeline distingue personas (tracks) de objetos
  (mochila, bolso, vaso, botella, plato) al calcular el overlap. Reglas:
  - Un objeto solo **nunca abre** una ocupación: la gracia de apertura la tiene
    que iniciar una persona. Así los platos sucios que quedan después de que
    el cliente se va no generan ocupaciones fantasma en bucle.
  - Si el cliente deja sus cosas y va a la caja antes de que se cumpla la
    gracia, el objeto sí sostiene la apertura (flujo normal de este negocio).
  - Con la mesa ocupada, si desaparecen las personas pero quedan objetos, se
    libera pasado `timeout_objeto_abandonado_segundos` (no el período de
    gracia normal). Si vuelve una persona, se cancela la liberación.
  - El default (120s) se eligió **más largo** que la gracia (45s) a propósito:
    en este local el cliente va a la caja a pedir/pagar dejando sus cosas, o el
    plato llega mientras está en el baño; un plazo muy corto partiría esas
    ocupaciones en dos. Es un parámetro del JSON: bajarlo si en la práctica
    las mesas con platos sucios quedan "ocupadas" demasiado tiempo.
  - El evento de cierre lleva `motivo` (`ausencia_persona` u
    `objeto_abandonado`) para logs y depuración.
- **Personal identificado por comportamiento** (microservicio: `staff_heuristic.py`):
  un track se clasifica como staff si visita varias mesas distintas en poco tiempo
  sin quedarse sentado (dwell time bajo), no por apariencia ni nombre.
- **Fusión de mesas por heurística** (microservicio: `table_fusion.py`): mesas
  adyacentes ocupadas a la vez + personas detectadas por encima de la suma de
  capacidades se reportan como una fusión (`EventoOcupacion.fusionada_con`), para
  no inflar las métricas de uso de cada mesa por separado.
- **Entregas como eventos múltiples** (`EventoEntrega`): modelo que acepta que
  no siempre hay aperitivo previo ni que todo el pedido llega junto.
- **Evidencia en S3 por ocupación** (microservicio: `clip_recorder.py`,
  `evidence_storage.py`): ver sección más abajo.

## Instalación

```bash
python -m venv .venv && source .venv/bin/activate   # fish: source .venv/bin/activate.fish
pip install -r requirements.txt
cp .env.example .env    # se carga automáticamente (python-dotenv) en la API
```

Este repo solo contiene la API; las dependencias pesadas del microservicio de
visión (`ultralytics`, `deep-sort-realtime`, `opencv-python`) van en su repo.

## Cómo correr la API (desarrollo)

```bash
python manage.py migrate
python manage.py createsuperuser   # opcional, para /admin/
python manage.py runserver
```

Endpoints CRUD disponibles bajo `/api/`: `mesas/`, `personal/`, `ocupaciones/`,
`entregas/`; y los 3 endpoints de métricas listados arriba.

## Calibración de zonas de mesa con video real

Ver el **repo del microservicio de visión** (`vision_service/calibracion.py`).
Resumen: `mesas_zonas.json` trae coordenadas de **ejemplo**; la config real se
genera marcando las mesas sobre un frame de la cámara del local:

```bash
# desde una grabación (o una imagen png/jpg, o el índice de una cámara en vivo, ej. 0)
python -m vision_service.calibracion grabaciones/salon-2026-09-10.mp4 \
    --camara-id cam-1-salon-principal \
    --salida vision_service/config/mesas_zonas.json
```

Consideraciones:

- **`mesa_id` debe coincidir con el `id` de la `Mesa` en la API Django**
  (`GET /api/mesas/`), porque el pipeline reporta ocupaciones por ese id. Crear
  primero las mesas en `/admin/` o vía `POST /api/mesas/` y usar esos ids al
  calibrar (podés pegar el mismo polígono en `Mesa.zona_poligono`).
- Los polígonos están en píxeles del frame a la resolución con la que se
  calibró; si se cambia la resolución de la cámara hay que recalibrar.
- Los `parametros` (gracia, timeout de objeto, umbrales de overlap) se analizan
  en la sección "Decisiones de diseño clave" de arriba y se ajustan en el JSON
  del microservicio.

## Cómo correr el microservicio de visión

El microservicio vive en su propio repo (ver "Arquitectura"). Resumen del uso:

```bash
export RESTAURANTE_API_URL=http://localhost:8000/api   # o en .env del microservicio
python -m vision_service.pipeline ruta/a/grabacion.mp4
# o con cámara en vivo:
python -m vision_service.pipeline 0
# opciones: --config otra.json  --fps-muestreo 2  --sin-evidencia
```

`detector.py` (YOLOv8) y `tracker.py` (DeepSORT/SORT) importan sus dependencias
pesadas de forma perezosa, así que el resto del paquete se puede testear sin
GPU/torch instalados — ver los tests en el repo del microservicio.

## Evidencia: clips a S3 por EventoOcupacion

Al **cerrarse** cada ocupación el pipeline sube a S3 un clip de video de esa
ocupación y guarda la key en `EventoOcupacion.clip_s3_key` (vía
`PATCH /api/ocupaciones/<id>/`). Se hace al cierre porque recién ahí el clip
cubre la ocupación completa.

Cómo funciona (en el repo del microservicio: `clip_recorder.py`,
`evidence_storage.py`):

- Por cada mesa se mantiene un buffer circular (**pre-roll**) con los últimos
  frames sampleados, recortados a la zona de la mesa. Como la apertura se
  confirma `periodo_gracia` segundos después de la llegada, el pre-roll permite
  que el clip empiece cuando el cliente llegó realmente.
- Al confirmarse la apertura se abre un MP4 temporal en disco y se le agrega
  cada frame sampleado (no se acumula en memoria: una ocupación puede durar más
  de una hora). Al cierre se finaliza, se sube a S3 y se borra el temporal.
- Decisiones tomadas (simples, documentadas aquí):
  - **Formato**: MP4 (codec `mp4v` de OpenCV), un archivo por ocupación.
  - **Recorte**: solo la zona de la mesa + margen de 40 px (archivos chicos y
    evidencia ligada a esa mesa; el margen deja ver al personal acercándose).
  - **FPS del clip** = FPS de muestreo del pipeline (2 por defecto), así el clip
    reproduce el tiempo real.
  - **Tope** de 20 000 frames por clip (≈2,7 h a 2 fps); si se supera se
    conserva el inicio y se registra un warning.
  - **Estructura en el bucket**:
    `evidencia/<camara_id>/mesa-<mesa_id>/<YYYY>/<MM>/<DD>/ocupacion-<YYYYMMDDTHHMMSS>.mp4`
    (navegable por cámara, mesa y fecha; la key es reproducible desde los
    datos del evento).
  - La subida es síncrona (unos segundos por clip) y **nunca tumba el
    monitoreo**: si falla, se loguea y la ocupación queda sin clip.
- Variables de entorno (ver `.env.example`):

| Variable                    | Uso                                                                                   |
|-----------------------------|---------------------------------------------------------------------------------------|
| `AWS_STORAGE_BUCKET_NAME`   | bucket destino. **Vacío = evidencia deshabilitada** (el pipeline sigue funcionando).  |
| `AWS_S3_REGION_NAME`        | región (default `us-east-1`); la API la usa para armar `clip_s3_url`.                 |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | credenciales para boto3 (o rol IAM de la EC2, o `~/.aws/credentials`). |
| `EVIDENCIA_PREFIJO_S3`      | prefijo raíz de las keys (default `evidencia`).                                       |
| `EVIDENCIA_DIR_LOCAL`       | carpeta temporal para el MP4 en curso (default `<tmp>/evidencia_clips`).             |
| `EVIDENCIA_CONSERVAR_LOCAL` | `1` para no borrar el MP4 tras subirlo, o para grabar en local sin bucket S3.        |

La API expone `clip_s3_key` y `clip_s3_url` en `GET /api/ocupaciones/` y en el
admin. Para un bucket privado, reemplazar `clip_s3_url` por URLs prefirmadas es
un cambio local en `EventoOcupacion.clip_s3_url`.

## Tests

```bash
# API Django (8 tests: métricas + evidencia)
python manage.py test monitoreo
```

> Los tests del microservicio de visión se corren en su repo
> (`python -m unittest discover -s vision_service/tests -t .`).

## Despliegue en AWS (según stack definido)

- **EC2**: corre la API Django (gunicorn). El **microservicio de visión** corre
  en su propio repo y máquina (mini-PC junto a las cámaras, o una EC2 aparte si el
  hardware alcanza para inferencia en tiempo real); solo necesita salida a
  internet para hablar con la API y con S3.
- **RDS (Postgres)**: base de datos de producción — configurar `RDS_*` en `.env`
  (ver `.env.example`); si esas variables no están, `settings.py` usa sqlite
  local para desarrollo. Aplicar `python manage.py migrate` (incluye la
  migración `0002` que agrega `clip_s3_key`).
- **S3**: bucket para los clips de evidencia. El microservicio de visión
  necesita permiso `s3:PutObject` sobre `<bucket>/<prefijo>/*`; la API solo
  necesita el nombre del bucket y la región para construir las URLs.

## Estado del proyecto

- Serializers/views de DRF y las 3 métricas: **hechos** (`monitoreo/`).
- Microservicio de visión (zonas + gracia, staff por comportamiento, fusión de
  mesas): **hecho** y testeado — en su repo independiente.
- Calibración de zonas con video real: **hecha** (`calibracion.py` en el repo del
  microservicio); falta correrla sobre las grabaciones del local y ajustar umbrales.
- Timeout de objetos abandonados sin persona: **hecho** (`occupancy_engine.py`,
  `timeout_objeto_abandonado_segundos`).
- Clips de evidencia a S3 por `EventoOcupacion`: **hecho**
  (`clip_recorder.py`, `evidence_storage.py`, campo `clip_s3_key`).
- Pendiente: detección de entregas (`EventoEntrega`) y asociación al `Personal`
  desde el pipeline (hoy la API y el cliente ya lo soportan:
  `ApiClient.reportar_entrega`, `ClasificadorStaff`), y validar los umbrales
  con video real.
