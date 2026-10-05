"""photo-story: photos / short clips + a narration script -> narrated, effect-rich story video.

Modules
    ctx          spec loading, canvas presets + layout, fonts, palette, media lookup, shared arrays
    util         easing, alpha compositing, crops, PIL layers
    timeline     narration timing -> units / shots / subtitles / section bounds
    shots        shot renderers (image moves, video, collage, film, split, grid, tilt, deck,
                 quote, route, medal, rows)
    overlays     per-shot overlays (sketch is in shots; develop, shimmer, dust, prick, hl, tri,
                 loupe, tl, count)
    transitions  fade push whip flash zoom iris leak ink blinds tear slideup
    looks        film grain, vignette, memory film, light leak, ink noise, background
    subtitles    bilingual subtitles, labels, running header, chapter cards
    render       CLI: frames -> ffmpeg encode -> voice + music mix
"""
