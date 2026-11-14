# Videos para facilitar el primer contacto — 14 de noviembre de 2026

La propuesta es probar tres formas de presentar una necesidad y facilitar un mensaje a ConectaProIA. La publicación sigue siendo orgánica, con la frecuencia existente. No se compran anuncios ni se activa generación de imágenes en el VPS.

## Qué aporta la investigación

El playbook de Meta recomienda video vertical 9:16, audio y mensajes dentro de las zonas libres de interfaz; en particular, reservar el tercio inferior evita que los controles tapen el contenido. Sus estudios de rendimiento corresponden a campañas pagadas y no permiten predecir resultados orgánicos para ConectaProIA. [Playbook de Meta, copia publicada por RDigital](https://rdigital.co/wp-content/uploads/2025/05/ReelsPlaybook_TurnCustomerAttentionIntoResults.pdf).

Meta también explica que favorece contenido original y puede reducir la distribución de copias con cambios menores. Por eso esta tanda tiene guiones, animación y audio propios, en lugar de reutilizar videos de terceros. Esto no garantiza una determinada distribución. [Meta, Rewarding Original Creators on Facebook](https://about.fb.com/news/2026/03/rewarding-original-creators-on-facebook/amp/).

La demostración oficial de WhatsApp muestra enlaces cortos y códigos QR como vías de entrada a una conversación. Nuestra aplicación usa enlaces a WhatsApp con un mensaje preparado. Un QR en el mismo teléfono no es nuestra acción principal. [WhatsApp, demostración de enlaces y QR](https://www.youtube.com/watch?v=igUhP_4_Lyo).

## Hipótesis editorial y piezas producidas

| Formato | Duración | Hipótesis que se prueba |
|---|---:|---|
| Ejemplo de mensaje que se escribe en pantalla | 15 s | Mostrar cómo empezar puede reducir la duda sobre qué escribir |
| Lista animada de pendientes del hogar | 12,6 s | Nombrar tareas reconocibles puede atraer una necesidad concreta |
| Escena de mascota con movimiento editorial | 13,8 s | Un servicio específico puede conectar mejor con personas que lo buscan |

Estas son decisiones de producción, no conclusiones demostradas sobre conversión. El inicio presenta el problema o la pregunta; luego explica qué información enviar y conserva un único destino: WhatsApp. La imagen de la mascota es ilustrativa, generada con image_gen; no representa un proveedor ni un testimonio. El tutorial muestra solo una consulta de ejemplo, sin inventar respuestas o resultados de la plataforma.

Los videos tienen texto permanente que permite entenderlos sin sonido, música y efectos originales sintetizados localmente, y movimiento de cámara o elementos. No incluyen narración. No se descargó música ni se contrataron APIs. Se aclara que buscar contactos es gratis y que el trabajo lo cobra cada profesional.

Los elementos principales quedan dentro de x=90..990, y=290..1240 en un lienzo 1080x1920. El renderer verifica cada caja de texto durante la exportación. Las zonas exactas pueden variar entre superficies y dispositivos; el margen de esta tanda es una decisión conservadora para Reels y Stories.

## Captación y recorrido

La cadena a evaluar es: una necesidad reconocible, comprensión del servicio, acceso al contacto y un mensaje recibido. Para una primera consulta conviene pedir servicio y comuna, y después los detalles que hagan falta. No se añaden formularios nuevos ni respuestas automáticas al bot desde este repositorio.

La web ofrece botones hacia WhatsApp. Conviene revisar también que el perfil social tenga una vía de contacto clicable y vigente; un campo vacío de la API no demuestra por sí solo que no existan otros enlaces del perfil. Estos videos muestran teléfono y web y no dependen de un supuesto enlace de la biografía.

Los siguientes contenidos que vale la pena preparar son demostraciones reales del recorrido de búsqueda, respuestas a dudas frecuentes y consejos útiles de profesionales que participen con permiso. Las entrevistas o testimonios deben ser reales y autorizados; requieren material adicional y no se sustituyen por historias inventadas.

## Cómo comparar resultados

Cada pieza conserva una referencia distinta en el enlace WhatsApp. El recolector existente cuenta contactos que envían esa referencia. No demuestra ventas, no atribuye por red y no captura todos los contactos que lleguen por otros caminos.

Revisar primero que las piezas se publicaron y se pudieron reproducir. Después comparar señales tras al menos 48 horas y volver a revisar a los siete días, teniendo en cuenta antigüedad y exposición. Un video con pocos espectadores no permite descartar su concepto. Separar alcance, interacciones, consultas atribuibles y contrataciones confirmadas.

Se mantiene variedad y no se aumenta la frecuencia para compensar un alcance bajo. Los nuevos formatos se suman a las imágenes y videos existentes. No se declara un ganador a partir de una sola consulta.

## Archivos y controles

- Guiones y parámetros: config/campaigns.reels_20261114.json.
- Prompt de la escena: config/campaigns.reels_20261114.prompt.json.
- Fuente: scripts/create_motion_reels.py.
- Medios, audio, escenas de revisión, captions y galería: output/advertising/reels_2026_11_14.
- El script crea manifest.review.json desactivado. Tras la revisión se aprueban hashes y fechas.
- Las tres entradas mantienen un mínimo de 21 días antes de repetirse, las ventanas existentes y la cuarentena de resultados parciales.
- Validación: geometría del texto, decodificación completa, dimensiones, duración, H.264/AAC, audio sin saturación, MP4 faststart, hashes y descarga HTTPS. Los contenedores de prueba de Meta no ejecutan media_publish.
