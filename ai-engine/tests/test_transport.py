import subprocess
import sys

import pytest

from nanfo_routing.contracts import Request
from nanfo_routing.transport import DockerTransport, TransportError


@pytest.mark.parametrize(
    "body,valid",
    [
        (
            'print(\'{"version":1,"ok":false,"error":"offline test","data":null}\'); '
            "raise SystemExit(1)",
            True,
        ),
        ('print(\'{"version":1,"ok":false,"error":"offline test","data":null}\')', True),
        ('print(\'{"x":1,"x":2}\')', False),
        ("print('{\"x\":NaN}')", False),
        ('print("not json")', False),
        ('print("{} "); raise SystemExit(1)', False),
        ('print("x" * (1024 * 1024 + 1))', False),
    ],
)
def test_bounded_fixed_command_transport(monkeypatch, body, valid):
    popen = subprocess.Popen

    def fixtureProcess(argv, **kwargs):
        assert argv == [
            "docker",
            "exec",
            "-i",
            "nanfo-experiment",
            "python",
            "-m",
            "emulation.experiment_client",
        ]
        assert kwargs["shell"] is False
        return popen([sys.executable, "-c", "import sys; sys.stdin.read(); " + body], **kwargs)

    monkeypatch.setattr(subprocess, "Popen", fixtureProcess)
    request = Request(command="reset", seed=1000, scenario="low")
    if valid:
        assert DockerTransport().exchange(request)["ok"] is False
    else:
        with pytest.raises(TransportError):
            DockerTransport().exchange(request)
