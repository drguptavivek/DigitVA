"""The gunicorn master warms the reference-form caches before workers fork."""

import importlib.util
from pathlib import Path

from app.services import instrument_translation_service as svc


def test_on_starting_warms_reference_caches_once(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "gunicorn_conf", Path(__file__).resolve().parents[1] / "gunicorn_app.conf.py"
    )
    conf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(conf)

    svc._reference_items_cached.cache_clear()
    svc._reference_notes_cached.cache_clear()
    conf.on_starting(server=None)
    assert svc._reference_items_cached.cache_info().currsize == 1
    assert svc._reference_notes_cached.cache_info().currsize == 1

    # A later request is a cache hit: the workbook is not parsed again.
    monkeypatch.setattr(svc, "read_workbook_items", lambda *a, **k: 1 / 0)
    svc.export_translations(svc.BASE_INSTRUMENT_CODE, svc.BASE_LOCALE)
    svc.reference_items()


def test_warm_up_is_scoped_to_the_main_app():
    # The public DORIS service shares the image and working directory; an
    # auto-loaded gunicorn.conf.py would parse the XLSForm in its 192 MB box.
    root = Path(__file__).resolve().parents[1]
    assert (root / "gunicorn_app.conf.py").is_file()
    assert not (root / "gunicorn.conf.py").exists()
    assert "-c gunicorn_app.conf.py" in (root / "boot.sh").read_text()
    assert "gunicorn_app.conf.py" not in (root / "boot-public-doris.sh").read_text()
