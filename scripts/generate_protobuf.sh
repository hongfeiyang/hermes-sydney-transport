#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
proto_dir="$repo_root/hermes_sydney_transport/proto"

python -m grpc_tools.protoc \
  --proto_path="$proto_dir" \
  --python_out="$proto_dir" \
  "$proto_dir/tfnsw_gtfs_realtime.proto"
