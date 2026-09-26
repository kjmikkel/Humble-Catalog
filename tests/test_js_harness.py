"""When the JS behaviour suite may skip, and when it must fail (#109).

Skipping without Node is right on a contributor's machine: Node is
optional, and the Python suite should still run. It is wrong in CI,
where the JS suite runs only because the runner image happens to ship
Node -- an image change would drop every JS test with nothing but a
skip count to show for it. CI sets HUMBLE_REQUIRE_NODE, and then a
missing Node is a failure.
"""
import pytest

from tests import js_harness


def _no_node(monkeypatch):
    monkeypatch.setattr(js_harness.shutil, "which", lambda name: None)


def test_without_node_the_suite_skips_by_default(monkeypatch):
    _no_node(monkeypatch)
    monkeypatch.delenv("HUMBLE_REQUIRE_NODE", raising=False)
    with pytest.raises(pytest.skip.Exception):
        js_harness.node_executable()


def test_without_node_the_suite_fails_when_node_is_required(monkeypatch):
    _no_node(monkeypatch)
    monkeypatch.setenv("HUMBLE_REQUIRE_NODE", "1")
    with pytest.raises(pytest.fail.Exception, match="HUMBLE_REQUIRE_NODE"):
        js_harness.node_executable()


def test_an_empty_value_does_not_require_node(monkeypatch):
    # `HUMBLE_REQUIRE_NODE=` in a shell profile is "unset", not "on".
    _no_node(monkeypatch)
    monkeypatch.setenv("HUMBLE_REQUIRE_NODE", "")
    with pytest.raises(pytest.skip.Exception):
        js_harness.node_executable()


def test_with_node_present_its_path_is_returned(monkeypatch):
    monkeypatch.setattr(js_harness.shutil, "which",
                        lambda name: "/opt/node/bin/node")
    monkeypatch.setenv("HUMBLE_REQUIRE_NODE", "1")
    assert js_harness.node_executable() == "/opt/node/bin/node"
