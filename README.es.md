<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a> · <a href="README.fr.md">Français</a> · <b>Español</b>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/brand/wordmark-on-dark.svg">
    <img alt="Reelfold" src="docs/brand/wordmark-on-light.svg" width="340">
  </picture>
</p>

<p align="center"><b>Una grabación, todos los cortes, para cada plataforma.</b><br>
Una herramienta de vídeo gratuita y de código abierto para quien edita por lotes.</p>

<p align="center">
  <a href="https://reelfold.com/docs/es/">Documentación</a> ·
  <a href="https://github.com/zyziyun/reelfold/releases/latest">Descargar para macOS</a> ·
  <a href="https://reelfold.com">reelfold.com</a> ·
  <a href="LICENSE">MIT</a>
</p>

- **Descríbelo y suelta el material.** Di lo que quieres con tus palabras; Reelfold elige los clips y los edita en
  paralelo en tu propio Mac.
- **Revisa solo las excepciones.** Cada archivo se comprueba automáticamente; tú solo miras lo que queda marcado.
- **Cada plataforma con su formato.** 20 plataformas, cada una con su tamaño, subtítulos, volumen, portada y texto. La
  publicación es asistida: Reelfold rellena la página de subida y tú pulsas publicar.

![Vídeo a cámara · clips de una clase · historia con fotos · vlog al ritmo · pódcast con caras ocultas · vídeo explicativo](docs/demos/strip.jpg)

## Instalación

**App para Mac** (Apple Silicon, gratuita). Se descarga desde
[Releases](https://github.com/zyziyun/reelfold/releases/latest) en cuanto salga la primera versión (muy pronto);
mientras tanto, [compílala desde el código fuente](https://reelfold.com/docs/es/start/install-mac/).

**Skill de Claude Code** (el mismo motor, todavía llamado `video-studio`):

```bash
git clone https://github.com/zyziyun/reelfold ~/.claude/skills/video-studio
~/.claude/skills/video-studio/install.sh
cp ~/.claude/skills/video-studio/persona.example.yaml ~/.claude/skills/video-studio/persona.local.yaml
```

La IA funciona con lo que ya tienes: tu sesión de Claude Code o Codex, tu propia clave de API o un modelo local.

**Documentación → [reelfold.com/docs/es](https://reelfold.com/docs/es/)**

## Pídelo así

| Quieres | Di algo como |
|---|---|
| Un vídeo a cámara bien ajustado | «Quita las pausas, las muletillas y las repeticiones, acelera a 1,1×, añade subtítulos y una barra de progreso, y expórtalo para TikTok y Shorts» |
| Una clase en clips verticales | «Corta esta clase de 70 minutos en 3 episodios verticales, una idea por episodio, con zoom al código, portadas y textos para publicar» |
| Un clip de pódcast | «Busca el mejor minuto de este pódcast de Zoom, oculta la cara y el nombre del invitado, en vertical» |
| Un vlog de viaje con ritmo | «Haz un vlog rápido, al ritmo de la música, con estas fotos y vídeos de Disneyland: días, lugares, efectos de sonido, 9:16» |
| Un vídeo, varias plataformas | «Expórtalo para Instagram Reels, TikTok y YouTube Shorts, cada uno con sus zonas seguras y su volumen» |

Más ejemplos: [ejemplos de peticiones](https://reelfold.com/docs/es/examples/).

## Más información

[Primeros pasos](https://reelfold.com/docs/es/start/what-is-reelfold/) ·
[Guías](https://reelfold.com/docs/es/guides/talking-head/) ·
[Conceptos](https://reelfold.com/docs/es/concepts/projects/) ·
[Referencia](https://reelfold.com/docs/es/reference/) ·
[Solución de problemas](https://reelfold.com/docs/es/help/troubleshooting/) ·
[Contribuir](https://reelfold.com/docs/es/contributing/)

## Licencia

MIT, incluidas la app (`apps/desk`), la web (`apps/site`) y la documentación (`apps/docs`). Las fuentes y los modelos se
descargan al instalar, con sus propias licencias (SIL OFL 1.1, Apache-2.0). Los flujos de HTML a vídeo usan
[HyperFrames](https://hyperframes.heygen.com).

Antes se llamaba **video-studio** (el skill y el motor) y **Daycut** (la app). Las instalaciones existentes en
`~/.claude/skills/video-studio` siguen funcionando; apúntalas a la nueva dirección con
`git -C ~/.claude/skills/video-studio remote set-url origin https://github.com/zyziyun/reelfold`.
