# Campañas para iniciar consultas

La tanda incorpora cuatro imágenes originales generadas con la herramienta integrada image_gen. El VPS recibe recursos ya preparados y no genera imágenes ni compra anuncios.

| Pieza | Necesidad que aborda | Acción pedida |
|---|---|---|
| Gotera pendiente | Una tarea concreta del hogar | Explicar la necesidad e indicar comuna |
| Necesidad y comuna | No saber por dónde empezar a buscar | Nombrar servicio y comuna |
| Documento por traducir | Buscar apoyo para un documento | Indicar idioma, documento y comuna |
| Pizza para compartir | Una ocasión cotidiana | Indicar comuna y qué busca para compartir |

Gasfitería, traducción y pizzerías se eligieron como hipótesis a partir de pequeñas señales históricas de Instagram: seguidores o visitas al perfil. No se presentan como ganadores demostrados ni se promete aumentar contactos en un porcentaje concreto.

## Entregables y reproducibilidad

- Prompts completos, textos y CTA: config/campaigns.contacto.prompts.json.
- Preparación sin llamadas a IA ni publicaciones: python scripts/prepare_contact_ads.py.
- Originales, feed JPEG 1080x1350, Story JPEG 1080x1920, captions, revisión y galería: output/advertising/contacto_2026_11_13.
- El script solo codifica y adapta el tamaño manteniendo el arte completo, sin recortes. Los originales generados se conservan sin cambios.
- manifest.review.json queda desactivado y pendiente. Tras revisión se crea manifest.approved.json con fechas y hashes.
- config/campaigns.library.json incorpora los dieciséis elementos como plantilla de restauración desactivada. El manifiesto activo se mantiene en el VPS junto al historial; no se reemplaza la base de la cola al ampliar la biblioteca.

Los cuatro anuncios se intercalan con la biblioteca anterior, empezando por hogar. Siguen los horarios, el mínimo de 24 horas entre campañas y la publicación habitual entre campañas. Las nuevas piezas esperan al menos 21 días antes de repetirse.

## Contenido y medición

El contacto oficial y la dirección de ConectaProIA se muestran dentro de cada imagen, también en Stories. Se aclara que buscar contactos es gratis y que valores y disponibilidad se consultan con cada profesional o local. Las fotografías son ilustrativas; no representan testimonios o negocios identificados.

Cada pieza tiene una referencia estable en el mensaje previo del enlace WhatsApp. El recolector existente cuenta contactos distintos que envían esa referencia, con consulta de solo lectura y sin exportar mensajes o personas. Se comparte entre canales y repeticiones; no atribuye por sí sola una red ni demuestra una venta. Los contactos que llegan por teléfono, web o un enlace sin referencia pueden quedar sin atribuir.

Comparar consultas, respuestas, guardados y visitas al perfil cuando las piezas tengan exposición suficiente. Mantener los datos ausentes como no disponibles. Estas variantes cambian imagen y texto a la vez; no constituyen un experimento A/B que permita aislar una única causa.

## Respaldo

Los scripts, prompts, textos y manifiesto se respaldan en Git. Los PNG, JPEG, galería y registros de revisión se respaldan en el paquete privado del VPS y en la carpeta local de trabajo. La galería pública solo contiene los anuncios y sus textos, sin métricas ni datos de clientes.
