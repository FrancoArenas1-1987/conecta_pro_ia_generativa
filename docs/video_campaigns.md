# Campañas publicitarias de video

El publicador combina la biblioteca habitual de imágenes con campañas de video aprobadas. Se ejecuta con el mismo temporizador, bloqueo y guardias de horario, intervalo y antispam.

- `campaign_queue.py`: selección, aprobación, checksums, cadencia y registro durable por destino.
- `run_instagram_autopublish_once.py`: integración con el trabajo existente.
- `campaign_status.py`: inspección de solo lectura, sin contactar proveedores.
- `create_campaign_ad.py` y `create_library_ads.py`: montaje local de las piezas a partir de imágenes existentes; no publican.
- `validate_campaign_ads.py`: decodificación y controles técnicos de los archivos.
- `test_campaign_queue.py`: pruebas de concurrencia, alternancia, recuperación y guardias del runner.

## Configuración y recuperación

`config/campaigns.library.json` contiene los captions, rutas relativas, hashes y URL HTTPS de los tres anuncios aprobados. Su interruptor global está deshabilitado para que restaurar el repositorio no publique ni repita campañas sin recuperar el estado.

1. Preparar `OUTPUT_ROOT/instagram/campaigns/` y recuperar sus archivos MP4/portadas desde un respaldo privado. Las URL públicas permiten recuperar los MP4 mientras el hosting esté disponible; verificar siempre los SHA-256.
2. Restaurar el manifiesto y `queue.sqlite3`, además del estado y borradores del publicador. No inicializar una cola vacía cuando ya existen publicaciones: conciliar primero los resultados con Meta para evitar duplicados.
3. Revisar credenciales mediante las variables de entorno del servidor. `.env`, claves SSH y datos operativos no forman parte de este respaldo de código.
4. Comprobar QC, aprobación y disponibilidad HTTPS. Habilitar el manifiesto solo después de la conciliación.
5. Mantener desactivada la fábrica de imágenes y conservar la publicación habitual en `image_only`. Los videos usan una ruta separada.

La política inicial exige una publicación habitual entre campañas, un mínimo de 24 horas entre intentos de campaña y siete días antes de repetir una pieza. Un envío parcial o incierto queda en cuarentena. Su estado se debe revisar contra Meta antes de permitir un nuevo intento.

La ejecución de video utiliza URL HTTPS estable. El enlace temporal devuelto por staging de Facebook no superó la ingestión de Instagram para estas piezas. Los contenedores de Reel fueron procesados con URL estable, sin necesidad de publicar durante la validación.

## Comprobaciones

```powershell
python -m pytest tests/test_campaign_queue.py tests/test_instagram_graph_publisher.py tests/test_instagram_publish_flow.py tests/test_publish_schedule.py -q
python scripts/campaign_status.py
```

Los generadores usan Pillow, MoviePy y FFmpeg; actualmente seleccionan fuentes de Windows. Las imágenes de entrada, la música y las salidas se conservan en las carpetas indicadas en cada script. Los MP4 y el estado mutable de producción requieren un respaldo aparte de Git.

La rama `mejoras` conserva el trabajo local de desarrollo. Una rama de respaldo del VPS registra por separado las diferencias del código del contenedor desplegado. Un push a `main` puede activar el workflow de despliegue existente: el respaldo de código no exige ejecutar ese despliegue.


## Revisión editorial y ampliación de noviembre

Las 30 imágenes habituales se recompusieron con textos prudentes, palabras completas y escenas corregidas por servicio. Se conserva cada original y su aprobación anterior. El video antiguo `mascotas_bien_cuidadas_v1` queda desactivado por fotografías poco representativas; el Reel canino nuevo sigue activo. La revisión inicial dejó 21 campañas registradas y 20 habilitadas (12 imágenes y 8 videos).

Dos campañas nuevas de mudanzas y mecánica automotriz tienen Feed, Story y enlace medible. Se mantienen las ventanas y la frecuencia. Ver `editorial_review_20261114.md`.


## Diseños y formatos variados

La ampliación siguiente suma tres conceptos: guía amarilla del 2026, búsqueda por comuna y pendientes cotidianos. Hay dos Feed 4:5, un Feed cuadrado 1:1 y tres Stories con composición propia 9:16. La biblioteca actual tiene 24 entradas: 23 habilitadas (15 campañas de imagen y 8 videos), además de las 30 imágenes habituales por servicio. La pieza con año 2026 tiene fecha de caducidad. Ver `variedad_campaigns_20261114.md`.

## Consejos útiles y observación de captación

Se suman dos campañas con consejos para consultar por una mudanza o soporte de notebook: dos Feed (1:1 y 4:5) y dos Stories nativas 9:16. La biblioteca tiene ahora 26 entradas, 25 habilitadas (17 campañas de imagen y 8 videos), además de las 30 imágenes habituales por servicio. Los horarios se conservan. El seguimiento privado de 14 días evalúa consultas con referencia y métricas comparables; no aumenta la frecuencia automáticamente. Ver `acquisition_trial_20261114.md`.
