"""No-store regressions for R09 admission, resource fencing, and failure cleanup."""

import argparse
import json
import os
import subprocess
import sys
from unittest.mock import Mock

import pytest

from scripts.review_fullstack import (
    AcceptanceFailure, LABEL, OwnedNeo4j, Processes, browser_results, clean_environment, exact_image, validate_counts,
)


@pytest.mark.parametrize("value", ["neo4j:5", "latest", "sha256:bad", "http://localhost:7687"])
def test_mutable_image_or_external_service_is_not_admitted(value):
    with pytest.raises(argparse.ArgumentTypeError):
        exact_image(value)


def test_caller_credentials_and_service_urls_are_not_inherited(monkeypatch):
    for key in ("POSTGRES_HOST", "REDIS_URL", "NEO4J_URI", "JWT_SECRET_KEY", "R09_API_URL", "NODE_OPTIONS"):
        monkeypatch.setenv(key, "must-not-propagate")
    assert "must-not-propagate" not in clean_environment().values()


@pytest.mark.parametrize("counts", [
    None, {"total": 0}, {"total": 4},
    {"total": 5, "passed": 4, "failed": 0, "errors": 0, "skipped": 1},
    {"total": 5, "passed": 4, "failed": 1, "errors": 0, "skipped": 0},
    {"total": 5, "passed": 4, "failed": 0, "errors": 1, "skipped": 0},
])
def test_missing_empty_partial_skipped_and_failed_browser_lanes_fail(counts):
    with pytest.raises(AcceptanceFailure):
        validate_counts(counts)


def test_complete_zero_skip_browser_lane_passes():
    validate_counts({"total": 5, "passed": 5, "failed": 0, "errors": 0, "skipped": 0})


def test_interrupted_browser_xml_does_not_interrupt_cleanup(tmp_path):
    report = tmp_path / "broken.xml"
    report.write_text("<testsuites><testsuite>")
    assert browser_results(report) == (None, [])


def test_neo4j_cleanup_refuses_other_owners_even_with_a_cidfile(tmp_path):
    neo = OwnedNeo4j(tmp_path, {}, "sha256:" + "a" * 64)
    cid = "b" * 64
    neo.cidfile.write_text(cid)
    neo.docker = Mock(return_value=Mock(stdout=json.dumps([{
        "Id": cid, "Image": neo.image, "Config": {"Labels": {LABEL: "another-owner"}},
    }])))
    with pytest.raises(AcceptanceFailure, match="ownership_mismatch"):
        neo.cleanup()
    assert all(call.args[0] != "rm" for call in neo.docker.call_args_list)


def test_interrupted_create_cidfile_recovers_exact_owned_container(tmp_path):
    neo = OwnedNeo4j(tmp_path, {}, "sha256:" + "a" * 64)
    cid = "b" * 64
    neo.cidfile.write_text(cid)
    neo.docker = Mock(side_effect=[
        Mock(stdout=json.dumps([{"Id": cid, "Image": neo.image, "Config": {"Labels": {LABEL: neo.owner}}}])),
        Mock(returncode=0), Mock(returncode=1),
    ])
    assert neo.cleanup()
    assert neo.docker.call_args_list[1].args == ("rm", "--force", "--volumes", cid)


def test_cleanup_continues_after_one_process_fails(tmp_path):
    processes = Processes(tmp_path)
    processes.children = [Mock(), Mock(), Mock()]
    processes.stop = Mock(side_effect=[OSError(), True, True])
    assert not processes.cleanup()
    assert processes.stop.call_count == 3


def test_timeout_reaps_owned_child_and_leaves_unrelated_child_alive(tmp_path):
    processes = Processes(tmp_path)
    env = {"PATH": os.environ["PATH"]}
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            processes.run("timeout", [sys.executable, "-c", "import time; time.sleep(60)"], env, timeout=0.1)
        assert processes.children[0].poll() is not None
        assert unrelated.poll() is None
        assert processes.cleanup()
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)
