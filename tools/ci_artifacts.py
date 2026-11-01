"""Offline-testable episode selection and additive, fast-forward CI publication."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import quote


EPISODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
INDEX_START = "<!-- ci-artifacts:start -->"
INDEX_END = "<!-- ci-artifacts:end -->"


def git(repo, *args, check=True, input=None):
    return subprocess.run(
        ["git", "-c", "user.name=Codex", "-c", "user.email=codex@openai.com",
         "-C", str(repo), *args],
        input=input, text=True, encoding="utf-8", capture_output=True, check=check,
    )


def ensure_commit(repo, sha):
    if not SHA.fullmatch(sha):
        raise ValueError("Expected a full commit SHA")
    if git(repo, "cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode:
        # A force push can leave the event's before outside the fetched branch history.
        git(repo, "fetch", "--no-tags", "origin", sha)
    git(repo, "cat-file", "-e", f"{sha}^{{commit}}")


def select_episodes(repo, event, sha, before="", requested="", audition=""):
    ensure_commit(repo, sha)
    files = git(repo, "ls-tree", "-r", "--name-only", "-z", sha).stdout.split("\0")
    available = {Path(p).stem for p in files
                 if p.startswith("episodes/") and p.count("/") == 1
                 and p.endswith(".json") and EPISODE.fullmatch(Path(p).stem)}
    if requested:
        if not EPISODE.fullmatch(requested) or requested not in available:
            raise ValueError("ep must name an existing episodes/<name>.json")
        return [requested]
    if audition:
        raise ValueError("audition requires ep")
    if event == "push":
        if not SHA.fullmatch(before):
            raise ValueError("push requires the full before SHA")
        if set(before) == {"0"}:
            return sorted(available)
        ensure_commit(repo, before)
        base = before
    elif event == "workflow_dispatch":
        parents = git(repo, "rev-list", "--parents", "-n", "1", sha).stdout.split()
        if len(parents) == 1:
            return sorted(available)
        base = parents[1]
    else:
        raise ValueError(f"Unsupported event: {event}")
    changed = git(repo, "diff", "--no-renames", "--name-only", "-z", base, sha,
                  "--", "episodes/", "voice/").stdout.split("\0")
    selected = set()
    for path in changed:
        parts = path.split("/")
        if len(parts) == 2 and parts[0] == "episodes" and path.endswith(".json"):
            selected.add(Path(path).stem)
        elif len(parts) >= 3 and parts[0] == "voice":
            selected.add(parts[1])
    return sorted(selected & available)


def remote_tip(repo, branch):
    ref = f"refs/heads/{branch}"
    result = git(repo, "ls-remote", "--exit-code", "--heads", "origin", ref, check=False)
    if result.returncode == 2:
        return None
    result.check_returncode()  # Authentication/network failure is not a missing branch.
    git(repo, "fetch", "--no-tags", "origin", ref)
    return git(repo, "rev-parse", "FETCH_HEAD").stdout.strip()


def update_index(worktree):
    readme = worktree / "README.md"
    previous = readme.read_text(encoding="utf-8") if readme.exists() else "# Ролики Admiral 8\n"
    links = []
    for path in sorted(worktree.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".mp4", ".mp3", ".wav", ".png", ".jpg", ".webp"}:
            relative = path.relative_to(worktree).as_posix()
            label = relative.replace("[", "\\[").replace("]", "\\]")
            links.append(f"- [{label}]({quote(relative, safe='/')}?raw=true)")
    block = INDEX_START + "\n\n## Файлы\n\n" + "\n".join(links) + "\n\n" + INDEX_END
    if INDEX_START in previous and INDEX_END in previous:
        start = previous.index(INDEX_START)
        end = previous.index(INDEX_END, start) + len(INDEX_END)
        previous = previous[:start] + block + previous[end:]
    else:
        previous = previous.rstrip() + "\n\n" + block + "\n"
    readme.write_text(previous, encoding="utf-8")


def publish(repo, source, branch, message, attempts=5):
    """Overlay only supplied files; a rejected push is reapplied to the new tip.

    Same-path replacements are intentional; previous bytes remain in Git history.
    A separate worktree keeps the source checkout and index untouched.
    """
    if branch not in {"renders", "takes", "assets"}:
        raise ValueError("Unsupported artifact branch")
    repo, source = Path(repo).resolve(), Path(source).resolve()
    if not source.exists():
        return None
    payload = []
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if path.is_symlink() or any(p.lower() == ".git" for p in relative.parts):
            raise ValueError("Artifact payload must not contain symlinks or .git")
        if path.is_file():
            payload.append((path, relative))
    if not payload:
        return None
    for _ in range(attempts):
        base = remote_tip(repo, branch)
        start = base
        if start is None:
            tree = git(repo, "hash-object", "-w", "-t", "tree", "--stdin", input="").stdout.strip()
            start = git(repo, "commit-tree", tree, "-m", f"Initialize {branch}").stdout.strip()
        with tempfile.TemporaryDirectory(prefix="ci_publish_") as tmp:
            worktree = Path(tmp) / "tree"
            git(repo, "worktree", "add", "--detach", str(worktree), start)
            try:
                for path, relative in payload:
                    target = worktree / relative
                    if any(p.is_symlink() for p in [target, *target.parents] if p != worktree.parent):
                        raise ValueError("Artifact destination must not traverse symlinks")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
                if branch in {"renders", "takes"}:
                    if (worktree / "README.md").is_symlink():
                        raise ValueError("README must not be a symlink")
                    update_index(worktree)
                # Include logs and media even if the artifact branch has ignore rules.
                git(worktree, "add", "--all", "--force")
                changed = git(worktree, "diff", "--cached", "--quiet", check=False)
                if changed.returncode == 0:
                    return base
                if changed.returncode != 1:
                    changed.check_returncode()
                git(worktree, "commit", "-m", message)
                commit = git(worktree, "rev-parse", "HEAD").stdout.strip()
                pushed = git(worktree, "push", "origin", f"HEAD:refs/heads/{branch}", check=False)
                if pushed.returncode == 0:
                    return commit
                if remote_tip(repo, branch) == base:
                    pushed.check_returncode()
            finally:
                git(repo, "worktree", "remove", "--force", str(worktree))
    raise RuntimeError(f"{branch} kept changing; publication failed after {attempts} attempts")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("select")
    publication = commands.add_parser("publish")
    publication.add_argument("source", type=Path)
    publication.add_argument("branch", choices=["renders", "takes", "assets"])
    args = parser.parse_args()
    if args.command == "select":
        episodes = select_episodes(Path.cwd(), os.environ["GITHUB_EVENT_NAME"],
                                   os.environ["GITHUB_SHA"], os.getenv("CI_BEFORE", ""),
                                   os.getenv("CI_EP", ""), os.getenv("CI_AUDITION", ""))
        value = " ".join(episodes)
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"list={value}\n")
        print("выпуски:", value or "нет")
    else:
        publish(Path.cwd(), args.source, args.branch,
                f"CI artifacts {os.getenv('GITHUB_SHA', '')[:7]}")


if __name__ == "__main__":
    main()
