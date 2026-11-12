# Una imagen por servicio y control operativo

La biblioteca productiva usa `output/runs/instagram/catalog/service_images.json`.
La clave es `service_catalog.code`; `legal`, `veterinarios`, `desarrollo_software`
y `traductores_ingles_espanol` son alias de los códigos actuales de la base.
Cada servicio tiene una imagen principal. Las variantes anteriores se conservan
en disco, pero no se seleccionan para publicación ni carruseles.

La fábrica reconcilia servicios activos con proveedores y adopta las imágenes
existentes cuyo control de calidad está aprobado. Mantiene esa aprobación por
SHA-256: cambiar la versión del manifiesto no dispara otra generación. Cambiar,
eliminar o rechazar una imagen la deja en `needs_review`. Sólo `missing` entra
a la cola automática. Una imagen rechazada después de generarse requiere revisión,
no otra petición pagada automática. No se generan servicios sin proveedores.

La publicación automática reutiliza las imágenes principales y desactiva la
generación OpenAI inline. La fábrica conserva el intervalo de 24 horas entre
creaciones exitosas; cuando ya no hay faltantes, no genera nada.

El presupuesto de la fábrica se controla con reservas atómicas en SQLite:
`output/runs/instagram/budget/image_usage.sqlite3`. Usa el límite
`INSTAGRAM_OPENAI_MONTHLY_BUDGET_USD` y reserva por petición
`IG_IMAGE_REQUEST_RESERVATION_USD` (0.30 USD por defecto para la configuración
gpt-image-1/high/1024x1536; revisar antes de cambiar modelo o tamaño).
Se conserva request_id, uso y costo calculado cuando el esquema es conocido;
el resto se contabiliza conservadoramente como reserva/estimación. Los logs
anteriores se importan una sola vez como estimaciones, nunca como facturación exacta.
La importación excluye nuevas peticiones ya registradas para evitar doble conteo.
Un error incierto conserva su reserva. El saldo agotado bloquea las siguientes
llamadas hasta ejecutar `--resume-after-topup` después de recargar.

Auditoría/sin gasto:

```
python scripts/instagram_image_factory.py --dry-run
python scripts/automation_status.py --database
```

`--dry-run` actualiza registro y presupuesto histórico, pero no solicita imágenes.
Después de recargar, `--dry-run --resume-after-topup` elimina un bloqueo de cuota.
Los fallos reales devuelven código distinto de cero. Las omisiones de intervalo
son normales. El temporizador de carruseles revisa cada 15 minutos entre 12:05 y
20:50 hora Chile, respetando las ventanas y 48 horas desde la publicación anterior:
la espera deja de perder un día entero por unos minutos de desfase.

Pruebas: selección canónica, aprobación persistente, archivo cambiado, cuota,
reservas concurrentes, historial idempotente y publicación desde imagen principal.
No se publican mensajes durante las pruebas.


## Validaci?n de layout sin llamadas pagadas

`python scripts/check_instagram_layouts.py --output logs/layout_check.json` consulta
servicios con proveedores y compone im?genes sint?ticas en una carpeta temporal.
No publica, no llama a OpenAI ni modifica el registro de im?genes o presupuesto.
El comando termina con c?digo 1 si alg?n layout falla o no hay servicios.
Para auditor?a offline se puede usar `--registry-snapshot ruta/service_images.json`.
Debe ejecutarse con las fuentes del contenedor Linux antes de cambiar la plantilla.

La plantilla v7 asigna regiones fijas a t?tulo, descripci?n, tarjetas y contacto;
mide las letras reales (incluidos bearings de fuentes Linux), ajusta la tipograf?a
sin truncar el texto y rechaza textos imposibles antes de comprar im?genes.
Si la fuente pagada ya se gener? y luego falla el procesamiento local, se conserva
y el servicio queda en `needs_review`: no se compra otra fuente autom?ticamente.
La correcci?n no recompone los PNG aprobados existentes. La revisi?n visual de
2026-10-18 se documenta en `docs/revision_imagenes_2026-10-18.md` y su JSON
identifica cada archivo por SHA-256 para evitar aplicar una revisi?n a otra imagen.
