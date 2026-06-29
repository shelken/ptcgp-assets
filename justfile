# PTCGP 资源下载命令集合（使用 uv）

# 直接运行 `just` 时显示可用命令
default:
    @just --list

# 查看 fetch_cards.py 参数帮助
help:
    uv run fetch_cards.py --help

# 下载所有系列（README 默认方式）
download:
    uv run fetch_cards.py

# 下载所有系列（详细日志，显示具体 URL）
download-verbose:
    uv run fetch_cards.py --verbose

# 下载指定系列，例如：just download-series "a"
download-series series="a":
    uv run fetch_cards.py --series '{{ series }}'

# 下载指定语言，例如：just download-langs "zh-TW,en-US"
download-langs langs="zh-TW,en-US":
    uv run fetch_cards.py --langs '{{ langs }}'

# 自定义完整参数
# 示例：
# just download-custom "a,b" "zh-TW,en-US" 30 5

# just download-custom "a,b" "zh-TW,en-US" 30 5 "--verbose"
download-custom series="a,b" langs="zh-TW,en-US" concurrency="20" max_retries="3" verbose_flag="":
    uv run fetch_cards.py --series '{{ series }}' --langs '{{ langs }}' --concurrency {{ concurrency }} --max-retries {{ max_retries }} {{ verbose_flag }}

# 从运行中的 PTCGP 游戏更新 cards.extra 与 sets metadata
update-metadata frida_test_dir:
    uv run python scripts/update_metadata.py --frida-test-dir '{{ frida_test_dir }}'

# 生成卡牌感知哈希 JSON（供 ptcgp-auto 游戏端拉取，免新用户下载全量卡图）
# 修改算法后必须同步更新 _ALGO_VERSION 并跑 tests/test_hashes.py
generate-hashes locale="zh-TW":
    uv run python scripts/generate_hashes.py --locale '{{ locale }}'

# 只生成指定 set 的哈希
generate-hashes-set set locale="zh-TW":
    uv run python scripts/generate_hashes.py --locale '{{ locale }}' --set '{{ set }}'
