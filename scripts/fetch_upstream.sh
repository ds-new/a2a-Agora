#!/usr/bin/env bash
# Pull the upstream code this project was built from, pinned to the commits it was read at.
#
#   bash scripts/fetch_upstream.sh            # sources only (skips the ~3 GB Phoenix model in Git LFS)
#   WITH_LFS=1 bash scripts/fetch_upstream.sh # also download Git LFS objects (needs git-lfs)
#
# Licenses: xai-org/x-algorithm, a2aproject/A2A and google-agentic-commerce/AP2 are Apache-2.0.
# twitter/the-algorithm and twitter/the-algorithm-ml (2023) are AGPL-3.0; this project does not
# copy code from them, it only cites three default parameter values (see agora/ranking/value_model.py).
set -euo pipefail

DEST="${1:-upstream}"
mkdir -p "$DEST"

REPOS=(
  "x-algorithm      https://github.com/xai-org/x-algorithm          9081b332f25634db1c3249ebd3d56fba332fd2e6"
  "the-algorithm    https://github.com/twitter/the-algorithm        c54bec0d4e029fe34926ef3258a86ccacc0d0182"
  "the-algorithm-ml https://github.com/twitter/the-algorithm-ml     b85210863f7a94efded0ef5c5ccf4ff42767876c"
  "a2a-spec         https://github.com/a2aproject/A2A               5f931b8a25fe66789f987ec4a55fc16ee9fe41ee"
  "ap2              https://github.com/google-agentic-commerce/AP2  e1ea56db72a6385bce3e5c1112b3a56ce60acb43"
)

for entry in "${REPOS[@]}"; do
  read -r name url sha <<<"$entry"
  dir="$DEST/$name"
  if [ -d "$dir/.git" ] && [ "$(git -C "$dir" rev-parse HEAD 2>/dev/null)" = "$sha" ]; then
    echo "ok    $name @ ${sha:0:7} (already present)"
    continue
  fi
  echo "fetch $name @ ${sha:0:7}"
  rm -rf "$dir" && mkdir -p "$dir"
  git -C "$dir" init -q
  git -C "$dir" remote add origin "$url"
  if [ "${WITH_LFS:-0}" = "1" ]; then
    git -C "$dir" fetch -q --depth 1 origin "$sha"
    git -C "$dir" checkout -q FETCH_HEAD
    git -C "$dir" lfs pull || echo "warn  git-lfs pull failed for $name"
  else
    GIT_LFS_SKIP_SMUDGE=1 git -C "$dir" fetch -q --depth 1 origin "$sha"
    GIT_LFS_SKIP_SMUDGE=1 git -C "$dir" checkout -q FETCH_HEAD
  fi
done

cat <<'EOF'

Files the Python port follows most closely:
  x-algorithm/candidate-pipeline/candidate_pipeline.rs   -> agora/ranking/pipeline.py
  x-algorithm/home-mixer/                                -> agora/ranking/for_you.py
  x-algorithm/xai-value-model/scoring.rs, weights.rs     -> agora/ranking/value_model.py
  x-algorithm/home-mixer/params/param.rs (weights)       -> agora/ranking/value_model.py
  x-algorithm/phoenix/xrex/models/recsys_model.py        -> agora/ranking/phoenix_lite.py
  x-algorithm/vm-ranker/dpp.rs                           -> agora/ranking/dpp.py
  x-algorithm/user-cred-v2/UserCredV2App.scala           -> agora/ranking/usercred.py
  x-algorithm/simclusters/                               -> agora/ranking/simclusters.py
  x-algorithm/visibility-filtering/rules/registry.rs     -> agora/ranking/visibility.py
  a2a-spec/specification/a2a.proto, docs/specification.md -> agora/a2a/
  ap2/docs/ap2/specification.md, code/sdk/schemas/ap2/   -> agora/protocol/mandates.py

Agents reach the ported X stack only as optional skills (x_rank, x_retrieve, x_safety,
x_reputation, x_audience, x_for_you), wrapped in agora/skills/x_stack.py.
EOF
