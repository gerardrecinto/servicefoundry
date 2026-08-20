#!/usr/bin/env bash
# Runs every reference implementation under cases/ and reports pass/fail.
#
# Each solution file has a runnable demo (Python __main__ block, Java/Go
# main(), etc.) with inline assertions, so "passing" here means the demo
# ran to completion without an uncaught exception or a failed assertion.
#
# Usage:
#   scripts/run_examples.sh          # runs the .py reference solutions
#   scripts/run_examples.sh --all    # also attempts Java/Go/Ruby/C++ solutions
#                                     # (skipped individually if the toolchain
#                                     #  isn't installed, not treated as a failure)

set -u
cd "$(dirname "$0")/.."

run_all=0
if [[ "${1:-}" == "--all" ]]; then
  run_all=1
fi

pass=0
fail=0
skip=0

check() {
  local label="$1"
  shift
  if "$@" >/tmp/run_examples_out.$$ 2>&1; then
    echo "PASS  $label"
    pass=$((pass + 1))
  else
    echo "FAIL  $label"
    sed 's/^/      /' /tmp/run_examples_out.$$
    fail=$((fail + 1))
  fi
  rm -f /tmp/run_examples_out.$$
}

while IFS= read -r -d '' f; do
  check "$f" python3 "$f"
done < <(find cases -name 'solution.py' -print0 | sort -z)

if [[ "$run_all" -eq 1 ]]; then
  if command -v javac >/dev/null && command -v java >/dev/null; then
    tmpdir=$(mktemp -d)
    if javac -d "$tmpdir" cases/rate-limiter/Solution.java 2>/tmp/run_examples_out.$$; then
      check "cases/rate-limiter/Solution.java" java -cp "$tmpdir" Solution
    else
      echo "FAIL  cases/rate-limiter/Solution.java (compile)"
      sed 's/^/      /' /tmp/run_examples_out.$$
      fail=$((fail + 1))
    fi
    rm -rf "$tmpdir" /tmp/run_examples_out.$$
  else
    echo "SKIP  cases/rate-limiter/Solution.java (no javac/java on PATH)"
    skip=$((skip + 1))
  fi

  if command -v go >/dev/null; then
    check "cases/rate-limiter/solution.go" go run cases/rate-limiter/solution.go
  else
    echo "SKIP  cases/rate-limiter/solution.go (no go on PATH)"
    skip=$((skip + 1))
  fi

  if command -v ruby >/dev/null; then
    check "cases/rate-limiter/solution.rb" ruby cases/rate-limiter/solution.rb
  else
    echo "SKIP  cases/rate-limiter/solution.rb (no ruby on PATH)"
    skip=$((skip + 1))
  fi

  if command -v g++ >/dev/null; then
    tmpbin=$(mktemp)
    if g++ -std=c++17 -o "$tmpbin" cases/rate-limiter/solution.cpp 2>/tmp/run_examples_out.$$; then
      check "cases/rate-limiter/solution.cpp" "$tmpbin"
    else
      echo "FAIL  cases/rate-limiter/solution.cpp (compile)"
      sed 's/^/      /' /tmp/run_examples_out.$$
      fail=$((fail + 1))
    fi
    rm -f "$tmpbin" /tmp/run_examples_out.$$
  else
    echo "SKIP  cases/rate-limiter/solution.cpp (no g++ on PATH)"
    skip=$((skip + 1))
  fi
fi

echo
echo "$pass passed, $fail failed, $skip skipped"
[[ "$fail" -eq 0 ]]
