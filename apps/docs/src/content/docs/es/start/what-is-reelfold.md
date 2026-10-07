---
title: Qué es Reelfold
description: Reelfold (千剪) es una herramienta de video gratuita, abierta y local que convierte una grabación en todos los cortes para cada plataforma. Así funciona.
---

Reelfold (千剪) convierte una sola grabación en la tanda de clips que vas a publicar esta semana. Describes lo que quieres con tus propias palabras y sueltas el material. Reelfold planifica los clips, los edita en tu propio Mac, revisa cada archivo y solo te muestra lo que necesita tu atención. Cada plataforma recibe su propia exportación, portada, título, descripción y etiquetas.

Es gratis, tiene licencia MIT y es de código abierto. El código está en [github.com/zyziyun/reelfold](https://github.com/zyziyun/reelfold).

## Dos formas de usarlo

Las dos versiones usan el mismo motor, así que una receta que funciona en una también funciona en la otra.

| | Reelfold para Mac | El skill de Claude Code |
|---|---|---|
| Qué es | Una app de escritorio (`apps/desk`, Electron) | El motor como skill para [Claude Code](https://claude.com/claude-code) (la raíz del repositorio) |
| Cómo le hablas | Un cuadro de peticiones en **Home**: «What are we making today?» | Con lenguaje natural, a Claude, en tu terminal |
| Ideal para | Lotes en un tablero, una cuadrícula de revisión, publicación asistida | Trabajar dentro de una carpeta, automatizar con scripts, ediciones puntuales |
| Plataforma | macOS en Apple Silicon (Windows más adelante) | Donde funcionen Claude Code, Python 3.10+ y ffmpeg |
| Instalación | [Instala la app para Mac](/docs/es/start/install-mac/) | [Instala el skill](/docs/es/start/install-skill/) |

En el skill, `SKILL.md` dirige cada petición a un workflow (`workflows/<name>/WORKFLOW.md`) con scripts probados y una biblioteca de Python compartida, `vstudio`.

## Cómo avanza un trabajo

1. **Describe.** Di qué estás haciendo y añade los archivos: un clip hablando a cámara, una clase de 70 minutos, una carpeta con tomas de un viaje, un guion. Por ejemplo: «Corta esta clase en 10 clips verticales para TikTok y Shorts, de menos de un minuto cada uno».
2. **Planifica.** Reelfold analiza el material y propone un plan: qué workflow, cuántos clips, qué plataformas, cuánto tardará y cuánto puede costar. Lo cambias con tus palabras («solo 3 clips», «nada en 9:16») antes de que empiece nada.
3. **Ejecuta el lote.** Las ediciones se hacen en tu Mac, varias a la vez. Primero sale un clip piloto para que compruebes el estilo antes de producir el resto.
4. **Revisa.** Cada archivo pasa controles automáticos (palabras perdidas, fotogramas congelados, volumen, duración). Solo ves lo que se marcó, más las decisiones que te tocan a ti: qué cortes de muletillas aceptar, qué arranque usar, qué portada elegir.
5. **Publica.** La publicación es asistida. La app para Mac abre la página de subida de cada plataforma en su navegador integrado y rellena el archivo y el texto. Tú pulsas publicar. Reelfold nunca publica por su cuenta.

Más sobre cada paso: [Proyectos](/docs/es/concepts/projects/), [Lotes y revisión](/docs/es/concepts/batch-review/), [Publicación](/docs/es/concepts/publishing/).

## Para quién es

- **Creadores que producen en tanda**: graban una vez y publican toda la semana, con el formato, la duración y el volumen que espera cada plataforma.
- **Podcasters y entrevistadores** que quieren sacar muchos clips de una conversación larga, con la cara de los invitados oculta cuando haga falta.
- **Docentes y creadores de cursos** que cortan clases y webinars en clips verticales o episodios.
- **Creadores que hablan a cámara (口播)** que quieren eliminar pausas, muletillas y repeticiones, con subtítulos, paneles de notas y portada.
- **Estudios** que llevan lotes de varios clientes en paralelo, cada uno con su estilo y su glosario.

## Qué se ejecuta en tu Mac

La transcripción, los cortes, los efectos, el renderizado y los controles de calidad se ejecutan en local. La IA la pones tú: tu Claude Code o Codex CLI con sesión iniciada (sin clave de API), una clave de API (Anthropic, OpenAI, DeepSeek, Qwen, Kimi, GLM, OpenRouter, Gemini, ElevenLabs) o un modelo local (Ollama, LM Studio, vLLM, llama.cpp, whisper local).

Cuando se usa un modelo de IA, solo recibe texto (transcripción, subtítulos y títulos), nunca tu video ni tu audio. En una prueba interna, una clase de 72 minutos se convirtió en 24 clips para 4 plataformas (96 archivos) por 0,73 USD en costo de API, unos 0,03 USD por clip. Consulta [Proveedores de IA](/docs/es/concepts/ai-providers/) y [Privacidad](/docs/es/concepts/privacy/).

## Antes video-studio y Daycut

Reelfold es el nuevo nombre del proyecto. El skill y el motor se publicaron como **video-studio**, y la app de escritorio se llamaba **Daycut** (日剪). Algunos nombres no cambian para que las instalaciones existentes sigan funcionando:

- el skill de Claude Code se sigue llamando `video-studio` y se instala en `~/.claude/skills/video-studio`
- el paquete de Python sigue siendo `vstudio`
- solo cambió la URL del repositorio, ahora `github.com/zyziyun/reelfold`

## Relacionado

- [Instala la app para Mac](/docs/es/start/install-mac/)
- [Instala el skill de Claude Code](/docs/es/start/install-skill/)
- [Tu primer proyecto](/docs/es/start/first-project/)
- [Ejemplos de peticiones](/docs/es/examples/)
