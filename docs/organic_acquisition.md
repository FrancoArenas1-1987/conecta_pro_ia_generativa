# Captación orgánica y métricas verificables

Este repositorio publica contenido y recoge métricas de Meta. No compra anuncios ni llama a servicios de IA para el análisis. La generación automática de imágenes continúa desactivada.

## Fallo de Stories de video de Facebook

La implementación anterior intentaba POST /PAGE/video_stories con video_url, url o file_url. Ese endpoint requiere una sesión de carga y rechazaba las tres peticiones por ausencia de upload_phase. El error se producía aunque Instagram Reel, Instagram Story y Facebook video ya hubieran sido publicados.

El publicador ahora:

1. Solicita upload_phase=start y conserva video_id.
2. Transfiere la URL HTTPS al upload_url devuelto por Meta, validando su host y el video_id.
3. Confirma uploading_phase=complete.
4. Registra la intención de finalizar y envía upload_phase=finish con video_state=PUBLISHED exactamente una vez.
5. Espera publishing_phase=complete. No confunde una aceptación HTTP con una publicación terminada.
6. Conserva el identificador real de la Story. Si finish devuelve solo success, resuelve la Story por su media_id exacto.

Cada fase de una campaña queda registrada antes de finalizar. Un timeout después de finish conserva el video_id y bloquea un reintento ciego. No se garantiza ausencia de fallos externos de Meta, pero se preservan los datos necesarios para conciliarlos sin repetir los destinos ya publicados.

La herramienta recover_facebook_story.py solo permite reparar el rechazo antiguo HTTP 400 que no inició una sesión y no tiene un resultado ambiguo. Requiere que los otros destinos tengan comprobantes, que la cuenta coincida y que el video conserve su aprobación. Una recuperación que se interrumpe no se vuelve a enviar automáticamente.

Fuente primaria del protocolo: https://github.com/fbsamples/reels_publishing_apis/blob/main/fb_reels_publishing_api_sample/index.js
Referencia de parámetros: https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/page.py

## Recolección

collect_social_insights.py consulta posts, Reels y Stories activos de Instagram; posts y Stories de Facebook cuando la API permite las métricas. Usa un máximo de 120 lecturas y conserva snapshots en OUTPUT_ROOT/instagram/analytics/observations.sqlite3. Las métricas no disponibles se conservan como ausentes; no se convierten en cero.

El temporizador conectapro-social-insights corre a las 08:15, 14:15 y 20:45 America/Santiago, con hasta tres minutos de desfase. Permite capturar las Stories antes de que expiren. Una segunda ejecución dentro de cuatro horas se omite. Los archivos del temporizador están en config/systemd. No cambia los horarios de publicación ni activa la fábrica de imágenes.

Los informes son privados: latest.json, analysis.json, policy.json, summary.json e informe.html. No se alojan en la galería pública de publicidad.

Referencia de métricas de Facebook: https://developers.facebook.com/docs/graph-api/reference/insights

## Medir consultas sin confundirlas con visualizaciones

Los nuevos borradores destinados a clientes usan un enlace WhatsApp con un mensaje previo que indica el servicio y una referencia CP de 12 dígitos hexadecimales. La referencia del borrador es estable y distinta de otros borradores. Cada campaña aprobada tiene una referencia por pieza creativa, compartida entre redes y repeticiones.

El recolector puede contar contactos de WhatsApp distintos por referencia durante los últimos 45 días mediante una consulta parametrizada y de solo lectura a la base ya configurada. No exporta textos, teléfonos ni identificadores de personas. La plataforma de atención no se modifica. Si la base no está disponible, la atribución permanece no disponible.

Las consultas se cuentan por referencia creativa, no por red o por publicación individual. No se suman como clientes globales únicos: una persona puede usar varias referencias. Una consulta no demuestra una venta, una contratación ni un trabajo realizado. Los mensajes que no llevan referencia no se atribuyen a un anuncio.

La llamada a la acción de los nuevos textos para clientes pide concretamente qué necesitan y en qué comuna buscan atención. Las imágenes existentes se mantienen.

## Ajustes automáticos conservadores

La rotación considera guardados, compartidos, respuestas, visitas al perfil y seguidores nuevos como señales de intención. No usa visualizaciones como clics ni inventa conversiones.

Para ajustar categorías se exige:

- Contenido para captar clientes, de Instagram feed o carrusel.
- Al menos 48 horas y no más de 45 días de antigüedad.
- Métricas recogidas durante las últimas 48 horas.
- Al menos tres publicaciones por categoría, alcance acumulado de 100 y señales de intención.
- Otra categoría comparable del mismo formato.
- Peso limitado entre 0,85 y 1,30.

Se reserva uno de cada tres turnos para la secuencia de exploración y se excluyen recursos recientes en los demás turnos. La elección es estable durante un mismo intento para mantener coherentes imagen y categoría. Sin evidencia o con un informe caducado se conserva la selección anterior.

Las campañas nuevas continúan su rotación editorial: no se favorece prematuramente una pieza sin historial suficiente. No se incrementa la frecuencia para compensar un alcance bajo.
