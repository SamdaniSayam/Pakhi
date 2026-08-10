import importlib

import pakhi.viz as viz


def test_viz_init_import_error(monkeypatch):
    import builtins

    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "pakhi.viz.dashboard":
            raise ImportError("mock error")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    importlib.reload(viz)

    # Reload again without monkeypatch so it doesn't break other tests
    monkeypatch.undo()
    importlib.reload(viz)
