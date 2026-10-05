"""Run SmartVA's command line without charts and without matplotlib.

Charts are for debugging only (``SMARTVA_CHARTS``; then the runner starts
SmartVA's own CLI instead). SmartVA imports matplotlib at the top of three
modules and draws two charts even with ``--figures False`` (``OutputPrep``
``_graph_gbd_csmf`` / ``_graph_all_csmf``); nothing in DigitVA reads them.
This launcher gives SmartVA an empty stand-in for matplotlib, so the real
library, its font cache and its import time are never paid, turns those two
charts off, then runs SmartVA unchanged. Any drawing that still happened would
fail loudly on the stand-in. Run as a script (not ``-m app...``), so the Flask
app is never imported. If a SmartVA upgrade renames the chart functions, it
stops loudly rather than quietly drawing again.
"""

import sys
import types


class _NoMatplotlib(types.ModuleType):
    """``import matplotlib`` and ``matplotlib.use("Agg")`` succeed; any other
    use raises."""

    def use(self, *args, **kwargs):
        return None

    def __getattr__(self, name):
        if name.startswith("__"):  # Python's own probes (__file__, __path__, ...)
            raise AttributeError(name)
        raise RuntimeError(f"matplotlib.{name} used with SmartVA charts off")


for _name in ("matplotlib", "matplotlib.pyplot", "matplotlib.ticker"):
    sys.modules[_name] = _NoMatplotlib(_name)
sys.modules["matplotlib"].pyplot = sys.modules["matplotlib.pyplot"]
sys.modules["matplotlib"].ticker = sys.modules["matplotlib.ticker"]

from smartva import output_prep, va_cli  # noqa: E402  (after the stand-in)

_UNUSED_CHARTS = ("_graph_gbd_csmf", "_graph_all_csmf")


def _no_chart(self):
    return None


for _name in _UNUSED_CHARTS:
    if not hasattr(output_prep.OutputPrep, _name):
        raise RuntimeError(f"SmartVA no longer has OutputPrep.{_name}; review smartva_cli_no_charts.py")
    setattr(output_prep.OutputPrep, _name, _no_chart)


if __name__ == "__main__":
    va_cli.main()
