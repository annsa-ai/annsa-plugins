"""Annsa principle enforcement: decide whether one Bash command may run.

Input: on stdin, either Claude Code's PreToolUse JSON (tool_input.command, cwd, session_id)
or, with --cursor, Cursor's beforeShellExecution JSON (command, cwd, conversation_id).
Output: Claude Code gets nothing (allow), a deny decision, or a one-time note to the person.
Cursor treats an empty answer as a failure, so it always gets {"permission": ...}.

The list of enforced principles and the patterns for each kind come from Annsa
(GET /mcp/enforce). Matching happens here, on this machine; Annsa is only called
again to record a block. When anything is unclear, the command runs.
"""

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request

HOME = os.path.expanduser("~/.annsa")
FRESH_SECONDS = 300
STALE_LIMIT_SECONDS = 24 * 3600
FETCH_TIMEOUT = 1.5
POST_TIMEOUT = 1.5
GIT_TIMEOUT = 2.0
CURSOR = "--cursor" in sys.argv[1:]
ANSWERED = []  # set once something was printed
WRAPPERS = {"sudo", "command", "time", "nohup", "exec"}


# ---------- config ----------


def config():
    """API host and token. ~/.annsa/enforce.json overrides the defaults (used to
    point a dogfood install at staging); ANNSA_API_URL and ANNSA_TOKEN override that."""
    cfg = {"api": "https://api.annsa.ai", "token_file": os.path.join(HOME, "token.json")}
    path = os.environ.get("ANNSA_ENFORCE_CONFIG", os.path.join(HOME, "enforce.json"))
    try:
        with open(path) as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    cfg["api"] = os.environ.get("ANNSA_API_URL", cfg["api"]).rstrip("/")
    # The token only ever goes over HTTPS (plain HTTP only to this machine, for tests).
    if not re.match(r"^(https://|http://(127\.0\.0\.1|localhost)(:\d+)?(/|$))", cfg["api"]):
        cfg["api"] = "https://api.annsa.ai"
    token = os.environ.get("ANNSA_TOKEN")
    if not token:
        try:
            with open(os.path.expanduser(cfg["token_file"])) as f:
                raw = f.read().strip()
            token = json.loads(raw).get("token") if raw.startswith("{") else raw
        except (OSError, ValueError, AttributeError):
            token = None
    cfg["token"] = token
    return cfg


def cache_path(cfg):
    key = hashlib.sha256(f"{cfg['api']}|{cfg['token']}".encode()).hexdigest()[:16]
    return os.path.join(HOME, f"enforce-{key}.json")


# ---------- the enforce list ----------


def fetch(cfg, etag=None):
    """Returns (status, data, etag). status is 'ok', 'same' or 'error'."""
    req = urllib.request.Request(cfg["api"] + "/mcp/enforce")
    req.add_header("Authorization", "Bearer " + cfg["token"])
    req.add_header("Accept", "application/json")
    if etag:
        req.add_header("If-None-Match", etag)
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            if "json" not in resp.headers.get("Content-Type", ""):
                return "error", None, None  # an HTML fallback page, not the API
            return "ok", json.load(resp), resp.headers.get("ETag")
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return "same", None, etag
        return "error", None, None
    except (OSError, ValueError):
        return "error", None, None


def save(path, data, etag):
    tmp = path + ".tmp"
    private_write(tmp, [json.dumps({"fetched_at": time.time(), "etag": etag, "data": data})])
    os.replace(tmp, path)


def refresh(cfg, path, cached):
    status, data, etag = fetch(cfg, cached.get("etag") if cached else None)
    if status == "ok":
        save(path, data, etag)
        return data
    if status == "same" and cached:
        save(path, cached["data"], etag)
        return cached["data"]
    return None


def enforce_list(cfg):
    """The current list, or None when Annsa can't be reached and nothing usable is cached."""
    fixture = os.environ.get("ANNSA_ENFORCE_FIXTURE")
    if fixture:
        with open(fixture) as f:
            return json.load(f)
    path = cache_path(cfg)
    try:
        with open(path) as f:
            cached = json.load(f)
    except (OSError, ValueError):
        cached = None
    if cached:
        age = time.time() - cached.get("fetched_at", 0)
        if age < FRESH_SECONDS:
            return cached["data"]
        if age < STALE_LIMIT_SECONDS:
            # Use the cache now and refresh in the background, so the command never waits.
            subprocess.Popen(
                [sys.executable, os.path.abspath(__file__), "--refresh"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return cached["data"]
    return refresh(cfg, path, cached)


# ---------- splitting a command into what actually runs ----------


def split_outside_quotes(command):
    """Split on && || ; | and newlines, but never inside quotes, so a commit message
    that says "fix; rm -rf x" stays one argument."""
    parts, buf, quote, i = [], [], None, 0
    while i < len(command):
        c = command[i]
        if quote:
            buf.append(c)
            if c == "\\" and quote == '"' and i + 1 < len(command):
                buf.append(command[i + 1])
                i += 1
            elif c == quote:
                quote = None
        elif c in ("'", '"'):
            quote = c
            buf.append(c)
        elif c == "\\" and i + 1 < len(command):
            buf.append(c + command[i + 1])
            i += 1
        elif command.startswith(("&&", "||"), i):
            parts.append("".join(buf))
            buf = []
            i += 1
        elif c in ";|\n":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    parts.append("".join(buf))
    return parts


def segments(command, depth=0):
    """Every simple command inside `command`, one level into bash -c, eval and $( )."""
    out = []
    for inner in re.findall(r"\$\(([^()]*)\)", command):
        if depth < 1:
            out.extend(segments(inner, depth + 1))
    for part in split_outside_quotes(command):
        part = part.strip()
        if not part:
            continue
        try:
            words = shlex.split(part, posix=True)
        except ValueError:
            words = part.split()
        while words and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]) or words[0] in WRAPPERS):
            words = words[1:]
        if not words:
            continue
        if depth < 1 and words[0] in ("bash", "sh", "zsh") and "-c" in words:
            i = words.index("-c")
            if i + 1 < len(words):
                out.extend(segments(words[i + 1], depth + 1))
                continue
        if depth < 1 and words[0] == "eval":
            out.extend(segments(" ".join(words[1:]), depth + 1))
            continue
        out.append(words)
    return out


def with_dirs(command, cwd):
    """Pair each segment with the directory it acts in, following cd and git -C."""
    here = cwd or os.getcwd()
    pairs = []
    for words in segments(command):
        if words[0] in ("cd", "pushd") and len(words) > 1:
            here = os.path.normpath(os.path.join(here, os.path.expanduser(words[1])))
            continue
        where = here
        if words[0] == "git" and len(words) > 2 and words[1] == "-C":
            where = os.path.normpath(os.path.join(here, os.path.expanduser(words[2])))
            words = ["git"] + words[3:]
        pairs.append((" ".join(words), where))
    return pairs


# ---------- facts about the repo, read only when a pattern needs them ----------


def git(where, *args):
    try:
        r = subprocess.run(
            ["git", "-C", where, *args], capture_output=True, text=True, timeout=GIT_TIMEOUT
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def default_branches(where):
    ref = git(where, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if ref and "/" in ref:
        return [ref.split("/", 1)[1]]
    return ["main", "master"]


def head_is_default(where):
    head = git(where, "rev-parse", "--abbrev-ref", "HEAD")
    return head is not None and head in default_branches(where)


def pr_base_is_default(line, where):
    m = re.match(r"^gh pr merge(?: +(?!-)(\S+))?", line)
    target = m.group(1) if m else None
    args = ["gh", "pr", "view"] + ([target] if target else []) + ["--json", "baseRefName", "-q", ".baseRefName"]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=GIT_TIMEOUT, cwd=where)
    except (OSError, subprocess.TimeoutExpired):
        return False  # can't tell, so it runs
    base = r.stdout.strip() if r.returncode == 0 else None
    return bool(base) and base in default_branches(where)


# ---------- matching ----------


def matches(rule, line, where):
    pattern = rule["re"]
    if "{default}" in pattern:
        alts = "|".join(re.escape(b) for b in default_branches(where))
        pattern = pattern.replace("{default}", alts)
    flags = re.IGNORECASE if rule.get("icase") else 0
    if not re.search(pattern, line, flags):
        return False
    if rule.get("no_dotdot") and ".." in line:
        return False
    when = rule.get("when")
    if when == "head_is_default":
        return head_is_default(where)
    if when == "pr_base_is_default":
        return pr_base_is_default(line, where)
    if when:
        return False  # a condition this script doesn't know yet: don't refuse on it
    return True


def first_block(command, cwd, data):
    """(principle, kind, line, where) for the first segment an enforced principle refuses."""
    kinds = data.get("kinds") or {}
    for line, where in with_dirs(command, cwd):
        for p in data.get("principles") or []:
            kind = kinds.get(p.get("kind"))
            if not kind:
                continue
            if any(matches(r, line, where) for r in kind.get("allow", [])):
                continue
            if any(matches(r, line, where) for r in kind.get("refuse", [])):
                return p, kind, line, where
    return None


# ---------- telling Annsa, telling the person ----------

SECRET_PATTERNS = [
    (re.compile(r"(?i)\b(bearer|token|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 [redacted]"),
    (re.compile(r"(?i)\b([A-Z0-9_]*(TOKEN|SECRET|KEY|PASSWORD|PASS|PWD|AUTH)[A-Z0-9_]*)=\S+"), r"\1=[redacted]"),
    (re.compile(r"(?i)(--?(token|password|pass|secret|api[-_]?key|key)[= ])\S+"), r"\1[redacted]"),
    (re.compile(r"(?i)(\-p)(\S{4,})"), r"\1[redacted]"),
    (re.compile(r"\b(sk|pk|rk)[-_][A-Za-z0-9_-]{12,}"), "[redacted]"),
    (re.compile(r"\b(ghp|gho|ghs|ghu|github_pat|glpat|xox[abprs]|mcp)_[A-Za-z0-9_-]{8,}"), "[redacted]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[redacted]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"), "[redacted]"),
    (re.compile(r"://([^/\s:@]+):([^@\s/]+)@"), r"://\1:[redacted]@"),
]


def redact(text):
    """Strip anything that looks like a credential before the command leaves the
    hook: Annsa redacts again on arrival, but the queue on disk sees it first."""
    for pattern, repl in SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text[:300]


def private_write(path, lines):
    """Write a file only this user can read."""
    os.makedirs(HOME, mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.writelines(lines)
    os.chmod(path, 0o600)


def post_block(cfg, body):
    queue = os.path.join(HOME, "enforce-queue.jsonl")
    pending = []
    try:
        with open(queue) as f:
            pending = [json.loads(x) for x in f if x.strip()]
    except (OSError, ValueError):
        pass
    todo = pending + [body]
    sent = 0
    for item in todo:
        req = urllib.request.Request(
            cfg["api"] + "/mcp/enforce/blocks",
            data=json.dumps(item).encode(),
            method="POST",
        )
        req.add_header("Authorization", "Bearer " + cfg["token"])
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=POST_TIMEOUT):
                sent += 1
        except (OSError, ValueError):
            break  # Annsa is unreachable: keep this and the rest for next time
    left = todo[sent:]
    try:
        private_write(queue, [json.dumps(item) + "\n" for item in left[-200:]])
    except OSError:
        pass


def once(session_id, key, message):
    """A note to the person, at most once per session for each key."""
    marks = os.path.join(HOME, "enforce-sessions")
    mark = os.path.join(marks, f"{session_id or 'none'}.{key}")
    if os.path.exists(mark):
        return
    try:
        os.makedirs(marks, exist_ok=True)
        open(mark, "w").close()
    except OSError:
        pass
    ANSWERED.append(1)
    if CURSOR:
        print(json.dumps({"permission": "allow", "user_message": message}))
    else:
        print(json.dumps({"systemMessage": message}))


def deny(principle, kind, line):
    number = principle.get("number")
    name = f"\"{principle.get('title', 'your principle')}\"" + (f" (#{number})" if number else "")
    reason = (
        f"Your principle {name} blocks this, as {kind.get('what', 'a refused command')}: `{line}`. "
        "Say it's ready for a person to run instead. This block is logged on the principle in Annsa."
    )
    ANSWERED.append(1)
    if CURSOR:
        print(json.dumps({"permission": "deny", "user_message": reason, "agent_message": reason}))
        return
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )


def repo_name(where):
    top = git(where, "rev-parse", "--show-toplevel")
    return os.path.basename(top) if top else os.path.basename(where)


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return
    if CURSOR:
        command = (event.get("command") or "").strip()
        session_id = event.get("conversation_id") or event.get("session_id")
    else:
        command = ((event.get("tool_input") or {}).get("command") or "").strip()
        session_id = event.get("session_id")
    if not command:
        return
    cfg = config()
    if not cfg["token"] and not os.environ.get("ANNSA_ENFORCE_FIXTURE"):
        once(session_id, "token", "Annsa isn't enforcing your principles here: run `npx annsa auth`.")
        return
    data = enforce_list(cfg)
    if data is None:
        once(session_id, "offline", "Annsa can't be reached, so your principles aren't enforced in this session.")
        return
    hit = first_block(command, event.get("cwd"), data) if data.get("principles") else None
    if not hit:
        return
    principle, kind, line, where = hit
    deny(principle, kind, line)
    if not os.environ.get("ANNSA_ENFORCE_NO_POST"):
        post_block(
            cfg,
            {
                "principle_id": principle.get("principle_id"),
                "kind": principle.get("kind"),
                "command": redact(line),
                "dir": repo_name(where),
                "session_id": session_id,
            },
        )


if __name__ == "__main__":
    if "--refresh" in sys.argv[1:]:
        c = config()
        if c["token"]:
            p = cache_path(c)
            try:
                with open(p) as f:
                    old = json.load(f)
            except (OSError, ValueError):
                old = None
            refresh(c, p, old)
    else:
        try:
            main()
        except Exception:  # never break a command because the hook broke
            pass
        if CURSOR and not ANSWERED:
            print(json.dumps({"permission": "allow"}))  # Cursor wants an answer every time
