"""Unit tests for scansort.ui.singleton_window module."""

import pytest

from scansort.ui.singleton_window import SingletonToplevel


def test_registry_hooks_are_abstract():
    """The base class must require subclasses to supply their registry hooks."""
    with pytest.raises(NotImplementedError):
        SingletonToplevel._instance()
    with pytest.raises(NotImplementedError):
        SingletonToplevel._set_instance(None)
    with pytest.raises(NotImplementedError):
        SingletonToplevel._lock()
