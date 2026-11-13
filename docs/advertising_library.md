# Biblioteca de campañas publicitarias

La biblioteca incorpora diez imágenes de campaña y seis videos. Es adicional a las imágenes habituales por servicio y a los carruseles existentes.

Los ángulos editoriales incluyen hogar, mascotas, variedad de servicios, marca, cómo buscar por necesidad y comuna, preguntas antes de contratar y la diferencia entre buscar contactos gratis y pagar por el trabajo profesional. No se presentan las personas ilustradas como testimonios o proveedores identificados.

## Archivos y textos

- El manifiesto productivo vive en OUTPUT_ROOT/instagram/campaigns/manifest.json.
- config/campaigns.library.json es una plantilla de restauración desactivada. Se debe conciliar el historial antes de habilitar una restauración.
- output/advertising/fresco_2026_11_12/revisar.html permite revisar los medios y captions localmente.
- Los PNG originales se conservan; las copias de entrega son JPEG 1080x1350 para feed. Las tres imágenes nuevas tienen JPEG 1080x1920 para Stories, con el diseño completo centrado sin recortes.
- Las tres imágenes iniciales se publican solo en feed: el caption incluye el contacto. Las nuevas imágenes y todos los videos incluyen contacto en la propia pieza.
- Los videos nuevos contienen tipografía animada y música de la biblioteca existente, sin narración ni solicitudes de IA.
- scripts/create_fresh_ads.py compone y codifica localmente; no publica ni llama a proveedores de IA. Deja las nuevas entradas pendientes de revisión.

## Rotación y seguridad

Las campañas de imagen y video usan la misma cola persistente y las mismas ventanas e intervalos del publicador. El orden intercala formatos y temas. Hay una publicación habitual entre campañas y al menos 24 horas entre intentos de campaña. Las nueve incorporaciones tienen un mínimo de 14 días antes de repetirse. La selección prioriza las piezas aún no intentadas y luego las menos recientes.

Cada recurso, caption y variante de Story requiere aprobación por SHA-256. La cola comprueba JPEG, proporción, tamaño y los bytes HTTPS antes de enviar. Los videos conservan su QC y verificación de bytes. No se transforma una imagen de feed en Story durante la publicación.

Los resultados parciales o inciertos conservan sus comprobantes y quedan bloqueados para reintento automático. El historial SQLite no se reemplaza al ampliar la biblioteca.

## Revisión sin publicar

    python scripts/check_campaign_library.py /ruta/campanas/manifest.json --report output/reviews/campaign_media.json
    python scripts/check_campaign_library.py /ruta/campanas/manifest.json --remote --report output/reviews/campaign_public_bytes.json
    python scripts/campaign_status.py

La auditoría comprueba captions, hashes, estructura de imágenes, decodificación completa de videos, duración, formato, cuadros no vacíos, audio audible sin saturación y MP4 faststart. --remote descarga los recursos HTTPS para verificar el contenido servido. No crea publicaciones.

Las pruebas de ingesta de Meta crean contenedores sin ejecutar media_publish. Un estado FINISHED demuestra que Meta procesó ese archivo; no equivale a una publicación visible ni garantiza futuras entregas.

La generación automática pagada de imágenes sigue desactivada. Esta biblioteca utiliza el VPS existente y recursos ya preparados. Los medios originales, paquetes y registros operativos permanecen en el almacenamiento de trabajo y los backups privados; el repositorio de código conserva los scripts, prompts, controles y manifiesto de restauración.


## Tanda para consultas por necesidad y comuna

Cuatro piezas nuevas de hogar, búsqueda por comuna, traducción y pizzerías se documentan en contacto_campaigns.md. Cada una tiene feed y Story, texto revisado y referencia de consulta. Sus originales y ocho JPEG de entrega se conservan en output/advertising/contacto_2026_11_13. Los nuevos elementos se intercalan al comienzo del manifiesto con los existentes; no se aumenta la frecuencia y la cola conserva todos sus comprobantes. El mínimo de repetición de estas cuatro piezas es de 21 días.
