# PTCGP 资源更新命令集合（使用 uv）

# 直接运行 `just` 时显示可用命令
default:
    @just --list

# === 一键全流程：下载卡牌 + hash + metadata + 卡包图 + 汇总 ===
# 前置：bs air 游戏已更新到最新版本并进入游戏主页
# expansions 为空时 update-device 自动对比缺失系列；传 code（如 B3b,A1）只处理指定系列
update-all expansions="":
    just update-online '{{ expansions }}'
    just update-device '{{ expansions }}'

# === 无设备依赖（可随时重跑）：下载卡牌图 + 增量生成 hash ===
# expansions 传 code 时只处理指定系列；空则全量
update-online expansions="":
    uv run fetch_cards.py {{ if expansions != "" { "--expansions " + expansions } else { "" } }}
    uv run python scripts/generate_hashes.py {{ if expansions != "" { "--expansions " + expansions } else { "" } }}
    @echo "✅ online 完成（卡牌图下载 + hash 生成）"

# === 需设备 + 游戏进主页：导出 metadata + 卡包图 + 汇总 ===
# expansions 为空时自动对比游戏与 repo，只更新缺失系列；传 code 只处理指定系列
update-device expansions="":
    #!/usr/bin/env bash
    set -euo pipefail
    EXPANSIONS='{{ expansions }}'
    # 空则自动对比缺失系列
    if [ -z "$EXPANSIONS" ]; then
        echo "=== 自动对比缺失系列 ==="
        EXPANSIONS=$(uv run python scripts/list_missing_expansions.py --print-only)
        if [ -z "$EXPANSIONS" ]; then
            echo "✅ 无缺失系列，跳过设备更新"
            just _summary
            exit 0
        fi
        echo "缺失系列: $EXPANSIONS"
    fi
    echo "=== 导出 metadata（expansions=${EXPANSIONS}）==="
    uv run python scripts/update_metadata.py --expansions "$EXPANSIONS"
    echo ""
    echo "=== 导出卡包图片（expansions=${EXPANSIONS}）==="
    uv run python scripts/update_pack_images.py --expansions "$EXPANSIONS"
    echo ""
    echo "=== 产出汇总 ==="
    just _summary

# === 汇总报告：列出每个语言的 metadata/卡牌图/hash/pack 状态 ===
_summary:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "语言    | 卡牌图 sets | hash sets | metadata | pack 图"
    echo "--------|------------|-----------|----------|--------"
    for lang_dir in images/*/; do
        lang=$(basename "$lang_dir")
        # 只列出含 cards-by-set 的语言目录（排除 others 等）
        [ -d "images/$lang/cards-by-set" ] || continue
        card_sets=$(ls -d "images/$lang/cards-by-set"/*/ 2>/dev/null | wc -l | tr -d ' ')
        hash_sets=$(ls "hashes/$lang"/*.json 2>/dev/null | wc -l | tr -d ' ')
        if [ -f "metadata/cards/$lang/cards.extra.json" ]; then meta="✅"; else meta="—"; fi
        packs=$(ls "images/$lang/packs"/*.webp 2>/dev/null | wc -l | tr -d ' ')
        printf "%-7s | %10s | %9s | %8s | %s\n" "$lang" "$card_sets" "$hash_sets" "$meta" "$packs"
    done
    echo ""
    echo "提示: metadata 一次导出全语言（schemaVersion 4），pack 图按 expansion code 增量。"
    echo "       空参 update-device 无缺失系列时跳过；强制全量刷新请直接 uv run python scripts/update_metadata.py"

# === 只生成指定 set 的哈希（调试用）===
generate-hashes-set set locale="zh-TW":
    uv run python scripts/generate_hashes.py --locale '{{ locale }}' --set '{{ set }}'

# === 生成所有语言 hash（调试用，等同 update-online 的 hash 部分）===
generate-hashes:
    uv run python scripts/generate_hashes.py

# === 下载指定系列（调试用）===
download-langs langs="zh-TW,en-US":
    uv run fetch_cards.py --langs '{{ langs }}'
