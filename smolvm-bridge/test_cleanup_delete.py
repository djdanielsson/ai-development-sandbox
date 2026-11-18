"""Deletion must follow both stop passes and preserve active/restarted sandboxes."""

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import maintenance
from host import Bridge

MACHINE = "omni-stale-1234abcd"


def load_cleanup():
    spec = importlib.util.spec_from_file_location("cleanup_delete", maintenance.REPO / "scripts/omnigent-cleanup-stale-containers.py")
    module = importlib.util.module_from_spec(spec)
    errors = SimpleNamespace(APIError=type("APIError", (Exception,), {}),
                             DockerException=type("DockerException", (Exception,), {}),
                             NotFound=type("NotFound", (Exception,), {}))
    with patch.dict(sys.modules, {"docker": Mock(), "docker.errors": errors, "httpx": Mock()}):
        spec.loader.exec_module(module)
    return module


class DeleteTests(unittest.TestCase):
    def test_podman_removes_only_stopped_inactive_containers_without_force(self):
        cleanup = load_cleanup()
        def container(name, status):
            return SimpleNamespace(name=name, status=status, reload=Mock(), remove=Mock(), labels={
                "io.omnigent.managed": "true", "io.omnigent.provider": "podman",
                "io.omnigent.session-name": name})
        stale, active, running, changed = container("stale", "exited"), container("active", "exited"), container("running", "running"), container("changed", "exited")
        changed.reload.side_effect = lambda: setattr(changed, "status", "running")
        podman = Mock()
        podman.containers.list.return_value = [stale, active, running, changed]
        with patch.object(cleanup, "active_session_host_names", return_value={"active"}):
            self.assertEqual(cleanup.delete_stopped_containers(podman, Mock(), "http://server"), 0)
        stale.remove.assert_called_once_with()
        for kept in [active, running, changed]:
            kept.remove.assert_not_called()
        self.assertTrue(podman.containers.list.call_args.kwargs["all"])

    def test_podman_rechecks_active_sessions_before_remove(self):
        cleanup = load_cleanup()
        item = Mock(status="exited", labels={"io.omnigent.session-name": "stale"})
        podman = Mock()
        podman.containers.list.return_value = [item]
        with patch.object(cleanup, "active_session_host_names", side_effect=[set(), {"stale"}]):
            cleanup.delete_stopped_containers(podman, Mock(), "http://server")
        item.remove.assert_not_called()

    def test_bridge_rejects_delete_if_vm_resumed(self):
        launcher = Mock()
        launcher._machine.return_value = {"state": "running"}
        with tempfile.TemporaryDirectory() as directory:
            bridge = Bridge(launcher, Path(directory))
            bridge.machines.add(MACHINE)
            with self.assertRaises(ValueError):
                bridge.dispatch({"operation": "delete_stopped", "sandbox_id": MACHINE})
        launcher._smolvm.assert_not_called()

    @patch.object(maintenance, "active_names", side_effect=[set(), {"stale"}])
    @patch.object(maintenance, "rpc")
    def test_vm_delete_rechecks_sessions(self, rpc, active):
        rpc.return_value = [{"sandbox_id": MACHINE, "state": "stopped", "session_name": "stale", "created_at": 1}]
        maintenance.delete_stopped()
        self.assertNotIn("delete_stopped", [c.args[0] for c in rpc.call_args_list])

    @patch.object(maintenance, "active_names", return_value=set())
    @patch.object(maintenance, "rpc")
    def test_vm_delete_rescans_and_keeps_running_vms(self, rpc, active):
        stopped = {"sandbox_id": MACHINE, "state": "stopped", "session_name": "stale", "created_at": 1}
        running = {**stopped, "sandbox_id": "omni-live-1234abcd", "state": "running"}
        rpc.return_value = [stopped, running]
        maintenance.delete_stopped()
        self.assertEqual([c.kwargs for c in rpc.call_args_list if c.args[0] == "delete_stopped"], [{"sandbox_id": MACHINE}])

    def test_wrapper_stops_both_providers_before_deleting_and_aborts_on_failure(self):
        for fail in [False, True]:
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "scripts").mkdir()
                (root / ".smolvm-bridge").mkdir()
                (root / ".smolvm-bridge/profile.json").write_text("{}")
                script = root / "scripts/omnigent-cleanup-stale-containers.sh"
                shutil.copyfile(maintenance.REPO / "scripts/omnigent-cleanup-stale-containers.sh", script)
                (root / "scripts/omnigent-cleanup-stale-containers.py").write_text("")
                for executable in ["podman", "python3"]:
                    target = root / executable
                    target.write_text(f'#!{sys.executable}\nimport os,sys\nfrom pathlib import Path\nphase=next(a for a in sys.argv if a.startswith("--"))\nwith Path(os.environ["CLEANUP_TEST_LOG"]).open("a") as f: f.write(Path(sys.argv[0]).name+" "+phase+"\\n")\nsys.exit(1 if os.environ["CLEANUP_TEST_FAIL"]=="1" and phase=="--apply" and Path(sys.argv[0]).name=="podman" else 0)\n')
                    target.chmod(0o755)
                log = root / "calls"
                result = subprocess.run(["sh", str(script), "--delete"], env={**os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"],
                                         "CLEANUP_TEST_LOG": str(log), "CLEANUP_TEST_FAIL": str(int(fail))}, capture_output=True)
                expected = ["podman --apply", "python3 --apply"]
                if not fail:
                    expected += ["podman --delete-stopped", "python3 --delete-stopped"]
                self.assertEqual(log.read_text().splitlines(), expected)
                self.assertEqual(result.returncode, int(fail))


if __name__ == "__main__":
    unittest.main()
