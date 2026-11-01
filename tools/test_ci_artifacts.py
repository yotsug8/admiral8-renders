"""Offline regressions: only temporary Git repositories and fake media bytes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ci_artifacts as ci


def write(root, name, content="fixture"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def commit(repo, message="fixture"):
    ci.git(repo, "add", "--all")
    ci.git(repo, "commit", "--allow-empty", "-m", message)
    return ci.git(repo, "rev-parse", "HEAD").stdout.strip()


class RepositoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="test_ci_")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        ci.git(self.repo, "init", "-b", "main")
        write(self.repo, "episodes/001.json", "{}")
        write(self.repo, "episodes/demo_layouts.json", "{}")
        write(self.repo, "episodes/demo-scene.json", "{}")
        write(self.repo, "voice/demo_layouts/line.mp3")
        self.initial = commit(self.repo)


class SelectionTests(RepositoryTest):
    def test_whole_push_includes_named_numeric_and_voice_changes(self):
        write(self.repo, "episodes/001.json", '{"changed": 1}')
        commit(self.repo)
        write(self.repo, "voice/demo_layouts/line.mp3", "new")
        commit(self.repo)
        write(self.repo, "episodes/demo-scene.json", '{"changed": 2}')
        tip = commit(self.repo)
        self.assertEqual(ci.select_episodes(self.repo, "push", tip, self.initial),
                         ["001", "demo-scene", "demo_layouts"])
        self.assertEqual(ci.select_episodes(self.repo, "workflow_dispatch", tip), ["demo-scene"])

    def test_new_branch_and_root_dispatch(self):
        for event, before in [("push", "0" * 40), ("workflow_dispatch", "")]:
            self.assertEqual(ci.select_episodes(self.repo, event, self.initial, before),
                             ["001", "demo-scene", "demo_layouts"])

    def test_renames_deletions_and_unrelated_paths(self):
        (self.repo / "episodes/001.json").unlink()
        ci.git(self.repo, "mv", "episodes/demo-scene.json", "episodes/new-name.json")
        (self.repo / "voice/demo_layouts/line.mp3").unlink()
        write(self.repo, "other/episodes/999.json")
        write(self.repo, "episodes/nested/999.json")
        write(self.repo, "episodes/demo_layouts.json.bak")
        tip = commit(self.repo)
        self.assertEqual(ci.select_episodes(self.repo, "push", tip, self.initial),
                         ["demo_layouts", "new-name"])

    def test_empty_change_and_manual_validation(self):
        tip = commit(self.repo)
        self.assertEqual(ci.select_episodes(self.repo, "push", tip, self.initial), [])
        for name in ["demo_layouts", "demo-scene", "001"]:
            self.assertEqual(ci.select_episodes(self.repo, "workflow_dispatch", tip,
                                                requested=name), [name])
        for name in ["missing", "../demo_layouts", "001 demo_layouts", '$(touch injected)',
                     'demo_layouts"; echo hacked', "demo_layouts\nlist=001"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                ci.select_episodes(self.repo, "workflow_dispatch", tip, requested=name)
        with self.assertRaises(ValueError):
            ci.select_episodes(self.repo, "workflow_dispatch", tip, audition="voice:title")
        for before in ["", "HEAD~1", "abc"]:
            with self.assertRaises(ValueError):
                ci.select_episodes(self.repo, "push", tip, before)

    def test_force_push_uses_event_before_without_merge_base(self):
        write(self.repo, "episodes/001.json", "old-lineage")
        before = commit(self.repo)
        ci.git(self.repo, "checkout", "--detach", self.initial)
        write(self.repo, "episodes/demo-scene.json", "new-lineage")
        tip = commit(self.repo)
        self.assertEqual(ci.select_episodes(self.repo, "push", tip, before), ["001", "demo-scene"])

    def test_missing_before_fetches_exact_commit_or_fails(self):
        write(self.repo, "episodes/001.json", "old-lineage")
        before = commit(self.repo)
        ci.git(self.repo, "checkout", "--detach", self.initial)
        write(self.repo, "episodes/demo-scene.json", "new-lineage")
        tip = commit(self.repo)
        runner = self.root / "shallow"
        ci.git(self.root, "clone", "--depth", "1", self.repo.as_uri(), str(runner))
        self.assertNotEqual(ci.git(runner, "cat-file", "-e", before, check=False).returncode, 0)
        self.assertEqual(ci.select_episodes(runner, "push", tip, before), ["001", "demo-scene"])
        with self.assertRaises(subprocess.CalledProcessError):
            ci.select_episodes(runner, "push", tip, "f" * 40)


class PublicationTests(RepositoryTest):
    def setUp(self):
        super().setUp()
        self.remote = self.root / "remote.git"
        ci.git(self.root, "init", "--bare", str(self.remote))
        ci.git(self.remote, "config", "receive.denyNonFastForwards", "true")
        ci.git(self.remote, "config", "receive.denyDeletes", "true")
        ci.git(self.repo, "remote", "add", "origin", str(self.remote))
        ci.git(self.repo, "push", "origin", "main")
        self.other = self.root / "other"
        ci.git(self.root, "clone", "-b", "main", str(self.remote), str(self.other))
        self.payload = self.root / "payload"
        self.payload.mkdir()

    def read(self, branch, path):
        return ci.git(self.remote, "show", f"{branch}:{path}").stdout

    def test_all_branches_preserve_files_history_and_checkout(self):
        write(self.repo, "staged.txt", "local staged change")
        ci.git(self.repo, "add", "staged.txt")
        before_status = ci.git(self.repo, "status", "--porcelain").stdout
        before_index = ci.git(self.repo, "write-tree").stdout
        for branch in ["renders", "takes", "assets"]:
            with self.subTest(branch=branch):
                old = self.root / f"old-{branch}"
                write(old, "old.mp4", "old video")
                write(old, "nested/takes.json", "metadata")
                write(old, "nested/voice.mp3", "old voice")
                write(old, "README.md", "# Handwritten catalog\nKeep this paragraph.\n")
                write(old, ".gitignore", "*.log\n*.mp4\n")
                first = ci.publish(self.repo, old, branch, "old artifacts")
                write(self.payload, "new.mp4", "new video")
                write(self.payload, "render.log", "log")
                second = ci.publish(self.repo, self.payload, branch, "new artifacts")
                self.assertEqual(ci.git(self.remote, "rev-parse", f"{second}^").stdout.strip(), first)
                for path, expected in [("old.mp4", "old video"), ("nested/takes.json", "metadata"),
                                       ("nested/voice.mp3", "old voice"), ("new.mp4", "new video"),
                                       ("render.log", "log")]:
                    self.assertEqual(self.read(branch, path), expected)
                readme = self.read(branch, "README.md")
                self.assertIn("Keep this paragraph.", readme)
                if branch != "assets":
                    self.assertIn("nested/voice.mp3", readme)
                    self.assertEqual(readme.count(ci.INDEX_START), 1)
                self.assertEqual(ci.publish(self.repo, self.payload, branch, "repeat"), second)
        self.assertEqual(ci.git(self.repo, "status", "--porcelain").stdout, before_status)
        self.assertEqual(ci.git(self.repo, "write-tree").stdout, before_index)
        self.assertEqual(ci.git(self.repo, "rev-parse", "HEAD").stdout.strip(), self.initial)
        self.assertEqual(ci.git(self.repo, "worktree", "list", "--porcelain").stdout.count("worktree "), 1)

    def test_same_path_replacement_retains_previous_bytes_in_history(self):
        write(self.payload, "clip.mp4", "version one")
        first = ci.publish(self.repo, self.payload, "renders", "first")
        write(self.payload, "clip.mp4", "version two")
        second = ci.publish(self.repo, self.payload, "renders", "second")
        self.assertEqual(self.read("renders", "clip.mp4"), "version two")
        self.assertEqual(self.read(first, "clip.mp4"), "version one")
        self.assertEqual(ci.git(self.remote, "rev-parse", f"{second}^").stdout.strip(), first)

    def test_racing_publishers_retry_existing_and_new_branches(self):
        real_git = ci.git
        competitor_payload = self.root / "competitor"
        write(competitor_payload, "competitor.mp4", "competitor")
        write(self.payload, "own.mp4", "own")
        for branch in ["renders", "takes", "assets"]:
            for existing in [False, True]:
                with self.subTest(branch=branch, existing=existing):
                    # Each iteration uses a fresh branch except the second pass.
                    raced = []
                    pushes = []

                    def race(repo, *args, **kwargs):
                        if args and args[0] == "push":
                            pushes.append(args)
                            if not raced:
                                raced.append(True)
                                write(competitor_payload, "competitor.mp4", f"competitor-{existing}")
                                raced.append(ci.publish(self.other, competitor_payload, branch, "competitor"))
                        return real_git(repo, *args, **kwargs)

                    write(self.payload, "own.mp4", f"own-{existing}")
                    with patch.object(ci, "git", side_effect=race):
                        tip = ci.publish(self.repo, self.payload, branch, "own")
                    self.assertGreaterEqual(len(pushes), 3)  # competitor, rejection, retry
                    self.assertTrue(all("--force" not in p and "-f" not in p for p in pushes))
                    self.assertEqual(self.read(branch, "own.mp4"), f"own-{existing}")
                    self.assertEqual(self.read(branch, "competitor.mp4"), f"competitor-{existing}")
                    self.assertEqual(real_git(self.remote, "rev-parse", f"{tip}^").stdout.strip(), raced[1])

    def test_empty_missing_payload_and_unavailable_remote(self):
        self.assertIsNone(ci.publish(self.repo, self.root / "absent", "renders", "empty"))
        self.assertIsNone(ci.publish(self.repo, self.payload, "renders", "empty"))
        self.assertEqual(ci.git(self.remote, "branch", "--list", "renders").stdout, "")
        write(self.payload, "render.log", "error log")
        ci.git(self.repo, "remote", "set-url", "origin", str(self.root / "missing.git"))
        with self.assertRaises(subprocess.CalledProcessError):
            ci.publish(self.repo, self.payload, "renders", "cannot publish")

    def test_rejected_push_fails_without_destroying_remote(self):
        write(self.payload, "old.txt", "old")
        first = ci.publish(self.repo, self.payload, "assets", "first")
        ci.git(self.remote, "config", "receive.denyCurrentBranch", "refuse")
        # A real rejecting receive hook, not a mocked push result.
        hook = self.remote / "hooks/pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        write(self.payload, "new.txt", "new")
        with self.assertRaises(subprocess.CalledProcessError):
            ci.publish(self.repo, self.payload, "assets", "rejected")
        self.assertEqual(ci.git(self.remote, "rev-parse", "assets").stdout.strip(), first)
        self.assertEqual(self.read("assets", "old.txt"), "old")


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import yaml
        except ImportError:
            raise unittest.SkipTest("PyYAML needed only for workflow structure/shell tests")
        root = Path(__file__).resolve().parents[1]
        cls.workflows = {p.stem: yaml.safe_load(p.read_text(encoding="utf-8"))
                         for p in (root / ".github/workflows").glob("*.yml")}

    def test_no_expressions_in_shell_and_full_history_checkout(self):
        for name, workflow in self.workflows.items():
            for job in workflow["jobs"].values():
                checkout = [s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@")]
                self.assertEqual(len(checkout), 1, name)
                if name == "render":
                    self.assertEqual(checkout[0]["with"]["fetch-depth"], 0)
                for step in job["steps"]:
                    script = step.get("run", "")
                    self.assertNotIn("${{", script)
                    self.assertNotIn("git push", script)

    def test_bash_syntax_and_injection_inputs_remain_literal_arguments(self):
        bash = shutil.which("bash")
        if os.name == "nt":
            candidate = Path(shutil.which("git")).parents[1] / "bin/bash.exe"
            if candidate.exists():
                bash = str(candidate)
        if not bash:
            self.skipTest("Bash unavailable")
        for workflow in self.workflows.values():
            for job in workflow["jobs"].values():
                for step in job["steps"]:
                    if "run" in step:
                        subprocess.run([bash, "-n"], input=step["run"], text=True, check=True,
                                       encoding="utf-8", capture_output=True)
        steps = self.workflows["render"]["jobs"]["render"]["steps"]
        malicious = 'x"; touch injected; # $(touch injected2) `touch injected3`'
        for mode in ["Подбор голоса", "Дубли озвучки", "Рендер", "audition"]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix="ci_shell_") as tmp:
                root = Path(tmp)
                write(root, "video.py", "import json,sys\nfrom pathlib import Path\n"
                      "Path('arguments.json').write_text(json.dumps(sys.argv[1:]))\n")
                name = "Рендер" if mode == "audition" else mode
                script = next(s["run"] for s in steps if s.get("name") == name)
                script = "\n".join(":" if line.strip().startswith(("pip install", "sudo ")) else line
                                   for line in script.splitlines())
                script = script.replace("python video.py", f'"{Path(sys.executable).as_posix()}" video.py')
                env = dict(os.environ, CI_VOICES=malicious, CI_TAKES=malicious, CI_EP="demo_layouts",
                           CI_AUDITION=malicious if mode == "audition" else "",
                           FV_DRAFT="1", FV_SILENT="1", EPISODES="demo_layouts")
                subprocess.run([bash, "-e", "-o", "pipefail", "-c", script], cwd=root, env=env,
                               text=True, encoding="utf-8", capture_output=True, check=True)
                args = json.loads((root / "arguments.json").read_text())
                if mode == "Рендер":
                    self.assertEqual(args, ["episodes/demo_layouts.json", "out/demo_layouts_draft.mp4"])
                else:
                    self.assertIn(malicious, args)
                self.assertFalse(any(root.glob("injected*")))


if __name__ == "__main__":
    unittest.main()
