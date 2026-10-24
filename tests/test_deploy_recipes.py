"""Exercise app deployment entry points without running an infrastructure tool."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class DeployRecipeTests(unittest.TestCase):
    def test_dispatch(self):
        real_just = shutil.which("just")
        if real_just is None:
            self.skipTest("just is required for deployment recipe invocation tests")
        repo = Path(__file__).resolve().parents[1]
        for host in ("production", "staging"):
            for override_root in (False, True):
                with self.subTest(host=host, override_root=override_root), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    control = root / "ops control"
                    control.mkdir()
                    bin_dir = root / "bin"
                    bin_dir.mkdir()
                    recorder = bin_dir / "just"
                    recorder.write_text(
                        "#!/usr/bin/env python3\n"
                        "import json, os, pathlib, sys\n"
                        "pathlib.Path(os.environ['RECORD']).write_text(json.dumps({"
                        "'args':sys.argv[1:], 'cwd':os.getcwd(), "
                        "'env':{k:os.environ.get(k) for k in "
                        "['PROJECTS_ROOT','OPS_LIBRARY_PATH','SOPS_AGE_KEY_FILE']}}))\n"
                        "sys.exit(int(os.environ.get('DISPATCH_EXIT', '0')))\n"
                    )
                    recorder.chmod(0o755)
                    env = os.environ.copy()
                    env.pop("PROJECTS_ROOT", None)
                    env.update(
                        PATH=str(bin_dir) + os.pathsep + env["PATH"],
                        OPS_CONTROL=str(control),
                        OPS_LIBRARY_PATH=str(root / "ops library"),
                        SOPS_AGE_KEY_FILE=str(root / "age key"),
                        RECORD=str(root / "record.json"),
                    )
                    expected_root = repo.parent
                    if override_root:
                        expected_root = root / "selected sources"
                        env["PROJECTS_ROOT"] = str(expected_root)
                    for exit_code in (0, 23):
                        env["DISPATCH_EXIT"] = str(exit_code)
                        (root / "record.json").unlink(missing_ok=True)
                        result = subprocess.run(
                            [real_just, "--justfile", str(repo / "justfile"), f"deploy-{host}"],
                            cwd=root,
                            env=env,
                            capture_output=True,
                            text=True,
                        )
                        self.assertEqual(result.returncode == 0, exit_code == 0, result.stderr)
                        record = json.loads((root / "record.json").read_text())
                        self.assertEqual(record["args"], ["deploy-one", "python_podcast", host])
                        self.assertEqual(record["cwd"], str(control.resolve()))
                        self.assertEqual(record["env"]["PROJECTS_ROOT"], str(expected_root))
                        self.assertEqual(record["env"]["OPS_LIBRARY_PATH"], env["OPS_LIBRARY_PATH"])
                        self.assertEqual(record["env"]["SOPS_AGE_KEY_FILE"], env["SOPS_AGE_KEY_FILE"])


if __name__ == "__main__":
    unittest.main()
