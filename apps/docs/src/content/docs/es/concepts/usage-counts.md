---
title: 'Privacidad: qué envía Reelfold'
description: La app para Mac puede compartir recuentos de uso anónimos, solo si lo activas. Cada campo que envía, cómo desactivarlo y cómo borrar los datos.
---

La app de Reelfold para Mac puede enviarnos unos pocos recuentos anónimos, por ejemplo «terminó un lote de 12 clips». Está **desactivado salvo que lo actives** (en el primer inicio o en **Ajustes › General › Privacidad**). Desactivado, no se envía nada y no se crea ningún identificador.

**Campos enviados** (por HTTPS a `https://t.reelfold.com/api/v1/ping`): un identificador aleatorio creado en tu ordenador (reemplazable), la versión de la app, el sistema y el procesador, el idioma de la app, el nombre del evento (`app_open` como mucho una vez al día, `first_batch_done`, `batch_done`, `export_done`, `publish_package`), el día (sin hora) y unos pocos números enteros (clips, formatos, minutos, plataformas). Nunca nombres de archivo, rutas, textos, transcripciones, instrucciones, claves ni vídeo.

**En el servidor**: la dirección IP no se guarda ni se registra; los campos desconocidos se descartan; los eventos se borran a los 13 meses (solo quedan totales diarios sin identificador).

**Desactivar**: Ajustes › General › Privacidad. **Borrar**: el botón «Borrar mis datos de uso» elimina todo lo que envió tu identificador y crea uno nuevo.

Detalles completos (en inglés): [Privacy: what Reelfold sends](/docs/concepts/usage-counts/).
