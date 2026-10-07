---
title: Ejemplos de peticiones
description: Peticiones que funcionan bien en Reelfold, agrupadas por caso de uso, desde quitar pausas de un clip a cámara hasta cortar una clase, procesar lotes y retocar.
---

Le hablas a Reelfold como le darías indicaciones a un editor. Estas peticiones funcionan en el cuadro de peticiones de la app para Mac y con el skill de Claude Code, y puedes escribirlas en español. Señala tus archivos (suéltalos en la app o nómbraselos a Claude) y ajusta los detalles.

## Cómo formular una petición

Una buena petición indica tres cosas:

1. **El material**: «este clip hablando a cámara», «esta clase de 70 minutos», «estas tomas de dron y estas fotos».
2. **El resultado**: cuántos clips, de qué duración y qué llevan (subtítulos, paneles de notas, portada, texto de publicación).
3. **La plataforma**: TikTok, YouTube Shorts, Instagram Reels, Xiaohongshu, Douyin, etc. La plataforma define el lienzo, las zonas seguras, el volumen y los límites de texto, así que casi nunca necesitas indicar tamaños.

Lo que no indiques sale de tus valores predeterminados (tu persona) o del propio material. Cuando algo no se puede dar por supuesto y cambiaría el resultado, como qué cara ocultar o si va con narración o con música, el planificador te pregunta antes de empezar.

## Hablando a cámara

<div class="rf-prompts">

| Si quieres | Di algo como | Workflow |
|---|---|---|
| Un short ágil | «Haz más ágil este clip hablando a cámara: quita las pausas, las muletillas y las repeticiones, acelera a 1,1×, añade subtítulos, paneles de notas y una barra de progreso, exporta para TikTok» | [talkinghead](/docs/es/reference/workflows/talkinghead/) |
| Un gancho inicial | «Abre con tres frases destacadas del clip, haz que las palabras clave salten en pantalla y prepara versiones para TikTok y Shorts» | [talkinghead](/docs/es/reference/workflows/talkinghead/) |
| Un estilo más dinámico | «Cambia al estilo de cortes rápidos: zooms de golpe, palabras que saltan, sellos y efectos de sonido» | [talkinghead](/docs/es/reference/workflows/talkinghead/) |
| Retoque | «Suaviza mi piel y añade un maquillaje ligero y natural; afina un poco la cara en la portada» | [talkinghead](/docs/es/reference/workflows/talkinghead/), [cover](/docs/es/reference/workflows/cover/) |
| Material de apoyo | «Cuando menciono el panel de control, corta a esta grabación de pantalla sin interrumpir el audio» | [talkinghead](/docs/es/reference/workflows/talkinghead/) |

</div>

## Solo limpieza de voz

<div class="rf-prompts">

| Si quieres | Di algo como | Workflow |
|---|---|---|
| Voz limpia y nada más | «Quita las pausas, los “eh” y las repeticiones de esta grabación, y haz una lista de lo que no tengas claro para que lo confirme» | [cleanup](/docs/es/reference/engine/cleanup/) |
| Limpiar una edición exportada | «Exporté esto desde CapCut. Quita los silencios y las muletillas, arregla el primer fotograma negro y ajusta el volumen» | [polish](/docs/es/reference/workflows/polish/) |
| Una pasada suave | «Solo una limpieza ligera: acorta las pausas largas pero conserva mis respiraciones y el ritmo natural» | [cleanup](/docs/es/reference/engine/cleanup/) |

</div>

## Grabaciones largas, cursos y llamadas

<div class="rf-prompts">

| Si quieres | Di algo como | Workflow |
|---|---|---|
| Episodios de una clase | «Corta esta clase de 70 minutos en 3 shorts verticales, una idea cada uno, con zoom al código, portadas y texto de publicación» | [longform-to-short](/docs/es/reference/workflows/longform-to-short/) |
| Clips verticales de un webinar | «Corta este webinar en 10 clips verticales de menos de un minuto para TikTok y Shorts, con franja de título arriba y un recorte de pantalla legible» | [longform-to-short](/docs/es/reference/workflows/longform-to-short/) |
| Un video de curso limpio | «Convierte esta grabación de pantalla en un video de curso: oculta la barra del navegador, añade capítulos y subtítulos, y cambia la voz de los alumnos» | [longform-to-short](/docs/es/reference/workflows/longform-to-short/) |
| Un clip de pódcast o llamada | «Encuentra el minuto más interesante de este pódcast grabado en Zoom, oculta la cara del invitado, difumina los nombres en pantalla, en vertical» | [call-clips](/docs/es/reference/workflows/call-clips/) |
| Clips de una edición terminada | «Saca la parte sobre proyectos personales, hacia el final de este video, como un short aparte» | [talkinghead](/docs/es/reference/workflows/talkinghead/) |

</div>

## Promos, historias y vlogs

<div class="rf-prompts">

| Si quieres | Di algo como | Workflow |
|---|---|---|
| Una promo premium | «Pantalla dividida, yo a la izquierda y las capturas a la derecha como tarjetas 3D con resaltados; congela 2 segundos en el prompt y amplíalo; luego un resumen de lo mejor a 1,1×» | [promo-recut](/docs/es/reference/workflows/promo-recut/) |
| Una historia con fotos | «Haz una historia con estética de cine de autor con estas fotos de una exposición: solo música, tres capítulos, revelados de antes y después, una lupa y aspecto de película» | [photo-story](/docs/es/reference/workflows/photo-story/) |
| Una historia narrada | «Convierte estas fotos de viaje y este guion en una historia narrada con mi propia voz, en 9:16» | [photo-story](/docs/es/reference/workflows/photo-story/) |
| Un vlog divertido | «Monta un vlog rápido, al ritmo de la música, con estos clips y fotos de Disneyland: rótulos de DÍA, marcadores de lugar, efectos de sonido, textos que saltan, en 9:16» | [vlog](/docs/es/reference/workflows/vlog/) (divertido) |
| Un vlog tranquilo | «Haz un vlog tranquilo con estas tomas de dron: corrección de color, cámara lenta, música suave» | [vlog](/docs/es/reference/workflows/vlog/) (tranquilo) |

</div>

## Videos explicativos y video con IA

<div class="rf-prompts">

| Si quieres | Di algo como | Workflow |
|---|---|---|
| Un video explicativo | «Haz un video explicativo al estilo de 3Blue1Brown sobre cómo funciona CUDA en una GPU, en short vertical, con subtítulos bilingües» | [explainer](/docs/es/reference/workflows/explainer/) |
| Explicativos a partir de un documento | «Haz cinco videos explicativos cortos a partir de las secciones de este PDF» | [explainer](/docs/es/reference/workflows/explainer/) |
| Un episodio generado con IA | «Haz el episodio 3 de mi miniserie con IA a partir de este guion con Kling, mantén los mismos personajes, presupuesto de 200 créditos» | [ai-video](/docs/es/reference/workflows/ai-video/) |

</div>

## Portadas, empaquetado y plataformas

<div class="rf-prompts">

| Si quieres | Di algo como | Workflow |
|---|---|---|
| Un paquete de publicación | «Haz una portada, un título, una descripción y etiquetas para este video, para YouTube e Instagram» | [cover](/docs/es/reference/workflows/cover/), [polish](/docs/es/reference/workflows/polish/) |
| Solo una miniatura | «Haz una miniatura de YouTube a partir de este clip con un título grande en dos líneas» | [cover](/docs/es/reference/workflows/cover/) |
| Varias plataformas | «Exporta este video para Instagram Reels, TikTok y YouTube Shorts, cada uno con su zona segura y su volumen» | [export](/docs/es/reference/cli/#vstudioexport) |
| Primero el guion | «Escribe un guion de 90 segundos sobre este tema para Shorts y después dame un ejercicio de pronunciación para las palabras difíciles» | [preproduction](/docs/es/reference/workflows/preproduction/) |

</div>

## Lotes y programación

<div class="rf-prompts">

| Si quieres | Di algo como | Workflow |
|---|---|---|
| Un lote completo | «Convierte esta carpeta de 30 clips hablando a cámara en shorts limpios para TikTok y Shorts, y muéstrame solo los que no pasen algún control» | [batch](/docs/es/reference/workflows/batch/) |
| Una semana a partir de una grabación | «Corta este directo en 14 clips de menos de 60 segundos y prepáralos para TikTok e Instagram Reels» | [batch](/docs/es/reference/workflows/batch/) |
| Un calendario de publicación | «Programa estos clips a dos por día a partir del lunes, a las 12:00 y a las 19:00» | [batch](/docs/es/reference/workflows/batch/) |

</div>

Nada se publica por ti. Una programación te da un calendario de publicación y los archivos empaquetados; cuando publicas, la app para Mac rellena la página de subida y tú pulsas publicar. Consulta [Programación y publicación](/docs/es/guides/scheduling-publishing/).

## Ediciones posteriores de un clip terminado

Cualquier clip terminado se puede volver a editar con tus palabras. En la app para Mac puedes seleccionar antes un tramo en la línea de tiempo o un subtítulo, y entonces «esto» se refiere a tu selección.

<div class="rf-prompts">

| Si quieres | Di algo como | Workflow |
|---|---|---|
| Recortar y acelerar | «Recorta los dos primeros segundos y acelera todo a 1,2×» | [output edit](/docs/es/reference/engine/output-edit/) |
| Quitar un tramo | «Quita esta parte» (con un tramo seleccionado) | [output edit](/docs/es/reference/engine/output-edit/) |
| Subtítulos | «Haz los subtítulos más grandes y resalta las palabras clave en amarillo» | [output edit](/docs/es/reference/engine/output-edit/) |
| Otro estilo | «Cambia al tema editorial» | [output edit](/docs/es/reference/engine/output-edit/) |
| Efectos | «Añade una palabra que salte en “tres pasos” en el 0:12 y un rótulo de capítulo en el 0:40» | [output edit](/docs/es/reference/engine/output-edit/) |
| Otro formato | «Añade una versión 16:9 para YouTube» | [output edit](/docs/es/reference/engine/output-edit/) |
| Deshacer un cambio | «Deshaz el cambio de música, pero conserva todo lo que vino después» | [output edit](/docs/es/reference/engine/output-edit/) |
| Todos los clips a la vez | «Quita la etiqueta de la serie de todos los clips» | [output edit](/docs/es/reference/engine/output-edit/) |

</div>

## Consejos para las peticiones de seguimiento

- **Cambia el plan antes de que se ejecute.** Las indicaciones cortas funcionan bien: «solo TikTok», «menos de 60 segundos cada uno», «5 clips», «velocidad 1,2×», «velocidad original», «en inglés», «más limpio» o «limpieza más ligera», «oculta las caras» o «no ocultes las caras», «añade un gancho» o «sin gancho», «horizontal» o «vertical», «al ritmo» o «tranquilo». El plan conserva todo lo que no mencionaste.
- **Un cambio cada vez** una vez hecho el clip. Cada petición es un paso que se puede deshacer, así que es fácil comparar y volver atrás.
- **Señala el momento.** Da un tiempo («en el 0:12»), cita las palabras («donde digo “tres pasos”») o selecciona el tramo en la app.
- **El texto incrustado en el video original** (una marca de agua o subtítulos que ya trae tu archivo fuente) no se puede cambiar de estilo ni eliminar con una edición. Reelfold te avisa cuando un clip tiene que volver a renderizarse desde su fuente.
- **Di lo que te gustó.** «Deja los subtítulos como están, cambia solo la portada» evita que una petición toque más de lo que querías.

## Relacionado

- [Tu primer proyecto](/docs/es/start/first-project/)
- [Recetas](/docs/es/concepts/recipes/)
- [Ediciones posteriores](/docs/es/concepts/output-edits/)
- [Referencia de workflows](/docs/es/reference/)
