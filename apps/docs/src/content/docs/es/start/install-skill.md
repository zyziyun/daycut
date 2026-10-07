---
title: Instala el skill de Claude Code
description: Instala el skill video-studio para Claude Code con tres comandos, descubre qué descarga install.sh, usa Whisper sin conexión, actualízalo y verifícalo.
---

El skill de Claude Code es el motor de Reelfold empaquetado para [Claude Code](https://claude.com/claude-code). Una vez instalado, le hablas a Claude de tu material («quita las pausas y acelera a 1,1×») y el skill le indica qué workflow ejecutar, con scripts probados y una biblioteca compartida detrás. El skill se sigue llamando `video-studio`.

## Requisitos

**Imprescindible**

- Claude Code
- Python 3.10+
- `ffmpeg` (`brew install ffmpeg` o `apt install ffmpeg`)

**Opcional, según el workflow**

| Si quieres | Instala |
|---|---|
| Videos explicativos y reediciones promocionales (HyperFrames) | Node 18+ con `npx hyperframes` |
| Portadas y diapositivas en HTML | Chrome / Chromium, o Playwright |
| Narración con IA (OpenAI TTS) | `OPENAI_API_KEY` |
| Catálogo de música | La CLI de HeyGen |
| Mejor detección del ritmo | `librosa` |
| Fotos HEIC | `pillow-heif` (en macOS se usa `sips` como alternativa) |
| Tu propia voz clonada | `mlx-audio` y un modelo Qwen3-TTS |

## Instalación

Ejecuta estas tres líneas:

```bash
git clone https://github.com/zyziyun/reelfold ~/.claude/skills/video-studio
~/.claude/skills/video-studio/install.sh
cp ~/.claude/skills/video-studio/persona.example.yaml ~/.claude/skills/video-studio/persona.local.yaml
```

1. El clon deja el skill donde Claude Code busca los skills.
2. `install.sh` instala las dependencias de Python y descarga fuentes y modelos (ver más abajo). Puedes volver a ejecutarlo sin problema: se omiten los archivos que ya existen.
3. `persona.local.yaml` guarda tus preferencias: velocidades por defecto, volumen, colores de marca, reglas para títulos, hashtags, correcciones de términos, fuentes y qué IA hace cada tarea. Git lo ignora, así que tus ajustes nunca acaban en el repositorio. Todas las opciones: [opciones de persona.yaml](/docs/es/reference/persona/).

Después, abre una sesión nueva de Claude Code para que cargue el skill.

## Qué descarga install.sh

Todo va a una sola carpeta de caché, `~/.cache/video-studio` (define `VSTUDIO_CACHE` para moverla):

| Qué | Dónde | Licencia |
|---|---|---|
| Noto Sans SC, Noto Serif SC, STIX Two Text, JetBrains Mono | `fonts/` | SIL OFL 1.1 |
| MediaPipe face landmarker, selfie segmenter, selfie multiclass segmenter (los usa el retoque) | `models/` | Apache-2.0 |
| Los paquetes de Python de `requirements.txt`, más `mlx-whisper` en Apple Silicon o `faster-whisper` en otros equipos | tu entorno de Python | varias |

Al terminar, te avisa si falta `ffmpeg` o `npx`. Define `SKIP_PIP=1` para saltarte los paquetes de Python y descargar solo fuentes y modelos.

La misma caché guarda también transcripciones, tomas de TTS y otros resultados reutilizables. La app para Mac usa esta carpeta, así que nada se descarga dos veces.

## Modelos de Whisper y uso sin conexión

La primera transcripción descarga un modelo de Whisper en la caché de Hugging Face (`~/.cache/huggingface/hub`, o `$HF_HOME/hub`):

- `mlx-community/whisper-large-v3-turbo` para mlx-whisper (Apple Silicon)
- `large-v3-turbo` (`Systran/faster-whisper-large-v3-turbo`) para faster-whisper

Para usar un modelo que ya tienes, o para trabajar en un equipo sin conexión, indícaselo al motor:

```bash
export VSTUDIO_WHISPER_MLX=/path/to/whisper-large-v3-turbo-mlx    # MLX folder (config.json + weights) or an HF repo id
export VSTUDIO_WHISPER_FW=/path/to/faster-whisper-large-v3-turbo  # CTranslate2 folder, or a size name such as small
export HF_HUB_OFFLINE=1                                           # never touch the network
```

El motor de transcripción se elige automáticamente: mlx-whisper; si no está, faster-whisper; y si tampoco, OpenAI `whisper-1` cuando `OPENAI_API_KEY` está definida.

## Elige tu IA

Cada paso con IA (planificar fragmentos, corregir subtítulos, el glosario, el texto de publicación) puede ejecutarse con tu Claude Code o Codex CLI con sesión iniciada, sin clave de API, con una clave de API o con un modelo local. Configúralo en `persona.local.yaml`:

```yaml
llm:
  default: {provider: claude-code}
```

Enrutamiento por tarea, alternativas y costos: [Proveedores de IA](/docs/es/concepts/ai-providers/).

## Verifica la instalación

Mira qué proveedores de IA y motores de transcripción y TTS tiene este equipo (no se envía nada):

```bash
cd ~/.claude/skills/video-studio/lib && python3 -m vstudio.llm providers
```

Si quieres, ejecuta las pruebas con medios sintéticos (requiere `pytest`; sin red):

```bash
cd ~/.claude/skills/video-studio && python3 -m pytest tests -q
```

## Cambio desde la URL antigua del repositorio

Si clonaste el skill cuando se publicaba como video-studio, apúntalo al nuevo repositorio. El nombre de la carpeta, el del skill y el paquete `vstudio` no cambian:

```bash
git -C ~/.claude/skills/video-studio remote set-url origin https://github.com/zyziyun/reelfold
```

Las versiones antiguas escribían parte de la caché en `~/.cache/vstudio`. Se sigue leyendo, pero ya no se escribe en ella; bórrala cuando ya no la necesites.

## Actualiza

```bash
git -C ~/.claude/skills/video-studio pull
~/.claude/skills/video-studio/install.sh
```

Al volver a ejecutar `install.sh` se instalan las nuevas dependencias de Python y las fuentes o modelos nuevos. Tu `persona.local.yaml` no se toca.

## Relacionado

- [Tu primer proyecto](/docs/es/start/first-project/)
- [Ejemplos de peticiones](/docs/es/examples/)
- [Referencia de la CLI](/docs/es/reference/cli/)
- [Instala la app para Mac](/docs/es/start/install-mac/)
