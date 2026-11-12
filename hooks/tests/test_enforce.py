"""Planted cases for the enforcement hook: every refusal next to the read it must let through.

Run: python3 -m pytest hooks/tests -q  (or python3 hooks/tests/test_enforce.py)
Uses the catalogue Annsa served on staging (fixture.json) with every kind switched on,
and never calls Annsa.
"""

import json
import os
import subprocess
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "enforce.sh")
FIXTURE = os.path.join(HERE, "fixture.json")


def repo(branch):
    d = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q", "-b", "main", d], check=True)
    subprocess.run(["git", "-C", d, "commit", "-q", "--allow-empty", "-m", "x"], check=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    if branch != "main":
        subprocess.run(["git", "-C", d, "checkout", "-q", "-b", branch], check=True)
    return d


ON_MAIN = repo("main")
ON_FEATURE = repo("feature/x")


def run(command, cwd=ON_FEATURE, fixture=FIXTURE, extra=None):
    env = {**os.environ, "ANNSA_ENFORCE_FIXTURE": fixture, "ANNSA_ENFORCE_NO_POST": "1",
           "HOME": tempfile.mkdtemp(), **(extra or {})}
    event = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd,
             "session_id": "test"}
    out = subprocess.run(["bash", HOOK], input=json.dumps(event), capture_output=True,
                         text=True, env=env, timeout=10).stdout.strip()
    return json.loads(out) if out else None


def run_cursor(command, cwd=ON_FEATURE, extra=None):
    env = {**os.environ, "ANNSA_ENFORCE_FIXTURE": FIXTURE, "ANNSA_ENFORCE_NO_POST": "1",
           "HOME": tempfile.mkdtemp(), **(extra or {})}
    event = {"command": command, "cwd": cwd, "conversation_id": "test", "sandbox": False}
    r = subprocess.run(["bash", HOOK, "--cursor"], input=json.dumps(event), capture_output=True,
                       text=True, env=env, timeout=10)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)  # Cursor needs valid JSON every time


def refused(out):
    return bool(out) and out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


REFUSE = [
    ("gh workflow run deploy.yml", ON_FEATURE),
    ("vercel --prod", ON_FEATURE),
    ("vercel deploy --prod", ON_FEATURE),
    ("terraform apply", ON_FEATURE),
    ("pnpm run deploy:prod", ON_FEATURE),
    ("git push origin main", ON_FEATURE),
    ("git push", ON_MAIN),
    ("git merge feature/x", ON_MAIN),
    ("gh pr review 12 --approve", ON_FEATURE),
    ("rm -rf src", ON_FEATURE),
    ("rm -fr ~/projects", ON_FEATURE),
    ("git reset --hard HEAD~3", ON_FEATURE),
    ("git clean -fd", ON_FEATURE),
    ("git push --force origin feature/x", ON_FEATURE),
    ("git branch -D old", ON_FEATURE),
    ("supabase db reset", ON_FEATURE),
    ('psql "$DB" -c "DROP TABLE users"', ON_FEATURE),
    # Hidden inside something else.
    ("cd /tmp && gh workflow run deploy.yml", ON_FEATURE),
    ("npm test && git push origin main", ON_FEATURE),
    ("bash -c 'git reset --hard'", ON_FEATURE),
    ("FOO=1 git push origin main", ON_FEATURE),
    ("sudo rm -rf /opt/app", ON_FEATURE),
    (f"git -C {ON_MAIN} push", ON_FEATURE),
]

ALLOW = [
    ("git status", ON_MAIN),
    ("git push", ON_FEATURE),
    ("git push origin feature/x", ON_FEATURE),
    ("git push --dry-run origin main", ON_FEATURE),
    ("git merge main", ON_FEATURE),
    ("gh workflow list", ON_FEATURE),
    ("gh pr view 12", ON_FEATURE),
    ("gh pr review 12 --comment -b ok", ON_FEATURE),
    ("vercel ls", ON_FEATURE),
    ("terraform plan", ON_FEATURE),
    ("rm -rf node_modules", ON_FEATURE),
    ("rm -rf dist build .next", ON_FEATURE),
    ("rm -rf /tmp/scratch", ON_FEATURE),
    ("rm file.txt", ON_FEATURE),
    ("git clean -n", ON_FEATURE),
    ("pytest -q", ON_FEATURE),
    ("ls -la", ON_FEATURE),
    # A quoted mention is an argument, not a command.
    ('git commit -m "fix; rm -rf src && git push origin main"', ON_FEATURE),
    ("echo 'vercel --prod'", ON_FEATURE),
    ("grep -r 'git reset --hard' docs", ON_FEATURE),
]


def test_every_refusal_is_refused():
    missed = [c for c, d in REFUSE if not refused(run(c, d))]
    assert not missed, missed


def test_every_read_runs():
    blocked = [c for c, d in ALLOW if refused(run(c, d))]
    assert not blocked, blocked


def test_the_refusal_names_the_principle():
    out = run("vercel --prod")
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert '"Test deploy" (#1)' in reason and "vercel --prod" in reason


def test_nothing_switched_on_refuses_nothing():
    data = json.load(open(FIXTURE))
    data["principles"] = []
    path = tempfile.mktemp(suffix=".json")
    json.dump(data, open(path, "w"))
    assert run("gh workflow run deploy.yml", fixture=path) is None


def test_switched_off_machine_wide():
    assert run("vercel --prod", extra={"ANNSA_ENFORCE": "0"}) is None


def test_no_token_runs_and_says_so_once():
    env = {"ANNSA_ENFORCE_FIXTURE": "", "ANNSA_TOKEN": "", "ANNSA_ENFORCE_CONFIG": "/nonexistent"}
    out = run("vercel --prod", extra=env)
    assert not refused(out)
    assert "npx annsa auth" in out["systemMessage"]


def test_unreachable_runs_and_says_so():
    env = {"ANNSA_ENFORCE_FIXTURE": "", "ANNSA_TOKEN": "x", "ANNSA_API_URL": "http://127.0.0.1:9", "ANNSA_ENFORCE_DEV": "1",
           "ANNSA_ENFORCE_CONFIG": "/nonexistent"}
    out = run("vercel --prod", extra=env)
    assert not refused(out)
    assert "can't be reached" in out["systemMessage"]


def test_secrets_never_leave_the_hook():
    import importlib.util
    spec = importlib.util.spec_from_file_location("enforce", os.path.join(HERE, "..", "enforce.py"))
    enforce = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(enforce)
    secrets = {
        "GITHUB_TOKEN=ghp_abcdefghijklmnop1234 gh workflow run deploy.yml": "ghp_abcdefghijklmnop1234",
        "vercel --prod --token abc123secretvalue": "abc123secretvalue",
        "curl -H 'Authorization: Bearer eyJhbGciOi.eyJzdWIiOiIx.c2lnbmF0dXJl' x": "eyJhbGciOi",
        "psql postgres://admin:hunter22pw@db.example.com -c 'DROP TABLE x'": "hunter22pw",
        "mysql -uroot -pS3cretPass -e 'drop database x'": "S3cretPass",
        "OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrst terraform apply": "sk-proj-abcdefghijklmnopqrst",
        "AWS_SECRET_ACCESS_KEY=abc/def+ghi aws apprunner start-deployment": "abc/def+ghi",
        "ANNSA_TOKEN=mcp_0123456789abcdef git push origin main": "mcp_0123456789abcdef",
    }
    leaked = [c for c, s in secrets.items() if s in enforce.redact(c)]
    assert not leaked, leaked
    assert enforce.redact("git push origin main") == "git push origin main"


def test_the_token_only_goes_over_https():
    import importlib.util
    spec = importlib.util.spec_from_file_location("enforce", os.path.join(HERE, "..", "enforce.py"))
    enforce = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(enforce)
    old = os.environ.get("ANNSA_API_URL")
    try:
        os.environ["ANNSA_API_URL"] = "http://evil.example.com"
        assert enforce.config()["api"] == "https://api.annsa.ai"
        os.environ["ANNSA_API_URL"] = "https://canopy.annsa.ai"
        assert enforce.config()["api"] == "https://canopy.annsa.ai"
    finally:
        if old is None:
            os.environ.pop("ANNSA_API_URL", None)
        else:
            os.environ["ANNSA_API_URL"] = old


def test_cursor_push_to_main_is_denied_and_a_feature_push_allowed():
    out = run_cursor("git push origin main")
    assert out["permission"] == "deny" and "git push origin main" in out["agent_message"]
    assert run_cursor("git push origin feature/x") == {"permission": "allow"}


def test_cursor_always_gets_a_valid_answer():
    assert run_cursor("ls -la") == {"permission": "allow"}  # fast path
    assert run_cursor("git status") == {"permission": "allow"}  # past the fast path
    assert run_cursor("vercel --prod", extra={"ANNSA_ENFORCE": "0"}) == {"permission": "allow"}


def test_cursor_unreachable_allows():
    env = {"ANNSA_ENFORCE_FIXTURE": "", "ANNSA_TOKEN": "x", "ANNSA_API_URL": "http://127.0.0.1:9", "ANNSA_ENFORCE_DEV": "1",
           "ANNSA_ENFORCE_CONFIG": "/nonexistent"}
    out = run_cursor("git push origin main", extra=env)
    assert out["permission"] == "allow" and "can't be reached" in out["user_message"]


def test_the_hook_files_are_valid_and_wired():
    root = os.path.join(HERE, "..", "..")
    claude = json.load(open(os.path.join(root, ".claude-plugin", "plugin.json")))
    cursor = json.load(open(os.path.join(root, ".cursor-plugin", "plugin.json")))
    assert os.path.exists(os.path.join(root, claude["hooks"]))
    assert os.path.exists(os.path.join(root, cursor["hooks"]))
    assert "url" not in cursor.get("author", {})
    json.load(open(os.path.join(root, claude["hooks"])))["hooks"]["PreToolUse"]
    json.load(open(os.path.join(root, cursor["hooks"])))["hooks"]["beforeShellExecution"]
    versions = {json.load(open(os.path.join(root, f))).get("version") for f in
                (".claude-plugin/plugin.json", ".cursor-plugin/plugin.json",
                 ".codex-plugin/plugin.json", ".grok-plugin/plugin.json")}
    assert len(versions) == 1, versions


def load_enforce(home):
    import importlib.util
    old = os.environ.get("HOME")
    os.environ["HOME"] = home
    try:
        spec = importlib.util.spec_from_file_location("enforce_" + os.path.basename(home),
                                                      os.path.join(HERE, "..", "enforce.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        os.environ["HOME"] = old
    return mod


def run_raw(raw_json, cwd=ON_FEATURE):
    env = {**os.environ, "ANNSA_ENFORCE_FIXTURE": FIXTURE, "ANNSA_ENFORCE_NO_POST": "1",
           "HOME": tempfile.mkdtemp()}
    out = subprocess.run(["bash", HOOK], input=raw_json, capture_output=True, text=True,
                         env=env, timeout=10).stdout.strip()
    return json.loads(out) if out else None


BYPASS = [
    "/usr/bin/git push origin main",
    "./git push origin main",
    "env git push origin main",
    "env -i FOO=1 git push origin main",
    "echo main | xargs git push origin",
    "echo main | xargs -I{} git push origin {}",
    "sudo -u root git push origin main",
    "command git push origin main",
    "nohup git push origin main",
    "git -c core.pager=cat push origin main",
    "git --no-pager push origin main",
    "git -c a=b -c c=d push origin main",
    'bash -c "git push origin main"',
    "sh -lc 'git push origin main'",
    "zsh -c 'cd /tmp && git push origin main'",
    "bash -c \"bash -c 'git push origin main'\"",
    "echo $(git push origin main)",
    "echo `git push origin main`",
    'echo "$(git push origin main)"',
    "cat <(git push origin main)",
    'eval "git push origin main"',
    "git status & git push origin main",
    "(git push origin main)",
    "if true; then git push origin main; fi",
    'g""it push origin main',
    "g\\it push origin main",
    "'git' push origin main",
    "X=git; $X push origin main",
    "$(echo git) push origin main",
    'bash -c "$CMD git push origin main"',
    "git push origin main 'unterminated",
]

STILL_ALLOWED = [
    "git status & echo hi",
    'echo "$(date)"',
    "sudo ls",
    "env FOO=1 ls",
    "git -c a=b status",
    "bash -c 'git status'",
    "echo 'it'\\''s $(git push origin main)'",
    "ls 2>&1",
    "find . -name '*.pyc' | xargs rm",
]


def test_every_bypass_is_refused():
    missed = [c for c in BYPASS if not refused(run(c))]
    assert not missed, missed


def test_bypass_cases_are_refused_for_cursor_too():
    missed = [c for c in BYPASS if run_cursor(c)["permission"] != "deny"]
    assert not missed, missed


def test_ordinary_wrapped_commands_still_run():
    blocked = [c for c in STILL_ALLOWED if refused(run(c))]
    assert not blocked, blocked


def test_json_escapes_are_decoded_before_matching():
    raw = '{"tool_input":{"command":"\\u0067it push origin main"},"cwd":"%s","session_id":"t"}' % ON_FEATURE
    assert refused(run_raw(raw))
    raw = '{"tool_input":{"command":"git push origin \\u006dain"},"cwd":"%s","session_id":"t"}' % ON_FEATURE
    assert refused(run_raw(raw))


def test_writes_into_the_annsa_folder_are_refused():
    for c in ["echo x > ~/.annsa/token.json", "cp evil.json ~/.annsa/enforce.json",
              "rm ~/.annsa/enforce-queue.jsonl", "cd ~/.annsa && echo '{}' > enforce.json",
              "tee $HOME/.annsa/token.json < x", "sed -i '' s/a/b/ ~/.annsa/token.json",
              "bash -c 'echo x >> ~/.annsa/token.json'"]:
        assert refused(run(c)), c
    for c in ["cat ~/.annsa/enforce.json", "ls -la ~/.annsa"]:
        assert not refused(run(c)), c


def test_a_planted_config_cannot_redirect_the_token():
    home = tempfile.mkdtemp()
    planted = os.path.join(home, "enforce.json")
    json.dump({"api": "https://evil.example.com", "token_file": "/etc/passwd"}, open(planted, "w"))
    env = {k: v for k, v in os.environ.items() if k not in ("ANNSA_API_URL", "ANNSA_TOKEN")}
    old = dict(os.environ)
    os.environ.clear()
    os.environ.update({**env, "ANNSA_ENFORCE_CONFIG": planted})
    try:
        enforce = load_enforce(home)
        cfg = enforce.config()
        assert cfg["api"] == "https://api.annsa.ai"
        assert cfg["token"] is None  # token_file in the config was ignored
        for bad in ["http://api.annsa.ai", "https://api.annsa.ai.evil.com", "https://evil.com/api.annsa.ai",
                    "https://api.annsa.ai@evil.com", "https://sub.annsa.ai", "http://127.0.0.1:8000",
                    "https://localhost"]:
            assert not enforce.api_ok(bad), bad
        for good in ["https://api.annsa.ai", "https://app.annsa.ai", "https://canopy.annsa.ai/x"]:
            assert enforce.api_ok(good), good
        os.environ["ANNSA_ENFORCE_DEV"] = "1"
        assert enforce.api_ok("http://127.0.0.1:8000") and not enforce.api_ok("https://evil.com")
    finally:
        os.environ.clear()
        os.environ.update(old)


def test_a_cache_dated_in_the_future_is_refetched():
    home = tempfile.mkdtemp()
    os.environ["ANNSA_ENFORCE_FIXTURE"] = ""
    enforce = load_enforce(home)
    cfg = {"api": "https://api.annsa.ai", "token": "t"}
    # Point the fetch at a closed local port so a refetch fails instead of returning the cache.
    os.environ["ANNSA_ENFORCE_DEV"] = "1"
    cfg["api"] = "http://127.0.0.1:9"
    path = enforce.cache_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for stamp in (time.time() + 10**9, "never", None):
        json.dump({"fetched_at": stamp, "etag": None, "data": {"principles": []}}, open(path, "w"))
        assert enforce.enforce_list(cfg) is None, stamp
    json.dump({"fetched_at": time.time(), "etag": None, "data": {"principles": []}}, open(path, "w"))
    assert enforce.enforce_list(cfg) == {"principles": []}
    os.environ.pop("ANNSA_ENFORCE_DEV")
    os.environ.pop("ANNSA_ENFORCE_FIXTURE")


def test_the_fast_path_is_fast():
    start = time.time()
    for _ in range(50):
        run("ls -la")
    per_call_ms = (time.time() - start) * 1000 / 50
    assert per_call_ms < 400, per_call_ms


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
