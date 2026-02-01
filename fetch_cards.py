#!/usr/bin/env python3
"""
PTCGP 卡牌图片爬虫
高性能异步下载 PokeOS 卡牌图片资源
"""

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

import aiohttp
import aiofiles
from tqdm.asyncio import tqdm
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)


@dataclass
class CardSet:
    """卡牌集合信息"""

    id: str
    set_code: str
    set_n_cards: int
    set_n_secrets: int
    series: str


class PTCGPDownloader:
    """PTCGP 卡牌图片下载器"""

    BASE_API_URL = "https://api.pokeos.com/api/tcg/set"
    IMAGE_BASE_URL = "https://s3.pokeos.com/pokeos-uploads/tcg/pocket"

    def __init__(
        self,
        base_dir: Path,
        languages: List[str],
        series_list: List[str],
        max_concurrency: int = 20,
        max_retries: int = 3,
    ):
        self.base_dir = base_dir
        self.languages = languages
        self.series_list = series_list
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries

        # 并发控制
        self.semaphore = asyncio.Semaphore(max_concurrency)

        # 统计
        self.stats = {
            "downloaded": 0,
            "skipped": 0,
            "failed": 0,
            "total": 0,
        }

        # 失败的 URL 列表，格式: (set_code, url)
        self.failed_items: List[tuple] = []

    async def fetch_sets(
        self, session: aiohttp.ClientSession, series: str
    ) -> List[CardSet]:
        """获取指定系列的卡牌集合列表"""
        url = f"{self.BASE_API_URL}?lang=pocket&group={series}"
        headers = {
            "Origin": "https://www.pokeos.com/",
            "Accept": "application/json",
        }

        try:
            async with session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response.raise_for_status()
                data = await response.json()

                sets = []
                for item in data:
                    # 跳过有 main_set 值的集合（子集），保留 main_set 为 None 的（主集）
                    if item.get("main_set") is not None:
                        continue

                    # 处理 PROMO 集合的 set_code，按系列区分
                    set_code = item["set_code"]
                    if set_code == "PROMO":
                        set_code = f"PROMO-{series.upper()}"

                    sets.append(
                        CardSet(
                            id=item["id"],
                            set_code=set_code,
                            set_n_cards=item.get("set_n_cards", 0),
                            set_n_secrets=item.get("set_n_secrets", 0),
                            series=series,
                        )
                    )

                return sets
        except Exception as e:
            print(f"[错误] 获取系列 {series} 失败: {e}")
            return []

    def get_image_path(self, lang: str, set_code: str, number: int) -> Path:
        """获取图片保存路径"""
        return (
            self.base_dir
            / "images"
            / lang
            / "cards-by-set"
            / set_code
            / f"{number}.png"
        )

    def get_image_url(self, set_id: str, number: int, lang: str) -> str:
        """获取图片 URL"""
        # 处理语言代码映射
        lang_map = {
            "zh-TW": "zh",
            "en-US": "en",
        }
        lang_code = lang_map.get(lang, lang)
        return f"{self.IMAGE_BASE_URL}/{set_id}/src/{number}_{lang_code}.png"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
        reraise=True,
    )
    async def download_image(
        self,
        session: aiohttp.ClientSession,
        url: str,
        filepath: Path,
        pbar: tqdm,
    ) -> bool:
        """下载单张图片"""
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                if response.status == 404:
                    # 图片不存在，不算失败
                    return False

                response.raise_for_status()

                # 确保目录存在
                filepath.parent.mkdir(parents=True, exist_ok=True)

                # 流式写入文件
                async with aiofiles.open(filepath, "wb") as f:
                    async for chunk in response.content.iter_chunked(8192):
                        await f.write(chunk)

                return True
        except Exception:
            # 失败直接返回 False，不重试（由 tenacity 控制重试）
            raise

    async def process_card(
        self,
        session: aiohttp.ClientSession,
        card_set: CardSet,
        number: int,
        lang: str,
        pbar: tqdm,
    ):
        """处理单张卡牌下载"""
        filepath = self.get_image_path(lang, card_set.set_code, number)

        # 检查文件是否已存在
        if filepath.exists():
            self.stats["skipped"] += 1
            pbar.update(1)
            return

        url = self.get_image_url(card_set.id, number, lang)

        async with self.semaphore:
            try:
                success = await self.download_image(session, url, filepath, pbar)
                if success:
                    self.stats["downloaded"] += 1
                else:
                    self.stats["failed"] += 1
                    self.failed_items.append((card_set.set_code, url))
            except Exception:
                self.stats["failed"] += 1
                self.failed_items.append((card_set.set_code, url))
            finally:
                pbar.update(1)

    async def process_set(
        self,
        session: aiohttp.ClientSession,
        card_set: CardSet,
        pbar: tqdm,
    ):
        """处理单个卡牌集合"""
        total_cards = card_set.set_n_cards + card_set.set_n_secrets

        tasks = []
        for lang in self.languages:
            for number in range(1, total_cards + 1):
                task = self.process_card(session, card_set, number, lang, pbar)
                tasks.append(task)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def run(self):
        """运行下载器"""
        print(f"开始下载 PTCGP 卡牌图片...")
        print(f"目标目录: {self.base_dir}")
        print(f"语言: {', '.join(self.languages)}")
        print(f"系列: {', '.join(self.series_list)}")
        print(f"并发数: {self.max_concurrency}")
        print()

        # 创建 aiohttp 会话，启用连接池和 HTTP/2
        connector = aiohttp.TCPConnector(
            limit=100,
            limit_per_host=30,
            enable_cleanup_closed=True,
            force_close=False,
        )

        timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=60)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        }

        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers=headers,
        ) as session:
            # 获取所有系列的集合
            all_sets: List[CardSet] = []
            for series in self.series_list:
                sets = await self.fetch_sets(session, series)
                all_sets.extend(sets)
                print(f"系列 {series}: 找到 {len(sets)} 个集合")

            if not all_sets:
                print("没有找到任何卡牌集合")
                return

            print(f"\n总共 {len(all_sets)} 个集合待处理")
            print()

            # 计算总任务数
            total_tasks = 0
            for card_set in all_sets:
                total_cards = card_set.set_n_cards + card_set.set_n_secrets
                total_tasks += total_cards * len(self.languages)

            self.stats["total"] = total_tasks
            print(f"预计需要处理 {total_tasks} 张图片")
            print()

            # 创建进度条
            with tqdm(total=total_tasks, desc="下载进度", unit="img") as pbar:
                # 处理每个集合
                tasks = []
                for card_set in all_sets:
                    task = self.process_set(session, card_set, pbar)
                    tasks.append(task)

                # 并发处理所有集合
                await asyncio.gather(*tasks, return_exceptions=True)

        # 输出统计
        print("\n" + "=" * 50)
        print("下载完成!")
        print(f"  成功下载: {self.stats['downloaded']}")
        print(f"  已存在跳过: {self.stats['skipped']}")
        print(f"  失败: {self.stats['failed']}")
        print(f"  总计: {self.stats['total']}")
        print("=" * 50)

        # 输出失败的 URL，按 set 分组
        if self.failed_items:
            print(f"\n失败的链接 ({len(self.failed_items)} 个):")

            # 按 set_code 分组
            from collections import defaultdict

            grouped = defaultdict(list)
            for set_code, url in self.failed_items:
                grouped[set_code].append(url)

            # 按 set_code 排序输出
            for set_code in sorted(grouped.keys()):
                print(f"\n  [{set_code}] ({len(grouped[set_code])} 个):")
                for url in grouped[set_code]:
                    print(f"    - {url}")


def main():
    parser = argparse.ArgumentParser(
        description="PTCGP 卡牌图片爬虫 - 高性能异步下载",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python fetch_cards.py
  python fetch_cards.py --series a,b --langs zh-TW,en-US
  python fetch_cards.py --concurrency 30 --max-retries 5
        """,
    )

    parser.add_argument(
        "--base-dir",
        type=str,
        default=".",
        help="基础目录路径 (默认: 当前目录)",
    )
    parser.add_argument(
        "--series",
        type=str,
        default="a,b",
        help="要下载的系列，逗号分隔 (默认: a,b)",
    )
    parser.add_argument(
        "--langs",
        type=str,
        default="zh-TW,en-US",
        help="要下载的语言，逗号分隔 (默认: zh-TW,en-US)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=20,
        help="并发下载数 (默认: 20)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="单文件最大重试次数 (默认: 3)",
    )

    args = parser.parse_args()

    # 解析参数
    base_dir = Path(args.base_dir).resolve()
    languages = [lang.strip() for lang in args.langs.split(",")]
    series_list = [s.strip() for s in args.series.split(",")]

    # 创建下载器并运行
    downloader = PTCGPDownloader(
        base_dir=base_dir,
        languages=languages,
        series_list=series_list,
        max_concurrency=args.concurrency,
        max_retries=args.max_retries,
    )

    try:
        asyncio.run(downloader.run())
    except KeyboardInterrupt:
        print("\n\n用户中断，正在退出...")
        sys.exit(1)
    except Exception as e:
        print(f"\n发生错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
