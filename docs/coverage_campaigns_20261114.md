# Cobertura y revisión de campañas

Se preparan 13 campañas nuevas con Feed 4:5 y Story nativa 9:16. Siete cubren categorías sin campaña específica habilitada: restaurantes/comida preparada, depilación, jardinería, carpintería, pintura, grúas/asistencia en ruta y abogados. Las otras muestran guías turísticos, agencias de viajes, sushi, hamburguesas, sándwiches/completos y un directorio general que combina varios sectores.

Se revisan tres Feed para incluir el teléfono de ConectaProIA (+56 9 8343 4503), la web y la acción dentro del arte. Se producen once Stories propias, incluidas las de esos tres anuncios. Se conservan identificadores e historial de campaña y se guardan archivos anteriores con nombres/versiones diferentes.

En conjunto son 40 archivos de entrega nuevos o revisados: 26 de ampliación, tres Feed corregidos y once Stories. Las escenas son ilustrativas, no testimonios ni prestadores identificados. Las piezas distinguen búsqueda gratuita de servicio cobrado y piden confirmar condiciones. No prometen disponibilidad inmediata ni cobertura para cualquier servicio en cualquier comuna.

La biblioteca fuente tiene 39 entradas y mantiene el interruptor global deshabilitado para restaurar con conciliación. La activación productiva deja 37 campañas habilitadas: 29 de imagen (todas con Story nativa) y ocho videos. Traducción permanece pausada y el video antiguo de mascotas deshabilitado. Las 30 primarias habituales aprobadas se conservan.

## Fuentes y reproducción

La herramienta integrada imagegen de esta conversación generó o editó los originales; no se usó el CLI ni generación pagada en el VPS. Los prompts se respaldan en:

- `config/campaigns.cobertura_20261114.prompts.json`
- `config/campaigns.correcciones_20261114.prompts.json`

Los originales y entregables están en el respaldo privado y en las carpetas locales `output/advertising/cobertura_2026_11_14` y `output/advertising/correcciones_2026_11_14`.

```sh
python scripts/prepare_contact_ads.py --specs config/campaigns.cobertura_20261114.prompts.json --output output/advertising/cobertura_2026_11_14
python scripts/prepare_reviewed_campaign_revisions.py --library config/campaigns.library.json --specs config/campaigns.correcciones_20261114.prompts.json --output output/advertising/correcciones_2026_11_14
```

Estos comandos producen candidatos deshabilitados para revisar. La preparación conserva las versiones previas sin duplicarlas al repetirse. El estado mutable productivo y su cola se restauran desde respaldo y se concilian.

Galerías de entrega previstas en el hosting existente:

- https://conectaproia.cl/campanas/cobertura-20261114/
- https://conectaproia.cl/campanas/correcciones-20261114/

## Seguimiento y controles

El recolector existente actualiza un informe privado `OUTPUT_ROOT/instagram/analytics/coverage.json` con oferta actual, campañas sin oferta, piezas generales y servicios sin publicidad específica. No publica, no aumenta frecuencia y no transforma métricas ausentes en cero. El reporte de 14 días continúa con su configuración previa.

La revisión combina originales y JPEG, contacto y ortografía, hashes y captions, dimensiones, descarga HTTPS y contenedores de ingestión sin publicar. El checker bloquea `media_publish`; `--formats STORIES` permite revisar solo las nuevas Stories de campañas cuyo Feed se conserva. El control de oferta se prueba sin red antes de desplegar.

Se conservan temporizadores, intervalos, aprobación editorial e historial por destino. La fábrica de imágenes por API sigue deshabilitada. Esta ampliación prioriza siete brechas; no equivale a crear un anuncio individual para todas las categorías del catálogo. El informe privado mantiene visible lo que falta.
