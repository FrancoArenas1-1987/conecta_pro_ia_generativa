# Revisión operativa — 18 de octubre de 2026

Consulta al VPS y PostgreSQL realizada aproximadamente a las 10:34, America/Santiago. No se cambiaron configuraciones ni datos, ni se ejecutaron trabajos de generación/publicación. Se ejecutó el reporte de estado en un contenedor temporal. Las publicaciones se comprobaron mediante respuestas persistidas en logs; no se consultó su visibilidad actual en Meta.

## Resultado

El VPS, Docker, API y PostgreSQL están operativos. Los cuatro timers están activos y systemd no registra unidades fallidas actualmente. Esto no descarta errores históricos: se encontraron fallos repetidos de generación de imágenes y bloqueos por presupuesto en búsqueda de proveedores.

## Automatización social

Recuento de archivos de log con fecha UTC desde 2026-10-11 hasta la consulta del 18 (incluye días parciales):

| Trabajo | Resultado |
|---|---|
| Fábrica de imágenes | 181 fallos con `Layout guard failed: preflight_candidate.png: card_service se superpone con cta`; 1 éxito posterior |
| Publicación automática | 13 ejecuciones exitosas y 1 omisión por intervalo mínimo |
| Carruseles | 4 ejecuciones exitosas; 233 omisiones por intervalo mínimo; 14 fuera de ventana; 1 log no interpretable por el parser |
| Renovación Meta | 8 ejecuciones exitosas |

La última imagen se generó el 18/10 a las 10:07 de Chile para lavandería/tintorería. Un único éxito posterior no demuestra que el fallo de layout esté resuelto para todos los servicios. El registro contiene 27 servicios activos con imagen aprobada, 111 sin imagen y 2 que requieren revisión: comida_preparada_restaurante y depilacion. La elegibilidad para generación depende también de proveedores disponibles y guardias de presupuesto/cadencia.

Última publicación automática: 17/10 a las 17:06 de Chile. El log registra modo real, estado published e identificadores de Instagram y Facebook. Último carrusel exitoso: 17/10 a las 14:50 de Chile, con identificadores de ambas plataformas. La última ejecución de carrusel se omitió normalmente a las 20:50 por ventana permitida 11:00–20:30. El timer incluye horas fuera de esa ventana; conviene alinearlo para reducir ruido.

Renovación Meta más reciente: 18/10 a las 00:58 de Chile, ok=true. No se verificó independientemente la expiración del token contra Meta.

Presupuesto local de imágenes de octubre: USD 1.806865 estimados/reservados; sin bloqueo de cuota. No representa facturación comprobada del proveedor.

## Base de datos y worker de plataforma

Consultas de los últimos siete días exactos en worker_runs: 7 succeeded, 18 blocked y 3 partial, todos de provider_discovery. Los 21 resultados bloqueados/parciales indican daily_search_budget_exhausted. El worker permanece activo, pero el descubrimiento queda limitado por presupuesto diario de búsqueda (proveedor configurado: Tavily). Último bloqueo: 18/10 a las 09:00 de Chile; último éxito: 17/10 a las 21:00 de Chile.

Candidatos: 1.893 imported, 79 pending_review, 585 rejected y 30 duplicate_provider. Mensajes entrantes sin procesar: 0. PostgreSQL responde y ocupa aproximadamente 60 MB. Una transacción inactiva vista inicialmente no persistió en la segunda consulta.

## Infraestructura y despliegue

Disco raíz: 47% ocupado, aproximadamente 40 GB libres. Memoria disponible: aproximadamente 2,5 GiB de 3,8 GiB; swap usada aproximadamente 236 MiB. Carga baja al momento de consulta. API y DB reportadas healthy; contenedor worker activo desde hace 11 días. No se realizó una auditoría completa de logs de otros proyectos del VPS.

HEAD del VPS: 40743c5, 2026-09-02. Tanto VPS como copia local tienen cambios sin commit, incluyendo automatización, presupuesto y registro de imágenes. Varios archivos coinciden por nombre; no se verificó igualdad de contenido. El VPS contiene además imágenes modificadas y archivos no versionados con nombres como CACHED, FETCH_HEAD y exporting. El script de despliegue presente en el árbol de trabajo rechaza repositorios sucios: un próximo deploy puede quedar bloqueado. No se limpiaron ni sobrescribieron archivos.

## Prioridades recomendadas

1. Revisar el layout y confirmar ejecuciones posteriores de fábrica; evitar nuevos gastos manuales mientras se diagnostica. Comprobar el único log de carrusel no interpretable.
2. Alinear cantidad y frecuencia de búsqueda con presupuesto diario antes de aumentar límites o contratar cuota.
3. Revisar las dos imágenes pendientes y priorizar faltantes de servicios con proveedores.
4. Consolidar cambios de producción en Git y preservar imágenes/artefactos antes de ordenar el repositorio y desplegar.
5. Monitorizar fallos históricos y bloqueos funcionales además de Result=success de systemd.
