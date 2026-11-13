"""Custom limits: the matchers Annsa uses, ported so the hook refuses exactly what the server describes.

Source of truth: backend/services/principle_limits.py in annsa-ai/Annsa (command_matches,
path_matches, segment_tokens, command_path_targets, command_touches_path). Keep this file
the same as that one: a change to a matcher there is a change here, in the same release.

Two grammars, neither a regex, both linear in pattern length times input length:
- words-v1 (a command): words with `*` (any characters), `?` (one character) and the word `**`
  (any number of words). Matches from the command's first word and reads as if it ended in `**`.
- glob-v1 (a path): segments split on `/`; `*` and `?` stay in one name, a whole segment `**`
  is any folders; matches at any depth unless it starts with `/`; what is beneath a match counts.

This stops an honest mistake. It is not a sandbox: a script, a variable or an encoded path gets past it.
Stdlib only.

Beyond the server's matcher (1.2.0, from the security review of PR #7; worth porting back to
principle_limits.py): a relative operand is also tried against the working directory
(`cd backend/migrations && rm x`), and ONE rule replaces the list of known writers: a segment
that names the limit's path, or a literal part of it, anywhere in any word is refused, unless it
starts with a bare read-only program (cat, ls, head, tail, wc, stat, file, grep, diff, echo, pwd,
test). It catches mistakes; it is not a sandbox.
"""

from __future__ import annotations

import os
import posixpath
import re
import shlex
from typing import Any, List, Optional, Sequence

COMMAND_GRAMMAR = "words-v1"
PATH_GRAMMAR = "glob-v1"
MAX_PATTERN = 200
MAX_WORDS = 20


def glob_match(pattern: str, text: str) -> bool:
    """`*` any characters, `?` one character, everything else literal. Two
    pointers with one backtrack point: at most len(pattern) * len(text) steps."""
    p = t = 0
    star = -1
    mark = 0
    while t < len(text):
        if p < len(pattern) and pattern[p] == "*":
            star, mark = p, t
            p += 1
        elif p < len(pattern) and (pattern[p] == "?" or pattern[p] == text[t]):
            p += 1
            t += 1
        elif star >= 0:
            mark += 1
            t = mark
            p = star + 1
        else:
            return False
    while p < len(pattern) and pattern[p] == "*":
        p += 1
    return p == len(pattern)


def _sequence_match(
    pattern: Sequence[str], items: Sequence[str], one: Any, *, anchored_end: bool
) -> bool:
    """`pattern` against `items` from the first one; `**` is any number of items.
    Two pointers with one backtrack point: at most len(pattern) * len(items) steps.
    Unless `anchored_end`, the pattern reads as if it ended in `**`."""
    p = i = 0
    star = -1
    mark = 0
    while i < len(items):
        if p < len(pattern) and pattern[p] == "**":
            star, mark = p, i
            p += 1
        elif p < len(pattern) and one(pattern[p], items[i]):
            p += 1
            i += 1
        elif p == len(pattern) and not anchored_end:
            return True
        elif star >= 0:
            mark += 1
            i = mark
            p = star + 1
        else:
            return False
    while p < len(pattern) and pattern[p] == "**":
        p += 1
    return p == len(pattern)


def command_matches(pattern: str, words: Sequence[str]) -> bool:
    """A command limit against one parsed command segment's words."""
    return _sequence_match(pattern.split(), list(words), glob_match, anchored_end=False)


def _segments(path: str) -> List[str]:
    return [seg for seg in path.split("/") if seg and seg != "."]


def path_matches(glob: str, path: str) -> bool:
    """A path limit against one path operand: any depth unless the glob starts
    with `/`, and what is beneath a match counts. `a/./b` and `a/../b` are
    resolved first."""
    want = _segments(glob)
    if not glob.startswith("/"):
        want = ["**"] + want
    if path.startswith("/") != glob.startswith("/") and glob.startswith("/"):
        return False
    have = _segments(posixpath.normpath(path) if path else path)
    return _sequence_match(want, have, glob_match, anchored_end=False)


_SHELL_GLOB = "*?["


def _seg_overlap(op: str, g: str) -> bool:
    """Could the operand's name `op` (which may hold shell glob characters) and
    the limit's `g` name the same file? A shell `*` never matches a leading dot."""
    op = re.sub(r"\[[^\]]*\]", "?", op)
    op_wild = any(c in op for c in "*?")
    g_wild = any(c in g for c in "*?")
    if not op_wild:
        return glob_match(g, op)
    if op[0] in "*?" and g[:1] == ".":
        return False
    if not g_wild:
        return glob_match(op, g)
    pre_op, pre_g = re.split(r"[*?]", op, maxsplit=1)[0], re.split(r"[*?]", g, maxsplit=1)[0]
    suf_op, suf_g = re.split(r"[*?]", op)[-1], re.split(r"[*?]", g)[-1]
    return (pre_op.startswith(pre_g) or pre_g.startswith(pre_op)) and (
        suf_op.endswith(suf_g) or suf_g.endswith(suf_op)
    )


def _aligned(g: List[str], o: List[str]) -> bool:
    """Do the operand's segments line up with the limit's from its start? A wildcard
    tail like `app/.e*` or `/repo/*` still counts: it could expand to the path."""
    if not o:
        return True  # names the root, an ancestor of everything
    for i, seg in enumerate(o):
        if i >= len(g) or g[i] == "**":
            return True  # beneath a match, or under a `**`
        if not _seg_overlap(seg, g[i]):
            return False
    return True  # the operand is the limit's path or an ancestor of it


def _overlaps(glob: str, op: str, *, anywhere: bool) -> bool:
    """Is `op` the path, a folder holding it, or (with shell glob characters) a
    name that could expand to it? The glob is compared from the repo root, or from
    any folder when the operand has shell globs."""
    if glob.startswith("/") and not op.startswith("/"):
        return False  # an absolute glob can't be placed on a relative operand
    g, o = _segments(glob), _segments(op)
    # A relative glob sits at any depth, as path_matches reads it (`**/glob`), so against
    # an absolute operand it is tried at every folder. A bare name like `.env*` is also
    # tried at every folder of a relative operand that has shell globs; a relative
    # operand is otherwise read from the repo root.
    if glob.startswith("/"):
        starts = [0]
    elif op.startswith("/") or (anywhere and len(g) == 1):
        starts = list(range(max(len(o), 1)))
    else:
        starts = [0]
    return any(_aligned(g, o[i:]) for i in starts)


def _has_brace_expansion(word: str) -> bool:
    """A `{` with a `,` or `..`: the shell may expand it into several words, so it is
    refused whatever the quoting (a quoted one over-refuses, which is the safe side)."""
    return "{" in word and ("," in word or ".." in word)


def _has_expansion(word: str) -> bool:
    """A `$` outside single quotes (a variable, `$(…)`, `$((…))`), unless it is the
    word's last character. A backslash-escaped one is a plain `$`."""
    quote = ""
    i = 0
    while i < len(word):
        c = word[i]
        if quote == "'":
            quote = "" if c == "'" else quote
        elif c == "\\" and i + 1 < len(word):
            i += 1
        elif c in "'\"":
            quote = c if not quote else ("" if quote == c else quote)
        elif c == "$" and i < len(word) - 1:
            return True
        i += 1
    return False


def _dequote(word: str) -> Optional[str]:
    """The word as the shell reads it: quotes and backslashes resolved. None when it
    can't be resolved (an unbalanced quote), which the caller treats as a refusal."""
    if (
        any(marker in word for marker in ("$'", '$"', "`", "$("))
        or _has_expansion(word)
        or _has_brace_expansion(word)
    ):
        return None  # the shell would expand or decode it into something else
    try:
        parts = shlex.split(word, posix=True)
    except ValueError:
        return None
    if len(parts) > 1:
        return None
    return parts[0] if parts else ""


def _home() -> str:
    return os.environ.get("HOME") or "/home/user"


def path_touched(
    glob: str, operand: str, *, recursive: bool = False, cwd: Optional[str] = None
) -> bool:
    """Does a write to `operand` touch the limit's path? It does when it is the
    path or beneath it; a path that climbs out of where it started (`../x`) can't
    be placed, so it counts; a recursive writer (rm -r, mv, rsync --delete) also
    touches a folder that holds the path; an operand with shell glob characters
    counts when what it could expand to overlaps the path."""
    op = operand
    if not op:
        return False
    if recursive and op in ("/", "~", "~/"):
        return True
    if op.startswith("~"):
        if op != "~" and not op.startswith("~/"):
            return True  # `~user`: someone else's home, can't be placed
        op = _home() + op[1:]
    # macOS and Windows compare names without case, so `.ENV` is `.env`.
    op, glob = op.lower(), glob.lower()
    op = posixpath.normpath(op)
    if recursive and cwd and op.startswith("/"):
        # A recursive write onto a folder that holds where the command runs.
        here = posixpath.normpath(cwd.lower())
        if here == op or here.startswith(op.rstrip("/") + "/"):
            return True
    if op == ".." or op.startswith("../"):
        return True
    if path_matches(glob, op):
        return True
    if cwd and not op.startswith("/"):
        # The same operand placed under where the command runs: `cd backend/migrations && rm x`.
        placed = posixpath.normpath(posixpath.join(cwd.lower(), op))
        if path_matches(glob, placed) or (
            any(c in op for c in _SHELL_GLOB) and _overlaps(glob, placed, anywhere=True)
        ):
            return True
    if any(c in op for c in _SHELL_GLOB):
        return _overlaps(glob, op, anywhere=True)
    return recursive and _overlaps(glob, op, anywhere=False)


_REDIRECTS = {">", ">>", "&>", "&>>", ">|"}


def segment_tokens(text: str) -> List[str]:
    """One command segment's tokens, quote-aware: a word is split on unquoted spaces
    only, so `".en"v` is one word (the shell joins them), and its quotes are kept for
    `_dequote`. An unquoted `>`, `>>`, `>|`, `>&`, `&>`, `&>>` is split out as its own
    token wherever it sits (`echo x>.env` is `echo`, `x`, `>`, `.env`), taking a
    file-descriptor number before it (`2>`) with it."""
    out: List[str] = []
    cur: List[str] = []
    quote = ""
    i = 0

    def flush() -> None:
        if cur:
            out.append("".join(cur))
            cur.clear()

    while i < len(text):
        c = text[i]
        if quote:
            cur.append(c)
            if c == "\\" and quote == '"' and i + 1 < len(text):
                cur.append(text[i + 1])
                i += 1
            elif c == quote:
                quote = ""
        elif c == "\\" and i + 1 < len(text):
            cur.append(c + text[i + 1])
            i += 1
        elif c in "'\"":
            quote = c
            cur.append(c)
        elif c.isspace():
            flush()
        elif c == ">" or (c == "&" and text[i + 1 : i + 2] == ">"):
            if cur and "".join(cur).isdigit():
                cur.clear()  # `2>`: the descriptor belongs to the operator
            flush()
            j = i + 1 if c == ">" else i + 2
            while j < len(text) and text[j] in ">|&" and j - i < 3:
                if text[j] == "&" and text[j - 1] != ">":
                    break
                j += 1
                if text[j - 1] in "|&":
                    break
            out.append(text[i:j])
            i = j - 1
        else:
            cur.append(c)
        i += 1
    flush()
    return out


#: The only programs trusted to read: a bare name (no `/`), so `/usr/bin/cat` is not one. A
#: segment that starts with one is not refused for naming the path or for a word the shell
#: would expand (`echo $HOME`); its redirects still are. Keep in step with enforce.READ_ONLY.
_READ_ONLY = {"cat", "ls", "head", "tail", "wc", "stat", "file", "grep", "diff", "echo", "pwd", "test", "["}


def command_path_targets(tokens: Sequence[str]) -> List[tuple]:
    """(operand, recursive) for each path one command segment could write to. One rule: unless
    the segment starts with a bare read-only program, every word of it (`--out=x` also as `x`)
    counts as a path, and a word that names a folder holding the limit's path counts too. The
    target of every redirect counts always. Every word is dequoted as the shell would; if any
    can't be resolved (an unbalanced quote, `$VAR`, a brace expansion) the segment is refused,
    shown here as an operand of `..`. Only a read-only segment is exempt, and then only its
    redirects are checked."""
    refuse = [("..", False)]
    raw = list(tokens)
    out: List[tuple] = []
    skip: set = set()
    for i, tok in enumerate(raw):
        if tok in _REDIRECTS and i + 1 < len(raw):
            target = _dequote(raw[i + 1])
            if target is None:
                return refuse
            out.append((target, False))
            skip.add(i + 1)
        elif tok == ">&" and i + 1 < len(raw):
            skip.add(i + 1)
            target = _dequote(raw[i + 1])
            if target is None:
                return refuse
            if not target.lstrip("-").isdigit():
                out.append((target, False))
    if not raw:
        return out
    if _dequote(raw[0]) in _READ_ONLY:
        return out
    idx = [
        i for i in range(len(raw)) if i not in skip and raw[i] not in _REDIRECTS and raw[i] != ">&"
    ]
    words = [_dequote(raw[i]) for i in idx]
    if any(x is None for x in words):
        return refuse
    for x in words:
        for part in {str(x), str(x).split("=", 1)[-1]}:
            if part:
                out.append((part, True))
    return out


def command_touches_path(
    glob: str, tokens: Sequence[str], cwd: Optional[str] = None, original: Optional[Sequence[str]] = None
) -> bool:
    """Does one command segment write to the limit's path? `cwd` is where it runs,
    when the caller knows: a recursive write onto a folder above it counts. Anything
    the check can't evaluate, including an error inside it, counts as touching: a
    limit never fails open."""
    try:
        if any(
            path_touched(glob, op, recursive=rec, cwd=cwd)
            for op, rec in command_path_targets(tokens)
        ):
            return True
        return _names_literal(glob, tokens, original) or _deletes_the_path(glob, tokens, cwd)
    except Exception:  # fail closed
        return True


def _literal_parts(glob: str) -> List[str]:
    """The literal runs of a path glob: `backend/migrations/001*` gives backend, migrations, 001."""
    return [run for run in re.split(r"[*?/]+", glob.lower()) if len(run) >= 2]


def _names_literal(glob: str, tokens: Sequence[str], original: Optional[Sequence[str]] = None) -> bool:
    """Does a segment that is not a bare read-only program name a literal part of the path
    anywhere (a flag value, `-so.env`, `--out=.env`, a script argument)?"""
    words = [_dequote(t) for t in tokens if t not in _REDIRECTS and t != ">&"]
    if not words or words[0] is None or words[0] in _READ_ONLY:
        return False
    # The whole segment as written, wrapper options included (`env -C dir`, `sudo -u x`).
    every = [_dequote(t) for t in (original if original is not None else tokens)]
    text = " ".join(w if w is not None else t for w, t in zip(every, original if original is not None else tokens)).lower()
    return any(part in text for part in _literal_parts(glob))


# --- a recursive delete that never names the path (`git clean -fd`, `rm -rf .`) ----------------

_RECURSIVE_RM = re.compile(r"^-[A-Za-z]*[rR][A-Za-z]*$")
_GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
_SCAN_LIMIT = 5000


_GIT_TREE_WRITERS = {"reset", "checkout", "restore", "stash", "apply", "merge", "pull", "rebase", "switch", "clean"}
_READ_FLAGS = {"-n", "--dry-run", "--check", "--stat", "--numstat", "--summary"}


def _git_parts(rest: List[str]):
    """(subcommand, its arguments, the -C directories) of git's arguments, global options skipped."""
    i, dirs = 0, []
    while i < len(rest):
        if rest[i] in _GIT_VALUE_OPTIONS:
            if rest[i] == "-C" and i + 1 < len(rest):
                dirs.append(rest[i + 1])
            i += 2
        elif rest[i].startswith("-"):
            i += 1
        else:
            break
    return (rest[i] if i < len(rest) else None), rest[i + 1 :], dirs


def _delete_operands(words: Sequence[str]) -> Optional[List[str]]:
    """The folders a tree-wide writer would rewrite (the working directory when none is
    named), or None when the segment is not one. Covers rm -r/-R/--recursive, find -delete,
    rsync --delete, git reset/checkout/restore/stash/apply/merge/pull/rebase/switch/clean,
    tar -x, unzip and patch; a dry run or a read-only flag (git clean -n, git apply --check,
    tar -t, unzip -l) is not one."""
    head, rest = posixpath.basename(words[0]), list(words[1:])
    flags = [x for x in rest if x.startswith("-")]
    plain = [x for x in rest if not x.startswith("-")]
    if head == "rm" and any(_RECURSIVE_RM.match(f) or f == "--recursive" for f in flags):
        return plain
    if head == "git":
        sub, after, dirs = _git_parts(rest)
        if sub not in _GIT_TREE_WRITERS:
            return None
        if sub == "stash" and after[:1] in (["list"], ["show"]):
            return None
        short = [f for f in after if f.startswith("-") and not f.startswith("--")]
        if any(f in _READ_FLAGS for f in after) or (
            sub == "clean" and any("n" in f[1:] for f in short)
        ):
            return None
        where = "."
        for d in dirs:
            where = posixpath.join(where, d)
        return [where]
    if head == "find" and "-delete" in rest:
        starts = []
        for x in rest:
            if x.startswith(("-", "(", "!")):
                break
            starts.append(x)
        return starts
    if head == "rsync" and any(f.startswith("--delete") for f in flags):
        return plain
    if head == "tar":
        first = rest[0] if rest else ""
        listing = any(f in ("--list", "--test-label") for f in flags) or any(
            re.fullmatch(r"-[A-Za-z]*t[A-Za-z]*", f) for f in flags
        ) or bool(re.fullmatch(r"[A-Za-z]*t[A-Za-z]*", first))
        extracting = any(f in ("--extract", "--get") for f in flags) or any(
            re.fullmatch(r"-[A-Za-z]*x[A-Za-z]*", f) for f in flags if not f.startswith("--")
        ) or bool(re.fullmatch(r"[A-Za-z]*x[A-Za-z]*", first))
        if listing or not extracting:
            return None
        dirs = [rest[i + 1] for i, x in enumerate(rest) if x in ("-C", "--directory") and i + 1 < len(rest)]
        dirs += [x.split("=", 1)[1] for x in flags if x.startswith("--directory=")]
        return dirs or ["."]
    if head == "unzip":
        if any(f in ("-l", "-t", "-v", "-z") for f in flags):
            return None
        dirs = [rest[i + 1] for i, x in enumerate(rest) if x == "-d" and i + 1 < len(rest)]
        return dirs or ["."]
    if head == "patch":
        if any(f in ("--dry-run",) for f in flags):
            return None
        dirs = [rest[i + 1] for i, x in enumerate(rest) if x in ("-d", "--directory") and i + 1 < len(rest)]
        return dirs or ["."]
    return None


def _deletes_the_path(glob: str, tokens: Sequence[str], cwd: Optional[str]) -> bool:
    """A recursive delete that empties a folder holding the limit's path, whether or not it
    names the path. Each operand is placed under the working directory; it counts when it is
    the path, an ancestor of it (a relative glob is read from the working directory), or a
    folder that holds something on disk the glob matches."""
    words = [_dequote(t) for t in tokens if t not in _REDIRECTS and t != ">&"]
    if not words or any(w is None for w in words):
        return False
    operands = _delete_operands([str(w) for w in words])
    if operands is None:
        return False
    here = posixpath.normpath((cwd or os.getcwd()).lower())
    glob = glob.lower()
    g_abs = _segments(glob if glob.startswith("/") else here + "/" + glob)
    for op in operands or ["."]:
        op = op.lower()
        if op.startswith("~"):
            op = _home().lower() + op[1:]
        placed = posixpath.normpath(posixpath.join(here, op))
        if _aligned(g_abs, _segments(placed)) or _holds_a_match(glob, placed, here):
            return True
    return False


def _holds_a_match(glob: str, folder: str, here: str) -> bool:
    """Is there, under `folder` on disk, an entry the glob matches? Bounded: a folder too
    big to scan counts as holding one (fail closed)."""
    if not os.path.isdir(folder):
        return False
    seen = 0
    for root, dirs, files in os.walk(folder):
        for name in dirs + files:
            seen += 1
            if seen > _SCAN_LIMIT:
                return True
            entry = posixpath.join(root, name).lower()
            rel = posixpath.relpath(entry, here) if entry.startswith(here.rstrip("/") + "/") else entry
            if path_matches(glob, rel):
                return True
    return False
