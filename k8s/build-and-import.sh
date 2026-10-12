#!/usr/bin/env bash
# =============================================================================
# build-and-import.sh
#
# k3s는 Docker Engine과 별개인 자체 containerd를 쓰기 때문에, docker build로
# 만든 이미지를 그대로 파드에서 쓸 수 없다 — 명시적으로 k3s의 containerd에
# 넘겨(import)줘야 한다(레지스트리 없이 단일 노드 로컬 클러스터에서 쓰는 방법).
# 각 k8s/*.yaml Deployment는 imagePullPolicy: Never라 여기서 만든 이미지를
# 그대로 쓰고 레지스트리를 조회하지 않는다.
#
# 사용법: ./k8s/build-and-import.sh
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

apps=(api mcp-server rag-worker stt-worker frontend)

for app in "${apps[@]}"; do
  tag="vps-detector/${app}:local"
  echo "==> docker build -t ${tag} apps/${app}"
  docker build -t "${tag}" "apps/${app}"
  echo "==> importing ${tag} into k3s containerd (sudo 필요)"
  docker save "${tag}" | sudo k3s ctr images import -
done

echo
echo "done. 이제 저장소 루트에서: kubectl apply -k ."
