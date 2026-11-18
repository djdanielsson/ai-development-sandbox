"""Moving source directories must preserve state and supervised PID checks."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import manage


class BridgeMigrationTests(unittest.TestCase):
    def stop_bridge(self, command, allowed):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / '.smolvm-bridge'
            state.mkdir()
            (state / 'bridge.pid').write_text('12345')
            repo = Path(directory) / 'omnigent'
            with patch.object(manage, 'ROOT', state), patch.object(manage, 'REPO', repo), \
                    patch.object(manage.sys, 'argv', ['manage.py', 'stop']), \
                    patch.object(manage.subprocess, 'run', return_value=SimpleNamespace(stdout=command(directory))), \
                    patch.object(manage.os, 'kill') as kill:
                if allowed:
                    manage.main()
                    kill.assert_called_once_with(12345, manage.signal.SIGTERM)
                else:
                    with self.assertRaises(SystemExit):
                        manage.main()
                    kill.assert_not_called()

    def test_current_source_path_can_be_stopped(self):
        self.stop_bridge(lambda d: f'python {d}/omnigent/smolvm-bridge/host.py --root {d}/.smolvm-bridge', True)

    def test_legacy_source_path_can_be_stopped(self):
        self.stop_bridge(lambda d: f'python {d}/smolvm-bridge/host.py --root {d}/.smolvm-bridge', True)

    def test_unrelated_recycled_pid_is_preserved(self):
        self.stop_bridge(lambda d: 'python unrelated.py', False)

    def test_bridge_using_other_state_is_preserved(self):
        self.stop_bridge(lambda d: f'python {d}/omnigent/smolvm-bridge/host.py --root /elsewhere', False)
