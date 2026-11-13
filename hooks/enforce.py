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
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import annsa_limits as limits  # the matchers for a workspace's own limits (1.2.0)
except Exception:  # a missing or broken file must not break a command: no limits then
    limits = None

HOME = os.path.expanduser("~/.annsa")
HOOK_VERSION = "2"  # sent as X-Annsa-Hook-Version: from 2 on, the server serves `limits` to this hook
FRESH_SECONDS = 300
STALE_LIMIT_SECONDS = 24 * 3600
FETCH_TIMEOUT = 1.5
POST_TIMEOUT = 1.5
GIT_TIMEOUT = 2.0
CURSOR = "--cursor" in sys.argv[1:]
ANSWERED = []  # set once something was printed
WRAPPERS = {"sudo", "command", "time", "nohup", "exec"}


# ---------- config ----------


API_HOSTS = {"api.annsa.ai", "app.annsa.ai", "canopy.annsa.ai"}
DEFAULT_API = "https://api.annsa.ai"


def api_ok(url):
    """The token only goes to Annsa's own hosts over HTTPS. Localhost is allowed only
    when ANNSA_ENFORCE_DEV=1 is set in the environment (never from a config file)."""
    try:
        u = urlsplit(url)
        host = (u.hostname or "").lower()
        u.port  # raises on a bad port
    except ValueError:
        return False
    if u.username or u.password:
        return False
    if u.scheme == "https" and host in API_HOSTS:
        return True
    return (
        os.environ.get("ANNSA_ENFORCE_DEV") == "1"
        and u.scheme in ("http", "https")
        and host in ("127.0.0.1", "localhost")
    )


def config():
    """API host and token. ~/.annsa/enforce.json (or ANNSA_ENFORCE_CONFIG) may name only
    `api`, and only an Annsa host; ANNSA_API_URL overrides that. The token comes from
    ANNSA_TOKEN or ~/.annsa/token.json, never from a path a config file names."""
    cfg = {"api": DEFAULT_API}
    path = os.environ.get("ANNSA_ENFORCE_CONFIG", os.path.join(HOME, "enforce.json"))
    try:
        with open(path) as f:
            loaded = json.load(f)
        if isinstance(loaded, dict) and isinstance(loaded.get("api"), str):
            cfg["api"] = loaded["api"]
    except (OSError, ValueError):
        pass
    cfg["api"] = os.environ.get("ANNSA_API_URL", cfg["api"]).rstrip("/")
    if not api_ok(cfg["api"]):
        cfg["api"] = DEFAULT_API
    token = os.environ.get("ANNSA_TOKEN")
    if not token:
        try:
            with open(os.path.join(HOME, "token.json")) as f:
                raw = f.read().strip()
            token = json.loads(raw).get("token") if raw.startswith("{") else raw
        except (OSError, ValueError, AttributeError):
            token = None
    cfg["token"] = token
    return cfg


def cache_path(cfg):
    # `|hook2`: a list cached by 1.1.0 holds no limits and must not answer a version-2 hook.
    key = hashlib.sha256(f"{cfg['api']}|{cfg['token']}|hook{HOOK_VERSION}".encode()).hexdigest()[:16]
    return os.path.join(HOME, f"enforce-{key}.json")


# ---------- the enforce list ----------


def fetch(cfg, etag=None):
    """Returns (status, data, etag). status is 'ok', 'same' or 'error'."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(cfg["api"] + "/mcp/enforce")
    req.add_header("Authorization", "Bearer " + cfg["token"])
    req.add_header("Accept", "application/json")
    req.add_header("X-Annsa-Hook-Version", HOOK_VERSION)
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
        fetched = cached.get("fetched_at")
        age = time.time() - fetched if isinstance(fetched, (int, float)) else -1
        if age < 0:
            cached = None  # a timestamp in the future is not to be trusted: refetch
    if cached:
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

# Words that run another command and are not themselves what matters.
WRAPPER_ARGS = {
    "sudo": {"-u", "-g", "-h", "-p", "-C", "-T", "-r", "-t", "-U", "-D", "-R"},
    "doas": {"-u", "-C"},
    "env": {"-u", "-C", "-S"},
    "nice": {"-n"},
    "ionice": {"-c", "-n", "-p"},
    "xargs": {"-I", "-n", "-P", "-L", "-s", "-d", "-E", "-a", "-J"},
    "timeout": {"-s", "-k"},
    "exec": {"-a"},
    "stdbuf": {"-i", "-o", "-e"},
    "caffeinate": {"-t", "-w"},
    "command": set(),
    "builtin": set(),
    "time": set(),
    "nohup": set(),
    "setsid": set(),
}
CONTROL_WORDS = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "(", "{(", "((", "&"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
GIT_GLOBAL_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix"}
GIT_GLOBAL_FLAGS = {"--no-pager", "-p", "-P", "--paginate", "--bare", "--no-replace-objects",
                    "--literal-pathspecs", "--no-optional-locks", "--no-lazy-fetch"}
MAX_DEPTH = 3
# Any of these in a command means an enforced principle could be in play.
VERB_RE = re.compile(
    r"\b(git|gh|vercel|netlify|fly|flyctl|railway|aws|terraform|npm|pnpm|yarn|bun|rm|psql|mysql|sqlite3|supabase)\b"
)
DYNAMIC_RE = re.compile(r"[$`*?\[{]")
ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def split_outside_quotes(command):
    """Split on && || ; | & and newlines, but never inside quotes, so a commit message
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
        elif c == "&" and (i == 0 or command[i - 1] not in "<>&") and not command.startswith(">", i + 1):
            parts.append("".join(buf))  # a background `&`, not `2>&1` or `&>`
            buf = []
        elif c in ";|\n":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    parts.append("".join(buf))
    return parts


def substitutions(s):
    """The inside of every $( ), backtick and <( ) in `s`, skipping single quotes."""
    out, i, sq, dq = [], 0, False, False
    while i < len(s):
        c = s[i]
        if sq:
            sq = c != "'"
        elif c == "\\":
            i += 1
        elif c == "'" and not dq:
            sq = True
        elif c == '"':
            dq = not dq
        elif c == "`":
            j = i + 1
            while j < len(s) and s[j] != "`":
                j += 2 if s[j] == "\\" else 1
            out.append(s[i + 1 : j])
            i = j
        elif c in "$<>" and s.startswith("(", i + 1):
            depth, j = 1, i + 2
            while j < len(s) and depth:
                depth += (s[j] == "(") - (s[j] == ")")
                j += 1
            out.append(s[i + 2 : j - (1 if depth == 0 else 0)])
            i += 1
        i += 1
    return out


def strip_wrapper(name, words):
    """Drop a wrapper's own options and return the command it runs."""
    takes_arg = WRAPPER_ARGS[name]
    while words:
        w = words[0]
        if w == "--":
            words = words[1:]
            break
        if w.startswith("-") and len(w) > 1:
            words = words[2:] if w in takes_arg else words[1:]
            continue
        break
    if name == "timeout" and words:
        words = words[1:]  # the duration
    return words


def strip_prefix(words):
    """Peel assignments, control words and wrappers off the front. Returns (words, via_xargs)."""
    via_xargs = False
    while words:
        w = words[0]
        if ASSIGN_RE.match(w) or w in CONTROL_WORDS:
            words = words[1:]
            continue
        name = os.path.basename(w)
        if name in WRAPPER_ARGS:
            via_xargs = via_xargs or name == "xargs"
            words = strip_wrapper(name, words[1:])
            continue
        words = [name] + words[1:]
        break
    return words, via_xargs


INLINE_CODE = {  # command: the flags that hand it code or another command to run
    "perl": {"-e", "-E"}, "ruby": {"-e"}, "node": {"-e", "-p", "--eval"}, "nodejs": {"-e"},
    "php": {"-r"}, "lua": {"-e"}, "script": {"-c"}, "awk": set(), "gawk": set(),
    "find": {"-exec", "-execdir", "-ok", "-okdir", "-delete"},
    "watch": None, "flock": None,  # always run another command
}


def runs_inline_code(head, words):
    """True for an interpreter or runner that carries code or a command the parser can't read."""
    if re.match(r"^python[0-9.]*$", head):
        return any(re.match(r"^-[A-Za-z]*c$", w) for w in words[1:])
    if head not in INLINE_CODE:
        return False
    flags = INLINE_CODE[head]
    if flags is None:
        return True
    return any(w in flags or (head in ("perl", "ruby") and re.match(r"^-[A-Za-z]*e$", w)) for w in words[1:])


def strip_prefix_tokens(tokens):
    """The raw tokens of one segment with the same prefix dropped that strip_prefix drops
    from its words, so a path limit reads `rm .env` behind `sudo` or `env X=1`."""
    plain = []
    for t in tokens:
        d = limits._dequote(t)
        plain.append(t if d is None else d)
    rest, _ = strip_prefix(plain)
    kept = tokens[len(tokens) - len(rest):] if rest else []
    return ([rest[0]] + kept[1:]) if kept else []


def segment_entries(command, issues, depth=0):
    """Every simple command inside `command` as {words, before, tokens, xargs}: `words`
    after wrappers are stripped, `before` as written, `tokens` the quote-aware tokens a path
    limit reads. Followed into bash -c, eval, $( ) and backticks. Anything that can't be
    followed is noted in `issues`."""
    out = []
    if depth >= MAX_DEPTH:
        issues.append("too deeply nested")
        return out
    for inner in substitutions(command):
        out.extend(segment_entries(inner, issues, depth + 1))
    for part in split_outside_quotes(command):
        part = part.strip()
        if not part:
            continue
        grouped = part.startswith("(")
        try:
            words = shlex.split(part.lstrip("({ "), posix=True)
        except ValueError:
            words = part.lstrip("({ ").split()
            issues.append("unbalanced quote")
        if grouped and words:
            words[-1] = words[-1].rstrip(")")
        before = list(words)
        words, via_xargs = strip_prefix(words)
        if not words:
            continue
        head = words[0]
        if DYNAMIC_RE.search(head):
            issues.append("a command name that is built at run time")
            continue
        if head in SHELLS:
            flag = next((i for i, w in enumerate(words[1:], 1)
                         if re.match(r"^-[A-Za-z]*c[A-Za-z]*$", w)), None)
            if flag is not None and flag + 1 < len(words):
                out.extend(segment_entries(words[flag + 1], issues, depth + 1))
                continue
        if runs_inline_code(head, words):
            issues.append("an interpreter running inline code")
        if head == "eval":
            out.extend(segment_entries(" ".join(words[1:]), issues, depth + 1))
            continue
        tokens = strip_prefix_tokens(limits.segment_tokens(part.lstrip("({ "))) if limits else []
        out.append({"words": words, "before": before, "tokens": tokens, "xargs": via_xargs})
    return out


def with_dirs(command, cwd, issues=None):
    """Pair each segment with the directory it acts in, following cd and git -C."""
    return [(e["line"], e["where"]) for e in with_dirs_full(command, cwd, issues)]


def with_dirs_full(command, cwd, issues=None):
    """Each segment with the directory it acts in, following cd and git -C: {line, where,
    words, before, tokens, xargs} (the first two are what with_dirs returns)."""
    issues = [] if issues is None else issues
    here = cwd or os.getcwd()
    pairs = []
    for entry in segment_entries(command, issues):
        words, piped = entry["words"], entry["xargs"]
        if words[0] in ("cd", "pushd") and len(words) > 1:
            here = os.path.normpath(os.path.join(here, os.path.expanduser(words[1])))
            continue
        where = here
        as_run = list(words)
        if words[0] == "git":
            rest, i = [], 1
            while i < len(words):
                w = words[i]
                if w in GIT_GLOBAL_WITH_ARG and i + 1 < len(words):
                    if w == "-C":
                        where = os.path.normpath(os.path.join(where, os.path.expanduser(words[i + 1])))
                    i += 2
                elif w in GIT_GLOBAL_FLAGS or re.match(r"^--(git-dir|work-tree|namespace|exec-path)=", w):
                    i += 1
                else:
                    rest = words[i:]
                    break
            words = ["git"] + rest
        if piped and VERB_RE.match(words[0]) and not (
            words[0] == "rm" and not any(w.startswith("-") for w in words[1:])
        ):
            issues.append("arguments that arrive on stdin")
        pairs.append({"line": " ".join(words), "where": where, "words": words, "as_run": as_run,
                      "before": entry["before"], "tokens": entry["tokens"], "xargs": piped})
    return pairs


# less, more and rg are left out on purpose: they can run other programs.
READ_ONLY = {"cat", "ls", "head", "tail", "grep", "egrep", "stat", "wc",
             "file", "diff", "test", "[", "echo", "pwd", "true", "cd", "pushd"}
RUNS_PROGRAMS = re.compile(r"^-(-pre|-exec|exec|execdir|ok|okdir|delete)(=|$)")
ANNSA_DIR_RE = re.compile(r"(^|[/\s\"'=~])\.annsa(?![\w.-])")


def writes_annsa_dir(command, cwd):
    """True when the command could change anything in ~/.annsa (the token, the cache, the
    queue): it names that folder and is not a plain read."""
    if not ANNSA_DIR_RE.search(command):
        return False
    if ">" in command:
        return True
    issues = []
    for line, _ in with_dirs(command, cwd, issues):
        if line.split(" ", 1)[0] not in READ_ONLY:
            return True
        if any(RUNS_PROGRAMS.match(w) for w in line.split(" ")[1:]):
            return True
    return bool(issues)


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
    """(principle, kind, line, where) for the first segment an enforced principle refuses.
    When a part of the command can't be followed and it names an enforced verb, that is
    refused too (the only place this hook fails closed)."""
    kinds = data.get("kinds") or {}
    issues = []
    pairs = with_dirs(command, cwd, issues)
    for line, where in pairs:
        for p in data.get("principles") or []:
            kind = kinds.get(p.get("kind"))
            if not kind:
                continue
            if any(matches(r, line, where) for r in kind.get("allow", [])):
                continue
            if any(matches(r, line, where) for r in kind.get("refuse", [])):
                return p, kind, line, where
    principles = data.get("principles") or []
    if issues and principles and VERB_RE.search(command):
        why = {"what": "a command Annsa can't read (%s)" % issues[0]}
        return principles[0], why, command[:200], os.getcwd() if not cwd else cwd
    return None


# ---------- a workspace's own limits (GET /mcp/enforce `limits`, 1.2.0) ----------

CUSTOM_KIND_RE = re.compile(r"^custom:[0-9a-f]{12}$")
LITERAL_RUN_RE = re.compile(r"[^*?/\s]{2,}")
HOOK_WRITERS = {"rm", "mv", "cp", "tee", "touch", "chmod", "chown", "truncate", "install", "ln",
                "unlink", "rsync", "dd", "mkdir", "sed", "perl", "git"}


def usable_limits(data):
    """The limits this hook enforces: switched on, type command or path, a grammar it reads.
    An import limit is a lint rule for the agent, never the shell hook. A reply with no
    `limits` (an older server) gives none, and the hook behaves as 1.1.0 did."""
    out = []
    listed = data.get("limits") if limits else None
    if not isinstance(listed, list):
        return out
    for item in listed:
        if not isinstance(item, dict) or item.get("state") != "on":
            continue
        kind_of, pattern, key = item.get("type"), item.get("pattern"), item.get("key")
        if kind_of not in ("command", "path") or not isinstance(pattern, str):
            continue
        grammar = limits.COMMAND_GRAMMAR if kind_of == "command" else limits.PATH_GRAMMAR
        if item.get("match") not in (None, grammar):
            continue  # a grammar this hook doesn't know: it can't be read
        pattern = " ".join(pattern.split()) if kind_of == "command" else pattern.strip()
        if not pattern or len(pattern) > limits.MAX_PATTERN or len(pattern.split()) > limits.MAX_WORDS:
            continue
        if sum(c not in "*?/ " for c in pattern) < 2:
            continue  # nothing named: it would match everything
        kind = item.get("kind")
        if not (isinstance(kind, str) and CUSTOM_KIND_RE.match(kind)):
            kind = "custom:" + key if isinstance(key, str) and re.fullmatch(r"[0-9a-f]{12}", key) else None
        if not kind:
            continue
        reason = " ".join(str(item.get("reason") or "").split())[:200]
        out.append({"type": kind_of, "pattern": pattern, "kind": kind, "reason": reason,
                    "principle_id": item.get("principle_id"), "number": item.get("number"),
                    "title": item.get("title") or "your principle"})
    return out


def limit_what(limit, why=None):
    return {"what": why or "a limit your workspace set (%s)" % limit["reason"]}


def limit_could_apply(limit, command):
    """For a command the parser can't fully read: does it name something the limit names?"""
    text = command.lower()
    return any(run.lower() in text for run in LITERAL_RUN_RE.findall(limit["pattern"]))


def limit_hit(command, cwd, data):
    """(principle, kind, line, where, limit) for the first segment a switched-on command or
    path limit refuses, or None. Fails closed: a segment it can't read that a limit could
    apply to is refused, and so is an error inside the check."""
    active = usable_limits(data)
    if not active:
        return None
    here = os.getcwd() if not cwd else cwd
    try:
        issues = []
        for e in with_dirs_full(command, cwd, issues):
            for limit in active:
                if limit["type"] == "command":
                    tries = (e["before"], e["as_run"], e["words"])
                    hit = any(limits.command_matches(limit["pattern"], w) for w in tries if w)
                else:
                    if e["xargs"] and e["words"][0] in HOOK_WRITERS:
                        hit = limit_could_apply(limit, command)  # its operands arrive on stdin
                    else:
                        hit = limits.command_touches_path(limit["pattern"], e["tokens"], cwd=e["where"])
                if hit:
                    return _limit_result(limit, e["line"], e["where"])
        if issues:
            for limit in active:
                if limit_could_apply(limit, command):
                    why = "a command Annsa can't read (%s), under a limit your workspace set (%s)" % (
                        issues[0], limit["reason"])
                    return _limit_result(limit, command[:200], here, why)
    except Exception:  # a limit never fails open
        limit = active[0]
        return _limit_result(limit, command[:200], here, "a command Annsa couldn't check against your limits", post=False)
    return None


def _limit_result(limit, line, where, why=None, post=True):
    principle = {"principle_id": limit["principle_id"], "number": limit["number"],
                 "title": limit["title"], "kind": limit["kind"]}
    return principle, limit_what(limit, why), line, where, post


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
    import urllib.request

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
    if writes_annsa_dir(command, event.get("cwd")):
        deny({"title": "Annsa's own files"}, {"what": "a change to ~/.annsa"}, command[:200])
        return
    data = enforce_list(cfg)
    if data is None:
        once(session_id, "offline", "Annsa can't be reached, so your principles aren't enforced in this session.")
        return
    post = True
    hit = first_block(command, event.get("cwd"), data) if data.get("principles") else None
    if not hit:
        hit = limit_hit(command, event.get("cwd"), data)
        if hit:
            hit, post = hit[:4], hit[4]
    if not hit:
        return
    principle, kind, line, where = hit
    deny(principle, kind, line)
    if post and not os.environ.get("ANNSA_ENFORCE_NO_POST"):
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
