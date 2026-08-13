#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

mode="${1:-all}"

architecture() {
  python scripts/check_architecture.py
}

lint() {
  ruff check hermes_sydney_transport scripts tests
  ruff format --check hermes_sydney_transport scripts tests
}

types() {
  if python -c "import mypy" >/dev/null 2>&1; then
    python -m mypy hermes_sydney_transport
  elif command -v mypy >/dev/null 2>&1; then
    mypy hermes_sydney_transport
  elif command -v uv >/dev/null 2>&1; then
    UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/sydney-transport-uv-cache}" \
      UV_TOOL_DIR="${UV_TOOL_DIR:-/tmp/sydney-transport-uv-tools}" \
      UV_TOOL_BIN_DIR="${UV_TOOL_BIN_DIR:-/tmp/sydney-transport-uv-bin}" \
      uv tool run --from 'mypy>=1.15,<2' \
      --with 'pydantic>=2.9,<3' --with 'protobuf>=6.31,<8' \
      mypy hermes_sydney_transport
  else
    echo "mypy is required; install the dev extra with: pip install -e '.[dev]'" >&2
    exit 1
  fi
}

test_suite() {
  PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS=error::ResourceWarning \
    python -m unittest discover -s tests -v
}

package_smoke() {
  package_tmp="$(mktemp -d)"
  trap 'rm -rf "$package_tmp"' RETURN
  mkdir "$package_tmp/source" "$package_tmp/wheel"
  cp -a hermes_sydney_transport pyproject.toml README.md LICENSE \
    "$package_tmp/source/"
  (
    cd "$package_tmp/source"
    python -c \
      'import setuptools.build_meta as backend, sys; backend.build_wheel(sys.argv[1])' \
      "$package_tmp/wheel" >/dev/null
  )
  wheel_path="$(find "$package_tmp/wheel" -maxdepth 1 -name '*.whl' -print -quit)"
  test -n "$wheel_path"
  python scripts/inspect_wheel.py "$wheel_path"
}

case "$mode" in
  architecture) architecture ;;
  lint) lint ;;
  types) types ;;
  test) test_suite ;;
  package) package_smoke ;;
  all)
    architecture
    lint
    types
    test_suite
    package_smoke
    ;;
  *)
    echo "usage: $0 [architecture|lint|types|test|package|all]" >&2
    exit 2
    ;;
esac
