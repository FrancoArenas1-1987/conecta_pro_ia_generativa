# Control previo de publicaciones

Cada publicación de feed/Reel conserva un caption asociado. Las Stories usan el texto del propio recurso visual; no reciben el caption del feed.

## Bloqueos antes de publicar

- Caption obligatorio, marca, enlace WhatsApp correcto y aclaración sobre la contratación del servicio.
- Detección de placeholders, texto con codificación rota y afirmaciones no respaldadas contempladas por las reglas.
- Coherencia entre la categoría de la imagen seleccionada y la categoría del borrador.
- Control técnico de imagen activo en la configuración y obligatorio en el runner programado.
- Campañas: video, portada y caption aprobados por SHA-256. La descarga HTTPS se compara byte a byte mediante hash con el MP4 aprobado.
- Carruseles: tres servicios del mismo tema, fuentes aprobadas en el registro, cinco slides válidos y captions revisados.

Los textos de las campañas se pueden revisar en `captions_campanas.md`. Las plantillas habituales corrigen errores ortográficos conocidos y sustituyen promesas no verificadas de certificación, disponibilidad inmediata o respuesta en minutos por información sobre contactos y disponibilidad.

## Resultados parciales

Las campañas conservan el registro de cada envío por destino y canal. Los carruseles ahora guardan el resultado de Instagram antes de enviar a Facebook. Si queda un envío parcial o incierto, se conserva un registro pendiente y se bloquea el reintento automático. Resolverlo requiere conciliar los identificadores con Meta, sin volver a publicar destinos que ya tuvieron éxito.

## Auditoría sin publicar

```bash
python scripts/audit_publication_library.py --report output/reviews/publication_audit.json
python scripts/campaign_status.py
```

El auditor comprueba variantes para clientes y proveedores, imágenes feed/story, temas de carrusel elegibles y captions de campañas. Usa archivos locales y no llama a proveedores ni publica. Su informe incluye los textos y resultados de cada comprobación.

Estos controles verifican reglas concretas y estructura técnica. No demuestran por sí solos que una fotografía represente bien el servicio, que todo texto integrado sea perfecto o que la pieza tenga buena calidad publicitaria. El contenido visual nuevo sigue necesitando revisión editorial antes de aprobarse. No se corrigieron publicaciones históricas ya publicadas.

## Biblioteca de campañas de imagen y video

Ver advertising_library.md para los formatos, fuentes, rotación y auditoría completa de las doce campañas. Las imágenes de campaña usan el mismo registro durable de entregas que los videos.

## Comprobantes de Stories y referencias

Las Stories de video de Facebook utilizan start, transferencia y finish, con registro de video_id y confirmación de la fase de publicación. La aceptación de una carga no se marca como publicación terminada. Las referencias de WhatsApp en los nuevos borradores y campañas conservan el teléfono validado. Ver organic_acquisition.md.
