"""Unit tests for internal event stream and routing contract constants."""

from app.events.bus import STREAM_GROUPS
from app.events.publisher import _STREAM_KEYS


def test_alert_module_stream_is_registered_for_event_publishing():
    assert _STREAM_KEYS["alert"] == "stream:alert"


def test_alert_stream_has_consumer_group_registration():
    assert STREAM_GROUPS["stream:alert"] == "nanfo-consumers"


def test_simulation_module_stream_is_registered_for_event_publishing():
    assert _STREAM_KEYS["simulation"] == "stream:simulation"


def test_simulation_stream_has_consumer_group_registration():
    assert STREAM_GROUPS["stream:simulation"] == "nanfo-consumers"


def test_plugin_module_stream_is_registered_for_event_publishing():
    assert _STREAM_KEYS["plugin"] == "stream:plugin"


def test_plugin_stream_has_consumer_group_registration():
    assert STREAM_GROUPS["stream:plugin"] == "nanfo-consumers"
