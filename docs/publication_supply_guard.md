# Oferta vigente antes de publicar

Las campañas aprobadas declaran `availability_scope` (`general` o `specific`) y `required_service_codes`. Una campaña general no garantiza servicios ni cobertura concretos. Una campaña específica requiere todos los servicios que menciona. Los códigos usan los alias canónicos del registro.

`publication_supply.py` lee categorías activas y cuenta prestadores con servicio activo, prestador activo y sin bloqueo vigente. La conexión SQL usa transacción de solo lectura, timeout y salida agregada; no exporta datos de clientes ni mensajes. No usa APIs de IA ni compra publicidad.

El runner actualiza los indicadores de oferta del registro después de las guardias de horario/intervalo y vuelve a sincronizar la selección. Conserva hashes y decisiones editoriales. El carrusel hace lo mismo después de su intervalo. Las publicaciones directas de borradores y carruseles comprueban la oferta antes de contactar a Meta. Las campañas filtran antes de reclamar la cola y comprueban de nuevo antes de preparar destinos.

Una consulta fallida nunca se interpreta como disponibilidad. Las campañas generales pueden seguir siendo elegibles al invocar directamente la cola; el runner requiere una consulta correcta para preparar su biblioteca. Las entradas sin metadatos o con alcance incoherente quedan fuera de selección. Una campaña pausada no vuelve a activarse por recuperar proveedores: exige revisión deliberada.

La pieza de traducción queda deshabilitada por falta de oferta en la auditoría del 14 de noviembre. Se conserva todo su historial. La presencia de proveedores no garantiza turnos, horarios ni cobertura en cada comuna; los anuncios invitan a consultar condiciones.

Las pruebas verifican bloqueo antes de llamadas a Meta, caída de BDD, conteos antiguos, múltiples servicios, alias, cambios de oferta entre selección y envío, aprobación preservada y conexiones de solo lectura. No se prueba publicando.
