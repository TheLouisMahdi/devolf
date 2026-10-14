"""Exercise source update/pin transactions without using GitHub or real caches."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "nt", "Windows PowerShell build resolver")
class BuildSourceTests(unittest.TestCase):
    old = "a" * 40
    latest = "b" * 40

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        original = Path(__file__).resolve().parents[1] / "resolve-beacheye-source.ps1"
        shutil.copyfile(original, self.project / original.name)
        self.manifest = self.project / "beacheye-source.json"
        self.original = json.dumps({"repository": "majidnow/BeachEye",
                                    "branch": "ver_50_remaster", "commit": self.old})
        self.manifest.write_text(self.original, encoding="utf-8")
        self.cache = self.root / "private-cache"
        for commit in (self.old, self.latest):
            snapshot = self.cache / "majidnow__BeachEye/ver_50_remaster" / commit
            (snapshot / ".git").mkdir(parents=True)
            for name in ("include/Configure.h", "include/Database.h", "include/Settings.h",
                         "include/MeasureType.h", "src/Database.cpp", "src/Settings.cpp"):
                file = snapshot / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text("// synthetic build fixture\n", encoding="utf-8")
            (snapshot / "src/cJSON_Imp.cpp").write_text(
                "#define JSON_NUM_ASSERT_DEF(obj, value, attr, def) fixture\n"
                "#define JSON_NUM_ADD(obj, value) fixture\n", encoding="utf-8")
        self.commands = self.root / "commands.jsonl"
        executable_dir = self.root / "bin"
        executable_dir.mkdir()
        helper = executable_dir / "fixture.py"
        helper.write_text(
            "import json, os, sys\nfrom pathlib import Path\n"
            "tool, *args = sys.argv[1:]\n"
            "with open(os.environ['DEVOLF_TEST_COMMANDS'], 'a') as f: f.write(json.dumps([tool, *args])+'\\n')\n"
            "if tool == 'git' and args[-2:] == ['rev-parse', 'HEAD']: print(Path(args[1]).name)\n"
            "elif tool == 'gh' and args[0] == 'api':\n"
            "    endpoint=args[1]\n"
            "    if endpoint == 'repos/majidnow/BeachEye': print('true')\n"
            "    elif endpoint.endswith('/commits/ver_50_remaster'):\n"
            "        if os.environ.get('DEVOLF_TEST_FAIL_HEAD'): sys.exit(1)\n"
            f"        print('{self.latest}')\n"
            "    elif '/commits/' in endpoint: print(endpoint.rsplit('/',1)[1])\n"
            "    else: sys.exit(9)\n"
            "else: sys.exit(9)\n", encoding="utf-8")
        for tool in ("gh", "git"):
            (executable_dir / f"{tool}.cmd").write_text(
                f'@"{sys.executable}" "{helper}" {tool} %*\r\n', encoding="utf-8")
        self.environment = dict(os.environ, PATH=str(executable_dir) + os.pathsep + os.environ["PATH"],
                                DEVOLF_BEACHEYE_CACHE=str(self.cache),
                                DEVOLF_TEST_COMMANDS=str(self.commands))

    def resolve(self, update=False):
        command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                   "-File", str(self.project / "resolve-beacheye-source.ps1")]
        if update:
            command.append("-UpdateBeachEye")
        return subprocess.run(command, env=self.environment, capture_output=True, text=True, timeout=20)

    def test_default_reuses_pin_without_querying_branch_head(self):
        result = self.resolve()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.manifest.read_text(), self.original)
        self.assertNotIn("/commits/ver_50_remaster", self.commands.read_text())
        self.assertIn("/commits/" + self.old, self.commands.read_text())

    def test_update_resolves_head_once_and_records_ready_checkout(self):
        result = self.resolve(update=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(self.manifest.read_text())["commit"], self.latest)
        self.assertEqual(self.commands.read_text().count("/commits/ver_50_remaster"), 1)
        snapshot = self.cache / "majidnow__BeachEye/ver_50_remaster" / self.latest
        self.assertTrue((snapshot / ".devolf-desktop-ready").exists())

    def test_failed_remote_lookup_does_not_change_recorded_pin(self):
        self.environment["DEVOLF_TEST_FAIL_HEAD"] = "1"
        result = self.resolve(update=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.manifest.read_text(), self.original)

    def test_incompatible_checkout_does_not_change_recorded_pin(self):
        snapshot = self.cache / "majidnow__BeachEye/ver_50_remaster" / self.latest
        (snapshot / "src/cJSON_Imp.cpp").write_text("// unsupported fixture\n")
        result = self.resolve(update=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.manifest.read_text(), self.original)


if __name__ == "__main__":
    unittest.main()
