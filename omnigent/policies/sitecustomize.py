"""Compatibility shim for Omnigent releases using a namespace package."""

from pathlib import Path

try:
    import omnigent
except ImportError:
    pass
else:
    if getattr(omnigent, "__file__", None) is None:
        package_path = next(iter(getattr(omnigent, "__path__", ())), None)
        if package_path is not None:
            # thread_pool_watchdog derives the installed package root from
            # ``omnigent.__file__``; PEP 420 namespace packages leave it None.
            omnigent.__file__ = str(Path(package_path) / "__init__.py")
