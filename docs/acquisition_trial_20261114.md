# Consejos útiles y seguimiento de captación

Del 14 de noviembre de 2026 a las 14:00 al 28 de noviembre a las 14:00 (America/Santiago) se observa una mezcla más variada sin cambiar los temporizadores, ventanas ni intervalos existentes. La fábrica de imágenes en el servidor permanece deshabilitada. No hay campañas de pago ni llamadas nuevas de generación a proveedores externos.

## Contenido aprobado

- `mudanza_datos_utiles_20261114_v1`: datos para consultar una mudanza; Feed cuadrado y Story con composición propia.
- `notebook_consulta_clara_20261114_v1`: datos para explicar una necesidad de soporte; Feed 4:5 y Story con composición propia.

Los cuatro diseños contienen mensaje, contacto, búsqueda gratuita y aclaración del servicio pagado. Se revisaron originales, entregables y captions. Los cuatro contenedores de prueba de Instagram terminaron en FINISHED sin publicar. Galería: https://conectaproia.cl/campanas/utilidad-20261114/ . Los originales, entregables y manifiestos se conservan en el respaldo privado de medios; los prompts están en `config/campaigns.utilidad_20261114.prompts.json`.

El manifiesto fuente conserva el interruptor global deshabilitado para restauraciones seguras. La activación productiva exige preservar `queue.sqlite3` y conciliar el historial, como describe `video_campaigns.md`.

## Evaluación privada y automática

El recolector existente actualiza `OUTPUT_ROOT/instagram/analytics/trials/captacion_14d_20261114/latest.json` e `informe.md`. Esta ruta queda excluida del servidor de medios. La configuración está en `config/acquisition_trial_20261114.json`.

La medida principal es el número de contactos distintos que mencionan una referencia publicitaria publicada, con una consulta SQL de solo lectura acotada por fecha. Se deduplican personas entre referencias sin exportar mensajes, teléfonos ni identificadores. No mide todas las consultas ni demuestra ventas. La referencia se comparte entre redes y no identifica el canal exacto.

Se compara con los 14 días anteriores. Para Feed, Reel y carrusel se toma la primera observación disponible entre 48 y 96 horas; para Stories entre 12 y 24 horas. Las comparaciones se separan por red y formato. No se comparan los totales acumulados de piezas antiguas con publicaciones recientes. Si falta historia o atribución, el informe lo declara y no recomienda aumentar la frecuencia.

Se requieren al menos seis publicaciones y alcance sumado de 200 en cada período dentro de un mismo formato de Instagram, cobertura de referencias del 80% en ambos períodos y atribución disponible. Después del cierre, al menos tres consultas distintas, más consultas que antes y una mediana de alcance no inferior al 80% del período anterior permiten recomendar considerar una prueba limitada de dos publicaciones adicionales por semana. Es una señal orientativa de una observación, no evidencia causal.

El informe nunca cambia temporizadores ni publica. La frecuencia se mantiene salvo un ajuste posterior deliberado. Las últimas piezas de cada período pueden necesitar hasta cuatro días para reunir métricas comparables; las actualizaciones continúan después del cierre.

## Comprobaciones

```sh
python -m pytest tests/test_acquisition_trial.py tests/test_acquisition_tracking.py tests/test_social_analytics.py tests/test_ad_delivery_formats.py tests/test_analytics_privacy.py -q
```

La validación productiva comprueba hashes de medios y fuentes, captions, URL HTTPS, selección en una copia aislada de la cola, horarios sin cambios, atribución SQL y protección de los informes. No ejecuta el publicador para probar.
