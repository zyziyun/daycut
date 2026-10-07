---
title: Resumen de la referencia
description: Qué cubre cada página de referencia de Reelfold, de la CLI, las opciones de persona y las plataformas a los 13 workflows y las notas del motor.
---

La sección de referencia es la capa de detalle que hay debajo de las guías: cada comando, opción, valor de plataforma y procedimiento de workflow. Estas páginas se generan a partir de los archivos del [repositorio de Reelfold](https://github.com/zyziyun/reelfold) (los perfiles y catálogos del motor, los procedimientos `WORKFLOW.md` y las notas de `references/`), así que coinciden con el código. Están escritas en inglés.

Si estás empezando, ve primero a las [guías](/docs/es/guides/talking-head/) y a los [ejemplos de peticiones](/docs/es/examples/); vuelve aquí cuando necesites el valor o la opción exactos.

## Referencia principal

| Página | Qué cubre |
|---|---|
| [CLI](/docs/es/reference/cli/) | Los comandos del motor (`python -m vstudio.*`): intake, project, batch, cleanup, export, reframe, platform, effects, llm, retouch |
| [Opciones de persona.yaml](/docs/es/reference/persona/) | Todas las opciones de `persona.local.yaml`: velocidades, volumen, colores de marca y tema, ajustes por plataforma, etiquetas, reglas de tono, correcciones de términos, fuentes, enrutamiento de la IA |
| [Especificaciones de plataformas](/docs/es/reference/platforms/) | El perfil de cada plataforma: lienzo, tamaños de portada, duración, límites de título, volumen |
| [Efectos y temas](/docs/es/reference/effects/) | El catálogo de efectos, qué motores renderizan cada efecto y los temas de diseño |
| [Reglas de subtítulos](/docs/es/reference/captions/) | Reglas para subtítulos, rótulos y texto de publicación: nombres, longitud de línea, énfasis, contraste |
| [Mensajes y códigos de error](/docs/es/reference/messages/) | Cada código de mensaje del motor, con su texto y dónde aparece |

## Workflows

Cada workflow es a la vez un procedimiento que sigue el skill y una receta que ejecuta la app para Mac.

| Workflow | Convierte… en… |
|---|---|
| [talkinghead](/docs/es/reference/workflows/talkinghead/) | Una grabación hablando a cámara en un short ágil y subtitulado: limpieza, velocidad, ganchos, paneles de notas, retoque, portada, texto de publicación |
| [promo-recut](/docs/es/reference/workflows/promo-recut/) | Un video a cámara más capturas, enlaces u otro video en una promo premium con pantalla dividida y tarjetas resaltadas |
| [longform-to-short](/docs/es/reference/workflows/longform-to-short/) | Una clase, un webinar o un directo en un video de curso editado y/o en episodios cortos o clips verticales |
| [call-clips](/docs/es/reference/workflows/call-clips/) | Llamadas, entrevistas y pódcast en clips, con caras ocultas y nombres en pantalla difuminados |
| [photo-story](/docs/es/reference/workflows/photo-story/) | Fotos y un guion de narración (o solo música) en una historia llena de efectos |
| [vlog](/docs/es/reference/workflows/vlog/) | Tomas de recurso en un vlog tranquilo con corrección de color o en uno rápido al ritmo de la música |
| [explainer](/docs/es/reference/workflows/explainer/) | Un tema en un video explicativo animado al estilo de 3Blue1Brown, con narración por IA y subtítulos bilingües |
| [polish](/docs/es/reference/workflows/polish/) | Cualquier edición exportada, lista para publicar: fotograma de portada, volumen, velocidad, limpieza opcional |
| [ai-video](/docs/es/reference/workflows/ai-video/) | Un guion o una idea en video generado con IA (Kling, Seedance, MiniMax) dentro de un presupuesto de créditos |
| [cover](/docs/es/reference/workflows/cover/) | Portadas y miniaturas en los tamaños de cada plataforma |
| [slides](/docs/es/reference/workflows/slides/) | Diapositivas cuadradas o a lienzo completo para videos verticales |
| [preproduction](/docs/es/reference/workflows/preproduction/) | Redacción de guiones, revisión del guion por plataforma y ejercicios de pronunciación |
| [batch](/docs/es/reference/workflows/batch/) | Muchos shorts a la vez: plan, piloto, ejecución en paralelo, controles automáticos, revisión, paquetes de publicación |

## Notas del motor

Notas más a fondo sobre cómo funciona el motor compartido. Útiles cuando automatizas el motor, depuras un resultado o contribuyes.

| Página | Tema |
|---|---|
| [Intake](/docs/es/reference/engine/intake/) | Cómo una petición en lenguaje natural y un montón de archivos se convierten en un plan |
| [Proyectos](/docs/es/reference/engine/projects/) | Recetas, elementos, puntos de control, el Inbox, series y el calendario de publicación |
| [Lotes](/docs/es/reference/engine/batch/) | Especificaciones de lote, listas de trabajos, el planificador, controles de calidad, revisión y paquetes |
| [Limpieza de voz](/docs/es/reference/engine/cleanup/) | Pausas, muletillas, repeticiones y tomas repetidas: detección, la respuesta de revisión, verificación |
| [Ediciones posteriores](/docs/es/reference/engine/output-edit/) | Segunda pasada sobre clips terminados: operaciones, ediciones con IA, deshacer y revertir de forma selectiva |
| [Proveedores de IA](/docs/es/reference/engine/providers/) | Cómo dirigir cada tarea de IA a una API, a un modelo local o a tu sesión de Claude Code / Codex |
| [Publicación](/docs/es/reference/engine/publishing/) | Cómo llega una publicación a cada plataforma y por qué nada se publica automáticamente |
| [Reglas de estilo](/docs/es/reference/engine/style-rules/) | Los temas de diseño detrás de las franjas de título, los subtítulos, las notas y las tarjetas |
| [Lista de estética](/docs/es/reference/engine/aesthetics/) | Las comprobaciones que conviene hacer a cualquier corte antes de entregarlo |
| [Sonido](/docs/es/reference/engine/sound/) | Ritmo, colocación de efectos de sonido y niveles |
| [Retoque](/docs/es/reference/engine/retouch/) | Suavizado de piel, maquillaje y remodelado para portadas y video |
| [Procedimiento de video corto](/docs/es/reference/engine/sop-short-video/) | Un short hablando a cámara, del tema a la publicación, de principio a fin |
| [Añadir efectos](/docs/es/reference/engine/adding-effects/) | Cómo añadir un efecto al catálogo y portarlo entre motores de renderizado |
| [Validación](/docs/es/reference/engine/validation/) | Qué se probó con material real y los límites conocidos |

## Relacionado

- [Qué es Reelfold](/docs/es/start/what-is-reelfold/)
- [Ejemplos de peticiones](/docs/es/examples/)
- [Contribuir](/docs/es/contributing/)
