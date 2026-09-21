"""Verifier opt-in and filesystem authority boundaries, without infrastructure."""

from unittest.mock import AsyncMock

import pytest

from scripts.verify_operator_override import main, sandbox


async def test_physical_verifier_requires_explicit_live(monkeypatch):
    monkeypatch.setattr('sys.argv', ['verify_operator_override.py'])
    run = AsyncMock()
    monkeypatch.setattr('scripts.verify_operator_override.verify', run)
    with pytest.raises(SystemExit) as error:
        await main()
    assert error.value.code == 2
    run.assert_not_awaited()


@pytest.mark.parametrize('commands', [False, True])
def test_backend_sandbox_only_intent_commands_writable(tmp_path, commands):
    args = sandbox(tmp_path, commands=commands)
    assert args[:4] == ['bwrap', '--ro-bind', '/', '/']
    assert '--unshare-pid' in args and '--die-with-parent' in args
    assert args[args.index('--tmpfs') + 1] == '/tmp'
    assert ['--tmpfs', '/run'] == args[args.index('/run') - 1:args.index('/run') + 1]
    binds = [args[index + 1:index + 3] for index, value in enumerate(args) if value == '--bind']
    assert binds == ([[str(tmp_path / 'commands')] * 2] if commands else [])


def test_stop_capture_orders_owned_worker_pause_before_trigger_and_resume_after_commit():
    import inspect
    from scripts.verify_operator_override import verify

    source = inspect.getsource(verify)
    pause = source.index('autonomy_worker.send_signal(signal.SIGSTOP)')
    capture = source.index("capture_task = asyncio.create_task(capture())", pause)
    stop = source.index("stopped = await request('POST', '/api/v1/autonomy/stop'", capture)
    committed = source.index("evidence['stop_committed_at']", stop)
    resume = source.index('autonomy_worker.send_signal(signal.SIGCONT)', committed)
    interrupted = source.index("'Control did not interrupt capture'", resume)
    assert pause < capture < stop < committed < resume < interrupted
