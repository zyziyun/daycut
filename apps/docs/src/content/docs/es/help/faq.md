---
title: Preguntas frecuentes
description: Respuestas sobre el precio y la licencia de Reelfold, Windows, qué sale de tu Mac, qué IA necesitas, idiomas, fuentes propias, publicación y uso comercial.
---

## ¿Reelfold es gratis?

Sí. Reelfold es de código abierto con licencia MIT: el motor, el skill de Claude Code, la app para Mac y el sitio web. Solo pagas a tu proveedor de IA, si usas una API de pago. Con un modelo local, o con tu Claude Code o Codex CLI con sesión iniciada, no hay factura de API. En una prueba interna, 96 archivos sacados de una clase de 72 minutos costaron 0,73 USD en llamadas a la API.

## ¿Hay una descarga para Mac? ¿Y para Windows?

La primera versión para macOS (Apple Silicon) llegará pronto a [GitHub Releases](https://github.com/zyziyun/reelfold/releases/latest). Mientras tanto, compílala desde el código fuente: consulta [Instala la app para Mac](/docs/es/start/install-mac/). Windows llegará más adelante. El motor en sí es Python y ffmpeg y tiene rutas de código para Windows (faster-whisper, el codificador `h264_mf`), pero la mayoría de las pruebas se hacen en Mac.

## ¿Publica por mí?

No. La publicación es asistida: la app abre la página de subida de la plataforma en su navegador integrado, coloca el video y escribe el título, el texto y las etiquetas. Tú lo revisas y pulsas publicar. La app nunca hace clic en publicar ni publica según un calendario. Consulta [Publicación](/docs/es/concepts/publishing/).

## ¿Qué sale de mi Mac?

Tu video y tu audio se quedan en tu Mac: la transcripción y el renderizado se ejecutan en local. Al proveedor de IA que elegiste solo va lo que necesita cada paso de IA: solo texto, como la transcripción, los subtítulos y los títulos. Con un modelo local, no sale nada. Hay dos excepciones que activas tú: el motor de transcripción de OpenAI envía el audio y la narración de OpenAI envía el texto del guion. Consulta [Privacidad](/docs/es/concepts/privacy/).

## ¿Qué IA necesito?

Cualquiera de estas, para cada tarea:

- Tu propio **Claude Code** o **Codex** CLI con sesión iniciada (sin clave de API).
- Una **clave de API**: Anthropic, OpenAI, DeepSeek, Qwen, Kimi, GLM, OpenRouter, Gemini, ElevenLabs.
- Un **modelo local**: Ollama, LM Studio, vLLM, llama.cpp, whisper local.

Sin ninguna IA, la planificación de fragmentos recurre a un planificador basado en reglas. Consulta [Proveedores de IA](/docs/es/concepts/ai-providers/).

## ¿Necesito Claude Code?

Para la app para Mac, no: sirve cualquier proveedor de los de arriba. La versión skill de Reelfold se ejecuta dentro de Claude Code, así que para esa sí. La receta de videos explicativos también necesita un agente de IA (Claude Code o Codex) para escribir sus escenas animadas.

## ¿En qué se diferencia de Opus Clip, Descript o CapCut?

Son buenas herramientas con otro enfoque. Opus Clip es un servicio en la nube para encontrar clips en videos largos, Descript es un editor basado en la transcripción y CapCut es un editor de línea de tiempo con plantillas. Reelfold está pensado para quienes editan en tanda:

- **Primero lo local.** Tu material se procesa en tu propio Mac.
- **Lote primero, luego revisas las excepciones.** Muchos clips se procesan en paralelo, cada archivo se revisa automáticamente y tú miras lo que se marcó.
- **Una grabación, todas las plataformas.** Lienzo, subtítulos, volumen, portada y texto adaptados a cada una de las 20 plataformas.
- **Usa tu propia IA**, o ninguna.
- **Código abierto** (MIT): puedes leerlo, cambiarlo y ampliarlo.
- **Publicación asistida** que te deja el último clic a ti.

## ¿Qué idiomas admite?

La app está en inglés, chino simplificado y francés. En cuanto al contenido, el chino y el inglés son los más desarrollados: detección de muletillas, reglas de subtítulos, subtítulos bilingües y texto de publicación en ambos idiomas. Whisper transcribe muchos otros idiomas, español incluido, pero esos flujos están menos probados.

## ¿Puedo usar mis propias fuentes y colores de marca?

Sí. En `persona.local.yaml`, apunta cualquier rol de fuente (`cjk`, `cjk-bold`, `serif`, `mono`…) a tu propio archivo y define tus colores de marca, el tema de los paneles, los hashtags predeterminados y las reglas para títulos. Los estudios pueden tener una marca distinta por cliente. Consulta [Temas](/docs/es/concepts/themes/) y la [referencia de persona](/docs/es/reference/persona/).

## ¿Puedo usarlo para trabajo comercial?

La licencia MIT permite el uso comercial, incluido el trabajo para clientes. Hay dos cosas que debes comprobar tú: los términos de tu proveedor de IA (las CLI de suscripción como Claude Code y Codex están pensadas para uso personal; usa una clave de API o un modelo local cuando los términos lo exijan) y las licencias de las fuentes, la música y el material que uses. El motor opcional de recorte RVM para portadas tiene licencia GPL-3.0 y solo se descarga si lo eliges.

## ¿Tengo que etiquetar el contenido generado con IA?

Sigue las normas de cada plataforma. Las plataformas chinas exigen declarar el contenido generado con IA (normas vigentes desde el 1 de septiembre de 2025), y YouTube, TikTok y Meta tienen sus propias etiquetas de IA. Reelfold nunca las marca por ti; la lista de comprobación de publicación y las notas de entrega a clientes te lo recuerdan. El workflow de video con IA planifica una etiqueta por plataforma. Consulta la [referencia de publicación](/docs/es/reference/engine/publishing/).

## ¿Qué pasó con video-studio y Daycut?

Reelfold es el nuevo nombre. El skill y el motor de código abierto se publicaron como **video-studio**, y la app de escritorio se llamaba **Daycut** (日剪). El skill se sigue llamando `video-studio`, el paquete de Python sigue siendo `vstudio` y las instalaciones existentes en `~/.claude/skills/video-studio` siguen funcionando. Solo se movió el repositorio, a [github.com/zyziyun/reelfold](https://github.com/zyziyun/reelfold).

## Relacionado

- [Qué es Reelfold](/docs/es/start/what-is-reelfold/)
- [Solución de problemas](/docs/es/help/troubleshooting/)
- [Contribuir](/docs/es/contributing/)
