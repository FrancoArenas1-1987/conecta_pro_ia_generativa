# Publicaciones para servicios pendientes

La segunda tanda de cobertura incorpora doce campañas de imagen: movimiento de tierra/demolición/transporte, fosas sépticas/alcantarillado, peluquería/barbería, laboratorios clínicos, redes/WiFi/Internet hogar, control de plagas, enfermería a domicilio, lavado de autos, marketing digital, seguridad privada, traumatología y yoga/Pilates.

Cada concepto tiene Feed 4:5 (1080 × 1350) y Story nativa 9:16 (1080 × 1920), texto de publicación y referencia propia de WhatsApp. Los 24 entregables incluyen mensaje, marca, teléfono de ConectaProIA, web y distinción entre búsqueda gratuita y servicio contratado. Las escenas son ilustrativas y no representan prestadores identificados, testimonios ni resultados garantizados. Las campañas de salud invitan a consultar contactos y condiciones; no ofrecen diagnósticos ni atención de urgencia.

Los originales se generaron con imagegen integrado en la conversación. No se usó generación por API ni se habilitó la fábrica del VPS.

## Preparación y revisión

Prompts: `config/campaigns.pendientes_20261114.prompts.json`.
Originales, entregables y revisión: `output/advertising/pendientes_2026_11_14/`.

```sh
python scripts/prepare_contact_ads.py --specs config/campaigns.pendientes_20261114.prompts.json --output output/advertising/pendientes_2026_11_14
```

La preparación entrega candidatos deshabilitados. Su aprobación requiere revisión visual del original y del JPEG, contacto, ortografía, legibilidad y márgenes para la interfaz de Stories. Las primeras propuestas verticales se descartaron por texto demasiado bajo; los finales reservan el tramo inferior para fondo sin información esencial. Se comprueban captions, hashes, dimensiones, descarga HTTPS, oferta vigente y contenedores de ingestión sin publicar. El manifiesto fuente conserva su interruptor global deshabilitado para restauraciones controladas; el manifiesto productivo se concilia por identificador conservando campañas e historial.

La ampliación no cambia horarios, intervalos, alternancia con imágenes habituales, repetición ni el seguimiento de captación. Se mantienen las dos campañas pausadas y las treinta primarias aprobadas. La rotación resultante contiene 51 entradas, 49 habilitadas: 41 campañas de imagen con Story nativa y ocho videos.

Galería: https://conectaproia.cl/campanas/pendientes-20261114/

El informe de brechas permanece privado y se recalcula con el catálogo y la oferta actual. Esta tanda cubre doce categorías adicionales; las restantes siguen registradas para próximas tandas. Estar habilitado en la rotación no equivale a tener una hora individual de publicación asignada.
