"""Gunicorn settings for the main app only (boot.sh passes -c).

Not named gunicorn.conf.py on purpose: gunicorn would then load it for the
public DORIS service too, which shares this image and working directory
and has a 192 MB memory limit.
"""


def on_starting(server):
    """Parse the reference XLSForm once in the master, before workers fork.

    Reading it costs about a second of pandas work. It is memoised per
    process, so without this the first translation request of every process
    paid it (staging: ~1.4 s median on the translations routes). Workers
    inherit the warm cache through --preload's fork. Needs no database.
    """
    from app.services.instrument_translation_service import (
        reference_items,
        reference_notes,
    )

    reference_items()
    reference_notes()
