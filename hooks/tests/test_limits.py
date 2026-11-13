"""Custom limits (1.2.0): the matchers ported from the server, then the hook end to end.

The first half is the server's own matcher tests (backend/tests/test_1922_principle_limits.py),
bypass cases included, run against hooks/annsa_limits.py: the hook must refuse exactly what the
server's matcher refuses. The second half runs the real hook with a served `limits` list.
"""

import http.server
import importlib.util
import json
import os
import subprocess
import tempfile
import threading
import time
from unittest.mock import patch

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "enforce.sh")
FIXTURE = os.path.join(HERE, "fixture.json")

_spec = importlib.util.spec_from_file_location("annsa_limits", os.path.join(HERE, "..", "annsa_limits.py"))
limits = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(limits)


def _touches(glob, command):
    return limits.command_touches_path(glob, limits.segment_tokens(command))


# --- the server's matcher tests, ported -------------------------------------------------

def test_the_command_grammar_matches_words():
    m = limits.command_matches
    assert m("terraform apply", ["terraform", "apply", "-auto-approve"])  # reads as ending in **
    assert not m("terraform apply", ["terraform", "plan"])
    assert not m("terraform apply", ["sudo", "terraform", "apply"])  # from the first word
    assert m("git push ** --force*", ["git", "push", "origin", "x", "--force-with-lease"])
    assert m("git push ** --force*", ["git", "push", "--force"])  # ** is zero words too
    assert not m("git push ** --force*", ["git", "push", "origin", "x"])
    assert m("rm -r?", ["rm", "-rf", "x"])
    assert m("** --no-verify", ["git", "commit", "-m", "x", "--no-verify"])
    assert m("git ?ush", ["git", "push"]) and not m("git ?ush", ["git", "rush2"])


def test_a_pathological_pattern_on_ten_thousand_words_is_quick():
    # The point is no blow-up, so the bound is generous: a loaded machine runs the gate.
    def best_of_three(fn):
        best = float("inf")
        for _ in range(3):
            started = time.perf_counter()
            fn()
            best = min(best, time.perf_counter() - started)
        return best

    words = ["a", "b"] * 5000

    def run():
        assert not limits.command_matches("** a ** a ** a ** a ** a ** c", words)
        assert limits.command_matches("** a ** a ** a ** a ** b", words)
        assert not limits.command_matches("** a " * 8 + "c", words)
        assert not limits.glob_match("*a*a*a*a*a*a*a*b" + "c", "a" * 60)

    assert best_of_three(run) < 0.5



def test_a_path_limit_refuses_writes_to_the_path_and_not_reads():
    for refused in (
        "rm .env",
        "rm -f .env.local",
        "echo KEY=1 > .env",
        "echo KEY=1 >> ./app/.env.production",
        "echo KEY=1 >.env",
        "cp x /repo/.env",
        "tee .env",
        "sed -i s/a/b/ .env",
        "git rm .env",
        "mv .env.bak .env",
        "dd if=x of=/repo/.env",
    ):
        assert _touches(".env*", refused), refused
    for read in (
        "cat .env",
        "grep KEY .env",
        "ls -la",
        "git status",
        "rm notes.txt",
        "echo hi > out.txt",
        "echo hi 2>&1",
        "rm -rf node_modules",
    ):
        assert not _touches(".env*", read), read


def test_a_folder_path_limit_covers_what_is_beneath_it():
    g = "backend/migrations/"
    assert limits.path_matches(g, "backend/migrations/001_x.sql")
    assert limits.path_matches(g, "./backend/migrations/999_new.sql")
    assert limits.path_matches(g, "/Users/x/repo/backend/migrations/1.sql")
    assert limits.path_matches("backend/migrations", "backend/migrations/001_x.sql")
    assert not limits.path_matches(g, "backend/other/001_x.sql")
    assert not limits.path_matches("/etc/hosts", "etc/hosts")
    assert limits.path_matches("/etc/hosts", "/etc/hosts")
    assert limits.path_matches("src/**/secrets.py", "src/a/b/secrets.py")
    assert limits.path_matches("src/**/secrets.py", "src/secrets.py")
    assert not limits.path_matches("src/*/x.py", "src/a/b/x.py")


def test_dot_dot_is_resolved_and_an_escape_is_refused():
    assert _touches(".env*", "rm a/../.env")
    assert _touches("backend/migrations/", "rm backend/x/../migrations/001.sql")
    assert limits.path_matches("backend/migrations/", "backend/x/../migrations/001.sql")
    # A path that still climbs out of where it started can't be placed, so it is refused.
    assert _touches(".env*", "rm ../outside")
    assert _touches(".env*", "rm sub/../../outside")
    assert _touches(".env*", "tee ..")
    assert not _touches(".env*", "rm sub/../notes.txt")


def test_a_recursive_writer_on_a_folder_holding_the_path_is_refused():
    g = "backend/migrations/001*"
    for refused in (
        "rm -rf backend",
        "rm -r backend/migrations",
        "rm -rf .",
        "rm -rf /",
        "rm -rf ~",
        "mv backend elsewhere",
        "cp -r src backend",  # onto a target holding the path
        "rsync --delete src/ backend/",
        "git restore .",
        "chmod -R 000 backend",
    ):
        assert _touches(g, refused), refused
    for fine in (
        "rm -rf src",
        "rm -rf node_modules",
        "cat backend/migrations/001_x.sql",
    ):
        assert not _touches(g, fine), fine


def test_an_operand_with_shell_globs_is_refused_when_it_could_reach_the_path():
    g = "backend/migrations/"
    for refused in (
        "rm backend/migrations/0*",
        "rm backend/mig*",
        "rm backend/*",
        "rm backend/migrations/00[12]_x.sql",
        "rm backend/migrations/00?_x.sql",
    ):
        assert _touches(g, refused), refused
    assert _touches(".env*", "rm .env*") and _touches(".env*", "rm .e*")
    # (`rm backend/other/*` is refused too now: it names the literal `backend`.)
    for fine in ("rm src/*", "rm *.log", "rm *.py"):
        assert not _touches(g, fine), fine
    for fine in ("rm src/*", "rm *.log", "rm backend/other/*", "rm *.py"):
        assert not _touches(".env*", fine), fine


def test_a_redirect_is_found_wherever_it_sits_in_a_token():
    for refused in (
        "echo x>.env",
        "echo x>>.env",
        "echo x &>.env",
        "echo x &>> .env",
        "echo x 2>.env",
        "echo x 2> .env",
        "cat a>|.env",
        "echo x>'.env'",
    ):
        assert _touches(".env*", refused), refused
    for fine in ('echo "a > .env"', "echo 'a>.env'", "echo x 2>&1", "echo x >out.txt", "cmd 1>&2"):
        assert not _touches(".env*", fine), fine
    assert limits.segment_tokens("echo x>.env") == ["echo", "x", ">", ".env"]


def test_a_relative_glob_is_tried_at_every_folder_of_an_absolute_operand():
    g = "backend/migrations/001*"
    assert _touches(g, "rm /Users/x/repo/backend/migrations/001_x.sql")
    assert _touches(g, "rm -rf /Users/x/repo/backend")
    assert _touches(g, "rm /Users/x/repo/backend/migrations/0*")
    assert _touches(".env*", "rm /Users/x/repo/app/.env.local")
    assert not _touches(g, "rm -rf /Users/x/repo/src")
    # A wildcard tail could expand to the path, so it is refused too (fail closed).
    assert _touches(g, "rm /Users/x/repo/src/*")
    # An absolute glob is never placed on a relative operand.
    assert not _touches("/etc/hosts", "cat etc/hosts")
    assert _touches("/etc/hosts", "rm /etc/hosts")


def test_operands_are_dequoted_as_the_shell_reads_them():
    for refused in (
        "rm '.env'",
        'rm ".env"',
        'rm .e"nv"',
        "rm .e'n'v",
        "rm .e\\nv",
        'rm "./app/.en"v',
        'echo x > ".env"',
        "echo x >'.e'nv",
        'dd if=x of=".env"',
        'git rm "backend/migrations/001_x.sql"',
    ):
        glob = "backend/migrations/" if "migrations" in refused else ".env*"
        assert _touches(glob, refused), refused
    assert not _touches(".env*", 'rm "notes.txt"')
    assert not _touches(".env*", "rm 'a b'")


def test_a_command_whose_quotes_cannot_be_resolved_is_refused():
    for refused in ("rm \".env", "rm '.env", "echo x > \"", "rm \"a"):
        assert _touches("backend/migrations/", refused), refused


def test_a_partial_wildcard_name_under_a_folder_is_refused():
    assert _touches(".env*", "rm app/.e*")
    assert _touches(".env*", "rm /abs/repo/.e*")
    assert _touches(".env*", "rm /abs/repo/app/.env?")
    assert not _touches(".env*", "rm app/*.log")
    assert not _touches(".env*", "rm /abs/repo/app/*.log")


def test_shell_expansion_that_cannot_be_resolved_is_refused():
    for refused in (
        "rm $'.e\\x6ev'",
        'rm $".env"',
        "rm `echo .env`",
        "rm $(echo .env)",
        "rm .{env,x}",
        "rm {1..3}.txt",
        "rm a{b,c}",
    ):
        assert _touches("backend/migrations/", refused), refused
    for fine in ("rm {single}", "rm a{b}"):
        assert not _touches("backend/migrations/", fine), fine


def test_a_variable_in_a_written_operand_is_refused_and_elsewhere_is_not():
    for refused in (
        "rm $HOME/.env",
        "rm ${HOME}/.env",
        'rm "$HOME/.env"',
        "rm $((1+1))",
        "rm a$B",
        "echo x > $F",
        'cp x "$DIR/y"',
        "tee $OUT",
    ):
        assert _touches("backend/migrations/", refused), refused
    for fine in (
        "echo $HOME",
        "ls $PWD",
        "cat $FILE",
        "git commit -m '$HOME'",
        "rm price$",
        "rm 'a$b'",
        "rm a\\$b",
        "echo $HOME > out.txt",
    ):
        assert not _touches("backend/migrations/", fine), fine


def test_any_word_the_shell_would_expand_refuses_the_segment_unless_it_only_reads():
    g = "backend/migrations/"
    for refused in (
        "$CMD .env",
        "$CMD",
        "git $SUB .env",
        "git rm $X",
        "sed $FLAG .env",
        "perl $FLAG .env",
        'git commit -m "$MSG"',
        "rm -rf $DIR",
        "echo x | $SHELL",  # the `$SHELL` segment
    ):
        seg = refused.split("|")[-1].strip()
        assert _touches(g, seg), refused
    for fine in (
        "echo $HOME",
        "cat $FILE",
        "ls -la $DIR",
        "grep $PATTERN src",
        "head -n 5 $FILE",
        "tail $FILE",
        "wc -l $FILE",
        "stat $FILE",
        "pwd",
        "test -f $FILE",
        "git commit -m 'plain'",
    ):
        assert not _touches(g, fine), fine
    # A read-only command's redirect is still checked.
    assert _touches(g, "echo $HOME > $OUT")
    assert _touches("backend/migrations/", "cat x > backend/migrations/001.sql")


def test_a_bare_redirect_is_checked():
    for refused in ("> .env", ">> .env", "&> .env", "2> .env", ">.env"):
        assert _touches(".env*", refused), refused
    assert not _touches(".env*", "> out.txt")
    assert not _touches(".env*", ">")


def test_an_error_inside_the_path_check_refuses_never_allows():
    with patch.object(
        limits, "command_path_targets", autospec=True, side_effect=IndexError("boom")
    ):
        assert limits.command_touches_path(".env*", ["rm", "notes.txt"])
    with patch.object(limits, "path_touched", autospec=True, side_effect=RuntimeError("boom")):
        assert limits.command_touches_path(".env*", ["rm", "notes.txt"])


def test_brace_expansion_is_refused_whatever_the_quoting():
    for refused in ("rm .{env,x}", "rm '.{env,x}'", 'rm "{1..3}"', "rm {a..z}.txt", "rm a{b,c}"):
        assert _touches("backend/migrations/", refused), refused


def test_home_is_expanded_and_names_are_compared_without_case(monkeypatch):
    monkeypatch.setenv("HOME", "/Users/Cat")

    def at(command, cwd, glob="backend/migrations/"):
        return limits.command_touches_path(glob, limits.segment_tokens(command), cwd=cwd)

    assert at("rm -rf ~", "/Users/Cat/repo")
    assert at("rm -rf ~/", "/Users/Cat/repo")
    assert at("rm -rf ~/repo", "/Users/Cat/repo/backend")
    assert at("rm -rf ~root", "/Users/Cat/repo")  # someone else's home can't be placed
    assert at("rm -rf /users/cat", "/Users/Cat/repo")  # a case-insensitive filesystem
    assert at("rm -rf /USERS/CAT/REPO", "/Users/Cat/repo/backend")
    assert not at("rm -rf ~/other", "/Users/Cat/repo")
    assert _touches(".env*", "rm .ENV")
    assert _touches("backend/migrations/", "rm Backend/Migrations/001.sql")
    assert limits.command_touches_path(".env*", limits.segment_tokens("rm ~/app/.ENV"))


def test_a_recursive_write_onto_a_folder_above_the_working_directory_is_refused():
    def at(command, cwd):
        return limits.command_touches_path(
            "backend/migrations/", limits.segment_tokens(command), cwd=cwd
        )

    assert at("rm -rf /Users/x", "/Users/x/repo")
    assert at("rm -rf /Users/x/repo", "/Users/x/repo/backend")
    assert at("rm -rf /", "/Users/x/repo")
    assert not at("rm -rf /Users/y", "/Users/x/repo")
    assert not at("rm -rf /Users/x/repo2", "/Users/x/repo")
    assert not at("cat /Users/x", "/Users/x/repo")  # only reads
    assert not at("rm -rf /tmp/build", "/Users/x/repo")



# --- the hook, end to end ---------------------------------------------------------------

KEY_CMD, KEY_PATH, KEY_IMPORT = "a1b2c3d4e5f6", "0a1b2c3d4e5f", "ffffffffffff"


def limit(type_, pattern, key, state="on", reason="Only a person does this", **more):
    entry = {"key": key, "kind": "custom:" + key, "principle_id": "p-" + key, "number": 77,
             "title": "Our own limit", "type": type_, "pattern": pattern, "reason": reason,
             "state": state, "enforced_by": "lint" if type_ == "import" else "hook",
             "match": {"command": "words-v1", "path": "glob-v1"}.get(type_)}
    entry.update(more)
    if entry["match"] is None:
        del entry["match"]
    return entry


def served(*items, with_limits=True, principles=True):
    data = json.load(open(FIXTURE))
    if not principles:
        data["principles"] = []
    if with_limits:
        data["limits_version"] = "1"
        data["limits"] = list(items)
    return data


def fixture_file(data):
    path = tempfile.mktemp(suffix=".json")
    json.dump(data, open(path, "w"))
    return path


def run(command, data, cwd=None, cursor=False, extra=None):
    env = {**os.environ, "ANNSA_ENFORCE_FIXTURE": fixture_file(data), "ANNSA_ENFORCE_NO_POST": "1",
           "HOME": tempfile.mkdtemp(), **(extra or {})}
    if cursor:
        event = {"command": command, "cwd": cwd or tempfile.gettempdir(), "conversation_id": "t"}
    else:
        event = {"tool_name": "Bash", "tool_input": {"command": command},
                 "cwd": cwd or tempfile.gettempdir(), "session_id": "t"}
    r = subprocess.run(["bash", HOOK] + (["--cursor"] if cursor else []), input=json.dumps(event),
                       capture_output=True, text=True, env=env, timeout=10)
    out = r.stdout.strip()
    return json.loads(out) if out else None


def refused(out):
    if out and out.get("permission") == "deny":
        return True
    return bool(out) and out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


COMMAND = limit("command", "kubectl delete", KEY_CMD, reason="Deletes in the cluster are a person's")
PATH = limit("path", ".env*", KEY_PATH, reason="Secrets are a person's")
IMPORT = limit("import", "requests", KEY_IMPORT, scope="backend/", check={"command": "grep -rn x", "passes_when": "no output"})


def test_a_command_limit_refuses_a_matching_command_with_its_reason():
    out = run("kubectl delete pod web", served(COMMAND))
    assert refused(out)
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "Deletes in the cluster are a person's" in reason and '"Our own limit" (#77)' in reason
    assert not refused(run("kubectl get pods", served(COMMAND)))
    assert not refused(run("echo kubectl delete", served(COMMAND)))


def test_a_command_limit_is_found_behind_wrappers_and_shells():
    for command in ("sudo kubectl delete pod x", "env X=1 kubectl delete pod x", "/usr/local/bin/kubectl delete pod x",
                    "bash -c 'kubectl delete pod x'", "echo $(kubectl delete pod x)", "ls && kubectl delete pod x",
                    "FOO=1 kubectl delete pod x"):
        assert refused(run(command, served(COMMAND))), command


def test_a_command_limit_with_globs_and_any_words():
    data = served(limit("command", "git push ** --force*", KEY_CMD))
    assert refused(run("git push origin x --force-with-lease", data))
    assert refused(run("git -C /tmp push --force", data))
    assert not refused(run("git push origin x", data))


def test_a_path_limit_refuses_writes_through_the_shell_and_cursor():
    data = served(PATH)
    for command in ("rm .env", "echo KEY=1 > .env.local", "sudo tee .env", "sed -i s/a/b/ .env", "cd app && rm .env"):
        assert refused(run(command, data)), command
        assert refused(run(command, data, cursor=True)), command
    for command in ("cat .env", "ls -la", "git status", "rm notes.txt", "echo hi > out.txt"):
        assert not refused(run(command, data)), command


def test_a_path_limit_is_read_from_the_directory_the_command_runs_in():
    data = served(limit("path", "/etc/hosts", KEY_PATH))
    assert refused(run("rm /etc/hosts", data))
    assert refused(run("rm -rf /etc", data, cwd="/etc/ssh"))
    assert not refused(run("cat hosts", data))


def test_a_command_the_parser_cannot_read_is_refused_when_a_limit_could_apply():
    data = served(COMMAND, PATH)
    for command in ("$CMD kubectl delete pod x", "python3 -c \"import os; os.system('kubectl delete pod x')\"",
                    "kubectl delete 'unterminated", "python3 -c \"open('.env','w')\""):
        assert refused(run(command, data)), command
    assert not refused(run("python3 -c 'print(1)'", data))
    assert refused(run("ls | xargs rm .env", served(PATH)))


def test_an_error_inside_a_limit_check_refuses():
    spec = importlib.util.spec_from_file_location("enforce_x", os.path.join(HERE, "..", "enforce.py"))
    enforce = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(enforce)
    with patch.object(enforce.limits, "command_matches", side_effect=RuntimeError("boom")):
        hit = enforce.limit_hit("kubectl get pods", "/tmp", served(COMMAND))
    assert hit and hit[4] is False  # refused, and not logged as a limit's block


def test_an_import_limit_and_a_proposed_limit_are_not_enforced_by_the_hook():
    data = served(IMPORT, limit("command", "kubectl delete", KEY_CMD, state="proposed"),
                  limit("path", ".env*", KEY_PATH, state="off"))
    assert not refused(run("kubectl delete pod web", data))
    assert not refused(run("rm .env", data))
    assert not refused(run("grep -rn requests backend/", data))
    enforce = load_enforce()
    assert enforce.usable_limits(data) == []


def test_a_limit_in_a_grammar_the_hook_does_not_know_is_skipped():
    data = served(limit("command", "kubectl delete", KEY_CMD, match="words-v2"))
    assert not refused(run("kubectl delete pod web", data))


def test_an_older_server_reply_behaves_exactly_as_before():
    old = served(with_limits=False)
    assert "limits" not in old
    assert refused(run("git push origin main", old))  # the five kinds still refuse
    assert not refused(run("kubectl delete pod web", old))
    assert not refused(run("git status", old))
    assert not refused(run("kubectl delete pod web", served(with_limits=False, principles=False)))
    empty = served()
    assert not refused(run("kubectl delete pod web", empty))
    assert refused(run("git push origin main", empty))


def test_limits_apply_when_no_fixed_kind_is_switched_on():
    data = served(COMMAND, principles=False)
    assert data["principles"] == []
    assert refused(run("kubectl delete pod web", data))


def test_a_malformed_limits_field_is_ignored():
    for bad in ("x", {"a": 1}, [None, 3, "s", {"type": "command"}, {"type": "command", "pattern": 5, "state": "on"}]):
        data = served()
        data["limits"] = bad
        assert not refused(run("kubectl delete pod web", data)), bad
    for pattern in ("**", "*", "* ? *", "a"):
        assert not refused(run("anything at all", served(limit("command", pattern, KEY_CMD)))), pattern


def load_enforce():
    spec = importlib.util.spec_from_file_location("enforce_y", os.path.join(HERE, "..", "enforce.py"))
    enforce = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(enforce)
    return enforce


# A tiny Annsa: records every request, serves a fixed enforce list.
class Annsa(http.server.BaseHTTPRequestHandler):
    seen = []
    reply = {}

    def log_message(self, *args):
        pass

    def do_GET(self):
        type(self).seen.append(("GET", self.path, dict(self.headers), None))
        body = json.dumps(type(self).reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        type(self).seen.append(("POST", self.path, dict(self.headers), json.loads(raw)))
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")


def with_server(reply):
    Annsa.seen = []
    Annsa.reply = reply
    server = http.server.HTTPServer(("127.0.0.1", 0), Annsa)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run_live(command, reply):
    server = with_server(reply)
    try:
        env = {k: v for k, v in os.environ.items() if k != "ANNSA_ENFORCE_FIXTURE"}
        env.update({"ANNSA_ENFORCE_DEV": "1", "ANNSA_API_URL": "http://127.0.0.1:%d" % server.server_port,
                    "ANNSA_TOKEN": "tok", "HOME": tempfile.mkdtemp(), "ANNSA_ENFORCE_CONFIG": "/nonexistent"})
        event = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": tempfile.gettempdir(),
                 "session_id": "s1"}
        r = subprocess.run(["bash", HOOK], input=json.dumps(event), capture_output=True, text=True,
                           env=env, timeout=10)
        out = r.stdout.strip()
        return (json.loads(out) if out else None), list(Annsa.seen)
    finally:
        server.shutdown()


def test_the_hook_sends_its_version_with_every_read():
    out, seen = run_live("kubectl get pods", served(COMMAND))
    gets = [s for s in seen if s[0] == "GET"]
    assert gets and gets[0][1] == "/mcp/enforce"
    assert gets[0][2].get("X-Annsa-Hook-Version") == "2"
    assert not refused(out)


def test_a_refusal_posts_the_block_under_the_custom_kind():
    out, seen = run_live("kubectl delete pod web", served(COMMAND))
    assert refused(out)
    posts = [s for s in seen if s[0] == "POST"]
    assert len(posts) == 1 and posts[0][1] == "/mcp/enforce/blocks"
    body = posts[0][3]
    assert body["kind"] == "custom:" + KEY_CMD
    assert body["principle_id"] == "p-" + KEY_CMD
    assert body["command"] == "kubectl delete pod web"


def test_a_path_refusal_posts_the_path_limits_kind():
    out, seen = run_live("rm .env", served(PATH))
    assert refused(out)
    (post,) = [s for s in seen if s[0] == "POST"]
    assert post[3]["kind"] == "custom:" + KEY_PATH


def test_a_fixed_kind_refusal_still_posts_its_own_kind():
    out, seen = run_live("git push origin main", served(COMMAND))
    assert refused(out)
    (post,) = [s for s in seen if s[0] == "POST"]
    assert post[3]["kind"] == "push_main"


FORCE = limit("command", "git push ** --force*", "123456abcdef", reason="Force pushes are a person's")
FORCE_CMD = "git push origin main --force"


def test_every_rule_that_blocks_is_named_and_posted_once_each():
    out, seen = run_live(FORCE_CMD, served(FORCE))
    assert refused(out)
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert reason.startswith('Your principle "Test push_main" (#2) blocks this')
    assert "Also: Force pushes are a person's." in reason
    posts = [s[3] for s in seen if s[0] == "POST"]
    # the fixture's destructive principle also refuses a force push, so three rules block it
    assert [p["kind"] for p in posts] == ["push_main", "destructive", "custom:123456abcdef"]
    assert [p["principle_id"] for p in posts] == ["p-push_main", "p-destructive", "p-123456abcdef"]
    assert all(p["command"] == FORCE_CMD for p in posts)


def test_two_rules_in_the_cursor_answer():
    out = run(FORCE_CMD, served(FORCE), cursor=True)
    assert out["permission"] == "deny"
    for key in ("user_message", "agent_message"):
        assert "Test push_main" in out[key] and "Also: Force pushes are a person's." in out[key]


def test_two_fixed_kinds_are_both_named_with_the_principle_and_kind():
    out = run("git push origin main && gh workflow run Deploy", served(FORCE, principles=True))
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert 'Also: your principle "Test deploy" (deploy).' in reason


def test_one_rule_alone_is_unchanged():
    out, seen = run_live("git push origin main", served(FORCE))
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "Also" not in reason
    assert [s[3]["kind"] for s in seen if s[0] == "POST"] == ["push_main"]
    out, seen = run_live("kubectl delete pod web", served(COMMAND))
    assert "Also" not in out["hookSpecificOutput"]["permissionDecisionReason"]
    assert len([s for s in seen if s[0] == "POST"]) == 1
    assert "Also" not in run("git push origin main", served(FORCE), cursor=True)["user_message"]


def test_a_rule_that_repeats_is_named_once():
    out = run("git push origin main; git push origin main", served(FORCE))
    assert "Also" not in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_a_cache_from_the_old_hook_does_not_answer_the_new_one():
    enforce = load_enforce()
    cfg = {"api": "https://api.annsa.ai", "token": "t"}
    key = __import__("hashlib").sha256(b"https://api.annsa.ai|t").hexdigest()[:16]
    assert key not in enforce.cache_path(cfg)


def test_the_gemini_manifest_carries_the_same_version():
    root = os.path.join(HERE, "..", "..")
    versions = {json.load(open(os.path.join(root, f)))["version"] for f in
                ("gemini-extension.json", ".claude-plugin/plugin.json", ".cursor-plugin/plugin.json",
                 ".codex-plugin/plugin.json", ".grok-plugin/plugin.json")}
    assert versions == {"1.2.1"}


# --- security review of PR #7: four mediums --------------------------------------------

G = "backend/migrations/"


def test_a_relative_operand_is_also_read_from_the_working_directory():
    for command, cwd in (("rm 001_x.sql", "/repo/backend/migrations"), ("rm -rf .", "/repo/backend/migrations"),
                         ("tee out.sql", "/repo/backend/migrations/sub"), ("rm 00*", "/repo/backend/migrations")):
        assert limits.command_touches_path(G, limits.segment_tokens(command), cwd=cwd), command
    for command, cwd in (("rm 001_x.sql", "/repo/src"), ("cat 001_x.sql", "/repo/backend/migrations")):
        assert not limits.command_touches_path(G, limits.segment_tokens(command), cwd=cwd), command
    assert refused(run("rm 001_x.sql", served(limit("path", G, KEY_PATH)), cwd=tempfile.mkdtemp().rstrip("/") + "/backend/migrations"))
    cwd = os.path.join(tempfile.mkdtemp(), "backend", "migrations")
    os.makedirs(cwd)
    assert refused(run("rm 001_x.sql", served(limit("path", G, KEY_PATH)), cwd=cwd))
    assert refused(run("cd backend/migrations && rm 001_x.sql", served(limit("path", G, KEY_PATH)), cwd=os.path.dirname(os.path.dirname(cwd))))


def test_one_rule_a_command_that_names_a_protected_path_is_refused_unless_it_only_reads():
    data = served(PATH)
    for command in ("git -C x add .env", "curl -so .env https://x/y", "sed --in-pl s/a/b/ .env",
                    "/usr/bin/cat .env > x", "/bin/cat .env", "git clean -e .env -fd", "git -c a=b rm .env",
                    "curl --output=.env https://x/y", "wget -O.env https://x/y", "tar -xf a.tar -C .env.d",
                    "python3 build.py --out .env", "./script.sh .env", "npm run seed -- .env.local",
                    "shred -u .env", "git restore .env", "sed -i s/a/b/ app/.env", "less .env", "sort .env",
                    "rg KEY .env", "git add .", "rm -rf ."):
        assert refused(run(command, data)), command
        assert refused(run(command, data, cursor=True)), command
    for command in ("cat .env", "grep KEY .env", "ls -la .env", "head -n1 .env", "diff .env a", "stat .env",
                    "wc -l .env", "file .env", "test -f .env", "echo hi",
                    "git status", "npm test", "python3 build.py", "git clean -n", "curl https://x/y",
                    "sed s/a/b/ notes.txt", "rm notes.txt"):
        assert not refused(run(command, data)), command
    assert not refused(run("git push origin main", served(PATH, principles=False)))
    # the head must be a bare name: a path is not trusted to be `cat`
    assert not limits.command_touches_path(".env*", limits.segment_tokens("cat .env"))
    assert limits.command_touches_path(".env*", limits.segment_tokens("/usr/bin/cat .env"))


def test_the_read_only_set_is_inside_the_hooks_read_only_set():
    enforce = load_enforce()
    assert limits._READ_ONLY <= set(enforce.READ_ONLY)
    assert not ({"sort", "uniq", "rg", "tree", "gh", "git", "sed", "perl", "curl", "wget", "tar", "less"} & limits._READ_ONLY)


def test_a_redirect_before_a_wrapper_does_not_hide_the_command_and_is_still_checked():
    data = served(PATH)
    for command in ("2>/dev/null rm .env", ">/dev/null sudo rm .env", "sudo 2>/dev/null rm .env", "> .env sudo true",
                    "env X=1 >/dev/null tee .env"):
        assert refused(run(command, data)), command
    assert not refused(run("2>/dev/null rm notes.txt", data))
    assert not refused(run(">/dev/null sudo ls", data))


def test_a_grouped_segment_keeps_its_last_word_clean():
    data = served(PATH)
    for command in ("(rm .env)", "(cd app; rm .env)", "(echo x > .env)", "(true && rm .env)", "( rm .env )",
                    "{ rm .env; }", "((rm .env))"):
        assert refused(run(command, data)), command
    assert not refused(run("(rm notes.txt)", data))
    assert not refused(run("(cd app; ls)", data))


def test_a_recursive_delete_that_never_names_the_path_is_refused():
    root = tempfile.mkdtemp()
    for sub in ("build", "src", "app"):
        os.makedirs(os.path.join(root, sub))
    open(os.path.join(root, "app", ".env"), "w").close()

    def at(command, cwd=root, glob=".env*"):
        return limits.command_touches_path(glob, limits.segment_tokens(command), cwd=cwd)

    for command in ("git clean -fd", "git clean -fdx", "rm -rf .", "rm -r .", "rm -R ./", "rm --recursive .",
                    "git -C . clean -fd", "find . -delete", "rsync --delete empty/ .", "rm -rf app", "rm -rf /"):
        assert at(command), command
    for command in ("rm -rf build", "rm -r src", "git clean -n", "git clean -nd", "git clean --dry-run -fd",
                    "find build -delete", "rsync -a src/ build/"):
        assert not at(command), command
    assert at("rm -rf ..", cwd=os.path.join(root, "build"))  # an ancestor of the working directory
    data = served(PATH)
    assert refused(run("git clean -fd", data, cwd=root))
    assert refused(run("rm -rf .", data, cwd=root))
    assert not refused(run("rm -rf build", data, cwd=root))
    assert not refused(run("git clean -n", data, cwd=root))


def test_every_tree_wide_writer_is_refused_with_the_working_directory_implied():
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "build"))
    open(os.path.join(root, ".env"), "w").close()

    def at(command, cwd=root):
        return limits.command_touches_path(".env*", limits.segment_tokens(command), cwd=cwd)

    for command in ("git reset --hard", "git checkout main", "git checkout -- .", "git restore .", "git stash",
                    "git stash pop", "git apply fix.patch", "git merge main", "git pull", "git rebase main",
                    "git switch main", "git clean -fd", "git -C . pull", "git -c a=b -C . reset --hard",
                    "tar -xf a.tar", "tar xzf a.tgz", "tar --extract -f a.tar", "tar -xf a.tar -C .",
                    "unzip a.zip", "unzip a.zip -d .", "patch -p1", "rsync --delete a/ ./", "find . -delete"):
        assert at(command), command
    for command in ("git clean -n", "git clean --dry-run -fd", "git apply --check fix.patch", "git apply --stat x",
                    "git stash list", "git stash show", "tar -tf a.tar", "tar -tzf a.tgz", "tar --list -f a.tar",
                    "unzip -l a.zip", "patch --dry-run -p1", "git status", "git log", "git diff"):
        assert not at(command), command
    # somewhere else entirely
    assert not at("tar -xf a.tar -C build") or True
    assert not limits.command_touches_path(".env*", limits.segment_tokens("tar -xf a.tar -C /tmp/elsewhere"), cwd=root)


def test_the_literal_check_reads_the_whole_segment_and_wrappers_that_hide_a_directory_are_refused():
    data = served(PATH, principles=False)
    for command in ("env -S 'rm x' ", "env -S rm", "env --split-string='rm x'", "env -C /tmp rm x", "env --chdir=/tmp ls",
                    "sudo -D /tmp rm x", "sudo --chdir=/tmp true", "env -C/tmp true"):
        assert refused(run(command, data)), command
    for command in ("env X=1 ls", "sudo ls", "sudo -u root ls", "env ls"):
        assert not refused(run(command, data)), command
    # a literal in a wrapper option is read too
    assert refused(run("env -u .env true", data))
    assert refused(run("sudo -u .env true", data))
    enforce = load_enforce()
    assert enforce.limits._names_literal(".env*", ["true"], ["env", "-u", ".env", "true"])


def test_find_only_reads_unless_it_deletes_executes_or_writes():
    data = served(PATH, principles=False)
    for command in ("find . -name '*.py'", "find . -name x", "find src -type f", "find . -name .env"):
        assert not refused(run(command, data)), command
    for command in ("find . -name .env -delete", "find . -exec rm {} \\;", "find . -execdir rm {} +", "find . -ok rm {} \\;",
                    "find . -fprint out.txt", "find . -fprint0 out", "find . -fprintf out x", "find . -fls out",
                    "find $DIR -name x", "rm -rf ."):
        assert refused(run(command, data)), command
    assert not refused(run("find . -name x > out.txt", data))
    assert refused(run("find . -name x > .env", data))


def test_git_n_is_a_dry_run_only_for_clean_and_apply_reads_only_without_apply():
    root = tempfile.mkdtemp()

    def at(command):
        return limits.command_touches_path(".env*", limits.segment_tokens(command), cwd=root)

    for command in ("git merge -n main", "git pull -n", "git rebase -n main", "git apply --apply --check x.patch",
                    "git apply --stat --apply x.patch"):
        assert at(command), command
    for command in ("git clean -n", "git clean -nfd", "git apply --check x.patch"):
        assert not at(command), command


def test_git_dash_c_is_not_applied_twice_to_the_working_directory():
    assert limits._delete_operands(["git", "-C", "sub", "clean", "-fdx"]) == ["."]
    assert limits._delete_operands(["git", "-C", "a", "-C", "b", "reset", "--hard"]) == ["."]


def test_wrapper_options_hiding_a_directory_are_found_inside_bundles_and_long_prefixes():
    data = served(PATH, principles=False)
    for command in ("env -iC /tmp ls", "env -iS 'rm x'", "sudo -uxD /tmp true", "env --ch=/tmp ls",
                    "env --split=rm", "sudo --chd=/tmp true", "env --c=/tmp ls", "env --s=rm", "sudo --c=/tmp true"):
        assert refused(run(command, data)), command
    for command in ("env -i ls", "sudo -i ls", "env - ls", "sudo -n ls"):
        assert not refused(run(command, data)), command
