"""Maintenance must preserve active, new, stopped, and foreign machines."""

import tempfile
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import maintenance
from host import Bridge

MACHINE = "omni-test-1234abcd"


class MaintenanceTests(unittest.TestCase):
    def machine(self, **changes):
        return {"sandbox_id": MACHINE, "session_name": "test", "state": "running",
                "created_at": 100, **changes}

    def test_prune_keeps_active_stopped_new_and_unknown_age_vms(self):
        self.assertTrue(maintenance.stale_candidate(self.machine(), set(), 1000))
        self.assertFalse(maintenance.stale_candidate(self.machine(), {"test"}, 1000))
        self.assertFalse(maintenance.stale_candidate(self.machine(state="stopped"), set(), 1000))
        self.assertFalse(maintenance.stale_candidate(self.machine(created_at=900), set(), 1000))
        self.assertFalse(maintenance.stale_candidate(self.machine(created_at=None), set(), 1000))

    @patch.object(maintenance, "rpc")
    @patch.object(maintenance, "active_names", side_effect=RuntimeError("API unavailable"))
    def test_prune_fails_closed_on_session_api_error(self, active, rpc):
        with self.assertRaises(RuntimeError):
            maintenance.prune(True)
        rpc.assert_not_called()

    @patch.object(maintenance, "rpc")
    @patch.object(maintenance, "active_names", side_effect=[set(), {"test"}])
    def test_prune_rechecks_before_stopping(self, active, rpc):
        rpc.return_value = [self.machine()]
        maintenance.prune(True)
        self.assertNotIn("stop", [call.args[0] for call in rpc.call_args_list])

    @patch.object(maintenance, "rpc")
    @patch.object(maintenance, "active_names", return_value=set())
    def test_dry_run_does_not_stop(self, active, rpc):
        rpc.return_value = [self.machine()]
        maintenance.prune(False)
        self.assertEqual([call.args[0] for call in rpc.call_args_list], ["list"])

    @patch.object(maintenance, "rpc", return_value=[{"state": "stopped"}])
    def test_reconnect_does_not_resume_stopped_vms(self, rpc):
        self.assertEqual(maintenance.reconnect(), 0)
        self.assertEqual([call.args[0] for call in rpc.call_args_list], ["list"])

    def test_bridge_lists_only_registry_and_stop_never_deletes(self):
        launcher = Mock()
        launcher._machine.return_value = {"state": "running", "created_at": 100,
                                          "labels": {"omnigent.session-name": "test"}}
        launcher._smolvm.return_value = SimpleNamespace(returncode=0)
        with tempfile.TemporaryDirectory() as directory:
            bridge = Bridge(launcher, Path(directory))
            bridge.machines.add(MACHINE)
            self.assertEqual(bridge.dispatch({"operation": "list"}), [self.machine()])
            bridge.dispatch({"operation": "stop", "sandbox_id": MACHINE})
            self.assertIn(MACHINE, bridge.machines)
            self.assertEqual(launcher._smolvm.call_args.args, ("machine", "stop", "--name", MACHINE))
            with self.assertRaises(PermissionError):
                bridge.dispatch({"operation": "stop", "sandbox_id": "omni-foreign-1234abcd"})
            launcher.terminate.assert_not_called()

    def test_vm_reconnect_uses_same_identity_without_expired_token(self):
        source = maintenance.REPO / "scripts/omnigent-reconnect-container.py"
        spec = importlib.util.spec_from_file_location("reconnect_guest", source)
        guest = importlib.util.module_from_spec(spec)
        with patch.dict("sys.modules", {"httpx": SimpleNamespace(Client=Mock(), HTTPError=RuntimeError)}):
            spec.loader.exec_module(guest)
        host = {"name": "test", "sandbox_provider": "smolvm", "host_id": "vm-host", "status": "offline"}
        # Same-name Podman host must not be selected for the VM's recovery.
        other = {**host, "sandbox_provider": "podman", "host_id": "container-host"}
        responses = [{"user_id": "local", "is_admin": True}, {"hosts": [other, host]},
                     {"hosts": [{**host, "status": "online"}]}]
        client = Mock()
        client.get.side_effect = [Mock(json=Mock(return_value=value)) for value in responses]
        with patch.object(guest.sys, "argv", [str(source), "http://100.96.0.1:8000", "test", "smolvm"]), \
             patch.object(guest.httpx, "Client", return_value=client), \
             patch.dict(guest.os.environ, {"OMNIGENT_HOST_TOKEN": "expired-test-token"}), \
             patch.object(guest.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            self.assertEqual(guest.main(), 0)
            env = run.call_args.kwargs["env"]
            self.assertEqual(env["OMNIGENT_HOST_ID"], "vm-host")
            self.assertEqual(env["OMNIGENT_DATA_DIR"], "/root/.omnigent/reconnect/vm-host")
            self.assertNotIn("OMNIGENT_HOST_TOKEN", env)
            self.assertIn("--background", run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
