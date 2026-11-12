#!/usr/bin/env bash
# Annsa principle enforcement for Claude Code (PreToolUse, Bash) and Cursor
# (beforeShellExecution, run with --cursor). Reads the hook's JSON on stdin.
# Most commands leave here in a few milliseconds: only a command that names one
# of the enforceable verbs reaches enforce.py. Anything that goes wrong allows
# the command; this stops honest mistakes and is not a security boundary.
# Cursor wants an answer every time, so on that side "allow" is printed.

allow() { [ "$1" = "--cursor" ] && printf '{"permission":"allow"}\n'; exit 0; }

[ "${ANNSA_ENFORCE:-1}" = "0" ] && allow "$1"

input=$(cat)

# Fast path: no enforceable verb anywhere in the command, nothing to check.
case "$input" in
  *git*|*gh\ *|*vercel*|*netlify*|*fly*|*railway*|*apprunner*|*terraform*|*npm*|*pnpm*|*yarn*|*bun\ *|*rm\ *|*psql*|*mysql*|*sqlite3*|*supabase*) ;;
  *) allow "$1" ;;
esac

py=$(command -v python3) || allow "$1"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out=$(printf '%s' "$input" | "$py" "$here/enforce.py" "$@" 2>/dev/null)
if [ -n "$out" ]; then printf '%s\n' "$out"; else allow "$1"; fi
exit 0
