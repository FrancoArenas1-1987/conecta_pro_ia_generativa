# Campañas con diseños y formatos variados — 14 de noviembre de 2026

Tres conceptos buscan facilitar el primer contacto: una guía amarilla moderna con el mensaje “Las amarillas del 2026”, la búsqueda por necesidad y comuna, y la pregunta cotidiana “¿A quién llamo para esto?”. Son hipótesis creativas; no demuestran de antemano un aumento de clientes.

La identidad es ConectaProIA. La referencia a una guía amarilla usa un diseño original y no incorpora logotipos de otros directorios. El mensaje invita a buscar contactos, sin garantizar proveedores disponibles en todas las comunas.

## Entregables

- Guía amarilla: Feed 1080×1350 y Story 1080×1920.
- Necesidad y comuna: Feed 1080×1350 y Story 1080×1920.
- Pendientes cotidianos: Feed cuadrado 1080×1080 y Story 1080×1920.

Son seis anuncios completos, con marca, mensaje, WhatsApp, sitio web y aclaración sobre el servicio cobrado por cada profesional. Cada Story tiene composición propia para pantalla vertical. La revisión editorial incluyó ortografía, teléfono, categorías representadas y posición de los textos.

Los seis originales se generaron con la herramienta integrada de la conversación. Los prompts iniciales y las instrucciones de ajuste de las Stories quedan en `config/campaigns.variedad_20261114.prompts.json`. Los archivos de trabajo descartados no se habilitan para publicar.

Los medios, originales, textos, manifiestos de revisión y galería se guardan en `output/advertising/variedad_2026_11_14`. La preparación usa `scripts/prepare_contact_ads.py`: admite Feed cuadrado y un original independiente para Story; conserva el arte completo durante la conversión y registra sus hashes. La galería muestra las seis versiones.

Galería de entrega: https://conectaproia.cl/campanas/variedad-20261114/

## Publicación y validación

Las tres campañas se intercalan en la biblioteca activa con texto y referencia de WhatsApp por concepto. Se mantienen las ventanas existentes, el mínimo de 24 horas entre campañas y una publicación habitual entre ellas. Las piezas nuevas tienen un mínimo de 21 días antes de repetirse.

La pieza con “2026” caduca el 1 de enero de 2027 a las 00:00 UTC. El selector admite `not_after` con zona horaria explícita y omite las piezas vencidas; las pruebas verifican el límite temporal y la continuidad de las campañas sin fecha de vencimiento.

Los controles incluyen dimensiones, JPEG, hashes aprobados, texto asociado, descarga HTTPS y procesamiento de Feed/Story en contenedores no publicados de Instagram. El comprobador bloquea `media_publish`. Una simulación sobre una copia privada de la cola comprueba la selección de las campañas sin enviar publicaciones ni alterar el historial real.

La biblioteca contiene 24 campañas registradas y 23 habilitadas: 15 de imagen y 8 videos. Las 30 primarias habituales por servicio siguen aprobadas para su rotación. El video antiguo de mascotas observado permanece deshabilitado. Los datos operativos y respaldos se conservan fuera del repositorio público.

La generación automática de imágenes por API sigue apagada. Las referencias permiten medir consultas que las incluyan; no atribuyen todas las consultas ni demuestran ventas. El manifiesto de restauración del repositorio permanece desactivado.
