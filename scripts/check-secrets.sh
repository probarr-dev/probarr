#!/usr/bin/env bash
# Blocks credentials from ever entering git history.
#
# Git history is effectively permanent: deleting a secret in a later commit
# does not remove it from the repo. This runs as a pre-commit hook and in CI,
# so the check exists from the very first commit rather than being retrofitted.
#
# Usage:
#   scripts/check-secrets.sh            # scan staged changes (hook mode)
#   scripts/check-secrets.sh --all      # scan every tracked file
set -uo pipefail

RED=$'\033[31m'; YEL=$'\033[33m'; GRN=$'\033[32m'; OFF=$'\033[0m'
[ -t 1 ] || { RED=""; YEL=""; GRN=""; OFF=""; }

# bash 3.2 (macOS default) has no `mapfile`, so read into the array the
# portable way. Do not "modernise" this to mapfile -- it silently produces an
# EMPTY file list on macOS, which makes the scan pass without checking anything.
FILES=()
if [ "${1:-}" = "--all" ]; then
  while IFS= read -r line; do FILES+=("$line"); done < <(git ls-files)
else
  while IFS= read -r line; do FILES+=("$line"); done < <(git diff --cached --name-only --diff-filter=ACM)
fi

# Files that are allowed to contain secret-shaped strings (they are templates
# or the checker's own patterns).
is_allowlisted() {
  case "$1" in
    .env.example|scripts/check-secrets.sh|README.md) return 0 ;;
    *) return 1 ;;
  esac
}

# name|regex  -- kept deliberately broad; false positives are cheap, a leaked
# provider URL is not.
PATTERNS=(
  'IPTV credentials in URL|[?&](username|password|u|p)=[A-Za-z0-9]{6,}'
  'Xtream player_api URL with creds|player_api\.php\?[^"'\''[:space:]]*(username|user)='
  'Xtream get.php URL|get\.php\?[^"'\''[:space:]]*(username|user)='
  'Private key block|-----BEGIN [A-Z ]*PRIVATE KEY-----'
  'AWS access key|AKIA[0-9A-Z]{16}'
  'Bearer/JWT token|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.'
  # Require a quoted LITERAL value. Matching bare identifiers flagged every
  # line of ordinary code that merely passes a password variable around, which
  # trains people to ignore the checker -- worse than not having one.
  'Generic api key literal|(api[_-]?key|apikey|secret|token)["'\'']?[[:space:]]*[:=][[:space:]]*["'\''][A-Za-z0-9/+_-]{16,}["'\'']'
  'Password literal|(password|passwd|pass)["'\'']?[[:space:]]*[:=][[:space:]]*["'\''][^"'\''${}]{8,}["'\'']'
  'Private RFC1918 host|\b(192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.)[0-9]{1,3}\.[0-9]{1,3}\b'
)

fail=0
for f in "${FILES[@]:-}"; do
  [ -z "$f" ] && continue
  [ -f "$f" ] || continue
  is_allowlisted "$f" && continue
  # Skip binaries.
  grep -Iq . "$f" 2>/dev/null || continue
  for entry in "${PATTERNS[@]}"; do
    label="${entry%%|*}"; rx="${entry#*|}"
    if hits=$(grep -nEI "$rx" "$f" 2>/dev/null); then
      # Allow an explicit opt-out marker for genuine false positives.
      hits=$(printf '%s\n' "$hits" | grep -v 'channeliq:allow-secret' || true)
      [ -z "$hits" ] && continue
      fail=1
      printf '%s\n' "${RED}SECRET?${OFF} ${YEL}${label}${OFF} in ${f}"
      printf '%s\n' "$hits" | sed 's/^/    /' | cut -c1-160
    fi
  done
done

# Never allow these paths to be committed at all.
for f in "${FILES[@]:-}"; do
  case "$f" in
    .env|*/.env|config/*|work/*|*.m3u|*.m3u8)
      printf '%s\n' "${RED}BLOCKED${OFF} ${f} must not be committed (runtime/credential path)"
      fail=1 ;;
  esac
done

if [ "$fail" -ne 0 ]; then
  cat <<'MSG'

Commit blocked. If a match is a genuine false positive, either add the file to
the allowlist in scripts/check-secrets.sh or append the marker

    channeliq:allow-secret

to the offending line. Do NOT bypass with --no-verify: once a secret is in a
commit it stays in the history even after you delete it.
MSG
  exit 1
fi

printf '%s\n' "${GRN}secret scan clean${OFF}"
