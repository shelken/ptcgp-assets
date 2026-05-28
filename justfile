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

# 从运行中的 PTCGP 游戏更新 cards.extra metadata
update-cards-extra frida_test_dir:
    uv run python scripts/update_cards_extra.py --frida-test-dir '{{ frida_test_dir }}'
