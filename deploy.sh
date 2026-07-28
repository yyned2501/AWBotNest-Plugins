#!/usr/bin/env bash
# deploy.sh —— 把本地开发好的插件同步到 tower 上的 AWBotNest 平台并热重载
#
# 流程：rsync 本地 plugins/<id> → tower:/mnt/user/appdata/awbotnest/plugins/<id>
#       然后调用平台开放 API POST /plugins/<id>/reload 热重载。
#
# 密钥全部从 pass 读取，不硬编码：
#   - SSH 口令：pass system/tower（第 1 行）
#   - API Key ：pass awbotnest/api
#
# 用法：
#   ./deploy.sh <插件> [<插件>...]    # 同步并重载指定插件（目录插件或单文件插件均可）
#   ./deploy.sh --all                 # 同步所有本地在开发的插件
#   ./deploy.sh -n <插件>             # dry-run，只显示 rsync 会传什么，不真传、不 reload
#   ./deploy.sh --delete <插件>       # 镜像同步（会删除远端多出的文件——慎用，会清掉运行时数据）
#
# 说明：默认 **不带** --delete，避免误删 tower 上的运行时数据（如 skyDropAnswer/templates
#       里学习到的模板）。新增/改名后想清掉远端旧文件时再显式加 --delete。

set -euo pipefail

# ---------- 配置 ----------
TOWER_HOST="192.168.31.10"
TOWER_USER="root"
REMOTE_PLUGINS="/mnt/user/appdata/awbotnest/plugins"
API_BASE="http://${TOWER_HOST}:18001/api/v1"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_PLUGINS="${REPO_ROOT}/plugins"
REMOTE_OWNER="1001:1001"   # 与现有开发插件属主保持一致（容器以 root 运行，属主不影响读写）

# 单文件插件里不算真实插件、需排除的
SKIP_FILES=("_TEMPLATE.py" "scratch.py" "__init__.py")

# ---------- 参数解析 ----------
DRY_RUN=0
DELETE=0
ALL=0
TARGETS=()
for arg in "$@"; do
  case "$arg" in
    -n|--dry-run) DRY_RUN=1 ;;
    --delete)     DELETE=1 ;;
    --all)        ALL=1 ;;
    -h|--help)    grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)            TARGETS+=("$arg") ;;
  esac
done

# ---------- 收集目标插件 ----------
if [ "$ALL" -eq 1 ]; then
  # 目录插件：含 __init__.py 的子目录
  for d in "$LOCAL_PLUGINS"/*/; do
    [ -f "${d}__init__.py" ] && TARGETS+=("$(basename "$d")")
  done
  # 单文件插件：顶层 *.py（排除模板/草稿）
  for f in "$LOCAL_PLUGINS"/*.py; do
    name="$(basename "$f")"
    skip=0
    for s in "${SKIP_FILES[@]}"; do [ "$name" = "$s" ] && skip=1; done
    [ "$skip" -eq 0 ] && TARGETS+=("${name%.py}")
  done
fi

if [ "${#TARGETS[@]}" -eq 0 ]; then
  echo "用法: ./deploy.sh [-n] [--delete] <插件> [...] 或 ./deploy.sh --all" >&2
  exit 1
fi

# 去重
mapfile -t TARGETS < <(printf '%s\n' "${TARGETS[@]}" | awk '!seen[$0]++')

# ---------- 取密钥 ----------
SSH_PASS="$(pass show system/tower 2>/dev/null | sed -n '1p')"
API_KEY="$(pass show awbotnest/api 2>/dev/null | sed -n '1p')"
[ -n "$SSH_PASS" ] || { echo "错误: 无法从 pass system/tower 读取 SSH 口令" >&2; exit 1; }
[ -n "$API_KEY" ]  || { echo "错误: 无法从 pass awbotnest/api 读取 API Key" >&2; exit 1; }

RSYNC_SSH="sshpass -p ${SSH_PASS} ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
RSYNC_OPTS=(-rltz --chown="${REMOTE_OWNER}"
            --exclude='__pycache__' --exclude='*.pyc'
            --exclude='node_modules' --exclude='.git')
[ "$DELETE" -eq 1 ] && RSYNC_OPTS+=(--delete)
[ "$DRY_RUN" -eq 1 ] && RSYNC_OPTS+=(--dry-run --itemize-changes)

# ---------- reload ----------
reload_plugin() {
  local id="$1" resp code
  resp="$(curl -s --noproxy '*' -m 20 -w '\n%{http_code}' \
            -X POST -H "X-API-Key: ${API_KEY}" "${API_BASE}/plugins/${id}/reload")"
  code="$(printf '%s' "$resp" | tail -n1)"
  body="$(printf '%s' "$resp" | sed '$d')"
  if [ "$code" = "200" ]; then
    echo "  reload ✅ ${body}"
  else
    echo "  reload ❌ HTTP ${code} ${body}" >&2
    return 1
  fi
}

# ---------- 主循环 ----------
echo "目标插件: ${TARGETS[*]}"
[ "$DELETE" -eq 1 ] && echo "⚠️  --delete 已开启：将镜像同步并删除远端多余文件（含运行时数据）"
[ "$DRY_RUN" -eq 1 ] && echo "（dry-run：不会真正传输或 reload）"
echo

fail=0
for id in "${TARGETS[@]}"; do
  echo "▶ ${id}"
  # 判定是目录插件还是单文件插件
  if [ -d "${LOCAL_PLUGINS}/${id}" ]; then
    src="${LOCAL_PLUGINS}/${id}/"
    dst="${REMOTE_PLUGINS}/${id}/"
  elif [ -f "${LOCAL_PLUGINS}/${id}.py" ]; then
    src="${LOCAL_PLUGINS}/${id}.py"
    dst="${REMOTE_PLUGINS}/${id}.py"
  else
    echo "  跳过：本地找不到 plugins/${id} 或 plugins/${id}.py" >&2
    fail=1; continue
  fi

  # shellcheck disable=SC2086
  if ! sshpass -p "$SSH_PASS" rsync "${RSYNC_OPTS[@]}" -e "$RSYNC_SSH" "$src" "${TOWER_USER}@${TOWER_HOST}:${dst}"; then
    echo "  同步 ❌ rsync 失败" >&2; fail=1; continue
  fi
  echo "  同步 ✅ → ${dst}"

  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  reload ⏭️  (dry-run 跳过)"
  else
    reload_plugin "$id" || fail=1
  fi
  echo
done

[ "$fail" -eq 0 ] && echo "全部完成 ✅" || { echo "存在失败项 ❌" >&2; exit 1; }
