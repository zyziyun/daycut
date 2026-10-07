"""A fake transcriber for the real-engine output tests (``VSTUDIO_OUTPUT_TRANSCRIBER=_fake_asr:words``)."""


def words(path, language=None):
    return [dict(w="hello", t=0.2, te=0.6), dict(w="world", t=0.8, te=1.3), dict(w="again", t=1.6, te=2.2)]
