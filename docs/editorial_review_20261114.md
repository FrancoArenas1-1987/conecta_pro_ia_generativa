# Revisión editorial y nuevas campañas — 14 de noviembre de 2026

La revisión técnica de la biblioteca se complementó con inspección visual. Los archivos podían cumplir formato, dimensiones y hashes y aun así mostrar una escena equivocada o afirmaciones sin respaldo.

## Correcciones

Se recompusieron 30 imágenes habituales por servicio como versiones `_editorial_v8.png`, conservando los originales. La plantilla elimina promesas de rapidez, verificación y cantidades de profesionales incrustadas en las imágenes. Distingue la búsqueda gratuita del servicio cobrado por cada profesional e invita a consultar disponibilidad y valores.

Se corrigió el orden de las reglas de escenas: veterinaria y peluquería canina se resuelven antes de salud y belleza; climatización y calefont antes de la regla genérica de gasfitería. Se crearon fotografías ilustrativas adecuadas para climatización, veterinaria, mudanzas y calefont; para peluquería canina se reutilizó la escena del Reel reciente. Los prompts están en `config/service_ads.editorial_v8.prompts.json`.

El ajuste tipográfico reduce el tamaño antes de partir una palabra. Un texto que no cabe conservando palabras completas falla antes de producir una pieza aprobada. Las pruebas cubren climatización, kinesiología, hamburguesas, electrodomésticos y sanitización, además de la correspondencia de escenas y la ausencia de las promesas retiradas.

El video antiguo `mascotas_bien_cuidadas_v1` queda fuera de rotación por fotos poco representativas. Se conserva, sin borrar su historial. La pieza nueva de peluquería canina permanece habilitada.

## Nuevas campañas

- Mudanzas: ayudar a formular la consulta con origen, destino y fecha.
- Mecánica automotriz: reconocer una necesidad concreta y pedir servicio y comuna.

Cada campaña conserva un original generado con la herramienta integrada de esta conversación, JPEG Feed 1080×1350, JPEG Story 1080×1920, texto revisado y referencia de WhatsApp. No son testimonios ni proveedores identificados. Los parámetros y prompts están en `config/campaigns.expansion_20261114.prompts.json`; la preparación usa `scripts/prepare_contact_ads.py --specs ... --output ...`. Esta conversión conserva el arte completo.

Galería de entrega: https://conectaproia.cl/campanas/expansion-20261114/

## Controles y reproducción

La recomposición manual usa `scripts/repair_service_library.py` sobre una instantánea privada y fuentes existentes. No accede a la base de datos, a IA ni a publicación: produce candidatos para revisar. Los datos operativos, informes, fotografías originales y respaldos permanecen fuera del repositorio público.

La auditoría aislada validó 30 primarias, 60 variantes Feed/Story, 118 textos y 4 tipos de carrusel sin fallos. Se revisaron los medios y textos de las campañas existentes. Para las dos nuevas se verifica además la descarga HTTPS y la ingestión en contenedores de Instagram sin publicar. `scripts/check_campaign_ingest.py` bloquea las llamadas de publicación y las escrituras ajenas a la creación de contenedores.

El registro activo conserva los hashes de cada aprobación; los originales anteriores quedan excluidos de la selección al cambiar la primaria. La biblioteca contiene 21 entradas y 20 campañas habilitadas, además de las 30 imágenes habituales. Se conservan los horarios, el intervalo entre campañas y los controles de resultados parciales. La generación automática de imágenes por API permanece apagada.

La validación reduce errores previsibles; no garantiza ausencia absoluta de defectos ni una cantidad de clientes. Las referencias permiten comparar consultas recibidas, no demostrar ventas.
