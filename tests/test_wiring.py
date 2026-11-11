"""Plugin wiring (__init__.py) with Hermes' storage module stubbed out.

Regression: on Nov 8 15:00:10 and Nov 11 05:45:25 a phone `/brownout park` was applied and the
"parked" alert went out, but the command reply failed with FileNotFoundError on
state.tmp -> state.json, because the watcher thread wrote state at the same moment. The gateway
then answered "Unknown command /brownout".
"""
import importlib.util
import sys
import threading
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_plugin(data_dir):
    storage = types.ModuleType("plugins.plugin_storage")
    storage.plugin_data_dir = lambda name: data_dir
    sys.modules.setdefault("plugins", types.ModuleType("plugins"))
    sys.modules["plugins.plugin_storage"] = storage
    spec = importlib.util.spec_from_file_location("brownout_under_test", ROOT / "__init__.py",
                                                  submodule_search_locations=[str(ROOT)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class StubEngine:
    def status(self):
        return '{"state": "parked"}'


def test_concurrent_state_writes_do_not_fail(tmp_path):
    plugin = load_plugin(tmp_path)
    errors = []

    def writer():
        for _ in range(300):
            try:
                plugin._write_state(StubEngine())
            except OSError as e:
                errors.append(e)

    threads = [threading.Thread(target=writer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert (tmp_path / "state.json").read_text() == '{"state": "parked"}'
    assert not list(tmp_path.glob("*.tmp"))
