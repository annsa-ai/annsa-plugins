#!/usr/bin/env bash
# Annsa principle enforcement for Claude Code (PreToolUse, Bash) and Cursor
# (beforeShellExecution, run with --cursor). Reads the hook's JSON on stdin and
# hands it to enforce.py, which decodes it before looking at the command.
# This stops honest mistakes; it is not a security boundary. Anything that goes
# wrong (no python, a crash, Annsa unreachable) allows the command. Cursor wants
# an answer every time, so on that side "allow" is printed.

allow() { [ "$1" = "--cursor" ] && printf '{"permission":"allow"}\n'; exit 0; }

[ "${ANNSA_ENFORCE:-1}" = "0" ] && allow "$1"

input=$(cat)
py=$(command -v python3) || allow "$1"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out=$(printf '%s' "$input" | "$py" "$here/enforce.py" "$@" 2>/dev/null)
if [ -n "$out" ]; then printf '%s\n' "$out"; else allow "$1"; fi
exit 0
