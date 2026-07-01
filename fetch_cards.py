#!/usr/bin/env python3
"""
PTCGP 卡牌图片爬虫
高性能异步下载 PokeOS 卡牌图片资源
"""

import argparse
import asyncio
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set, Tuple

import aiofiles
import aiohttp

# 黑名单：需要从备选源下载的卡牌 (set_code, number)
BLACKLIST: Set[Tuple[str, int]] = {
    ("A1a", 63),  # 主源缺失
    ("A1a", 80),  # 主源交换81
    ("A1a", 81),  # 主源交换80
    ("A2a", 75),  # 主源缺失
    ("A2a", 85),  # 主源错误
} | {("PROMO-A", i) for i in range(109, 118)}  # 主源缺失

# 备选源配置
FALLBACK_BASE_URL = "https://raw.githubusercontent.com/marcelpanse/tcg-pocket-collection-tracker/main/frontend/public/images"
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from tqdm.asyncio import tqdm


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
    FALLBACK_BASE_URL = "https://raw.githubusercontent.com/marcelpanse/tcg-pocket-collection-tracker/main/frontend/public/images"

    def __init__(
        self,
        base_dir: Path,
        languages: List[str],
        series_list: List[str],
        max_concurrency: int = 20,
        max_retries: int = 3,
        verbose: bool = False,
        expansions: List[str] | None = None,
    ):
        self.base_dir = base_dir
        self.languages = languages
        self.series_list = series_list
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries
        self.verbose = verbose
        # expansions: 按 expansion code 精确过滤（如 ["B3b","A1"]），不传则不过滤
        self.expansions = set(expansions) if expansions else None

        # 并发控制
        self.semaphore = asyncio.Semaphore(max_concurrency)

        # 统计（按语言分组）
        self.stats: Dict[str, Dict[str, int]] = {
            "downloaded": defaultdict(int),
            "downloaded_fallback": defaultdict(int),
            "converted_png": defaultdict(int),
            "convert_failed": defaultdict(int),
            "skipped": defaultdict(int),
            "failed": defaultdict(int),
        }
        self.stats_total = 0

        # 失败项列表，格式: (set_code, number, lang, detail)
        self.failed_items: List[Tuple[str, int, str, str]] = []

        # 缺失项列表（404），格式: (set_code, number, lang, url)
        self.missing_items: List[Tuple[str, int, str, str]] = []

        # 从备选源下载的列表，格式: (set_code, number, lang, url)
        self.fallback_items: List[Tuple[str, int, str, str]] = []

        # 转换成功的列表，格式: (set_code, number, lang)
        self.converted_items: List[Tuple[str, int, str]] = []

    async def fetch_sets(
        self, session: aiohttp.ClientSession, series: str
    ) -> List[CardSet]:
        """获取指定系列的卡牌集合列表"""
        url = f"{self.BASE_API_URL}?lang=pocket&group={series}"
        headers = {
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

    def get_image_path(
        self, lang: str, set_code: str, number: int, ext: str = "png"
    ) -> Path:
        """获取图片保存路径"""
        return (
            self.base_dir
            / "images"
            / lang
            / "cards-by-set"
            / set_code
            / f"{number}.{ext}"
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

    def get_fallback_url(self, set_code: str, number: int) -> str:
        """获取备选源图片 URL（英文 webp）"""
        # 备用源中 PROMO- 开头的都改为 P- 格式
        if set_code.upper().startswith("PROMO-"):
            set_code = "P-" + set_code[6:]
        return f"{self.FALLBACK_BASE_URL}/en-US/{set_code}-{number}.webp"

    def convert_webp_to_png(
        self,
        webp_path: Path,
        png_path: Path,
        set_code: str,
        number: int,
        lang: str,
        source_url: str,
    ) -> bool:
        """将 webp 转换为 png（仅在 png 缺失时调用）"""
        try:
            import importlib

            pil_image = importlib.import_module("PIL.Image")
        except Exception:
            self.stats["convert_failed"][lang] += 1
            if self.verbose:
                print(
                    f"[转换失败] {set_code} #{number} [{lang}] Pillow 不可用 | url: {source_url}"
                )
            else:
                print(f"[转换失败] {set_code} #{number} [{lang}] Pillow 不可用")
            return False

        try:
            png_path.parent.mkdir(parents=True, exist_ok=True)
            with pil_image.open(webp_path) as img:
                img.save(png_path, "PNG")

            self.stats["converted_png"][lang] += 1
            self.converted_items.append((set_code, number, lang))
            if self.verbose:
                print(
                    f"[转换成功] {set_code} #{number} [{lang}] webp -> png | url: {source_url}"
                )
            else:
                print(f"[转换成功] {set_code} #{number} [{lang}] webp -> png")
            return True
        except Exception as e:
            self.stats["convert_failed"][lang] += 1
            if self.verbose:
                print(
                    f"[转换失败] {set_code} #{number} [{lang}] webp -> png | url: {source_url} | 错误: {e}"
                )
            else:
                print(f"[转换失败] {set_code} #{number} [{lang}] webp -> png")
            return False

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
    ) -> tuple[bool, bool]:
        """下载单张图片

        Returns:
            (success, is_404):
            - success: 是否成功下载
            - is_404: 是否是404错误
        """
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                if response.status == 404:
                    # 图片不存在
                    return False, True

                response.raise_for_status()

                # 确保目录存在
                filepath.parent.mkdir(parents=True, exist_ok=True)

                # 流式写入文件
                async with aiofiles.open(filepath, "wb") as f:
                    async for chunk in response.content.iter_chunked(8192):
                        await f.write(chunk)

                return True, False
        except Exception:
            # 失败直接抛出，由 tenacity 控制重试
            raise

    async def download_from_fallback(
        self,
        session: aiohttp.ClientSession,
        set_code: str,
        number: int,
        lang: str,
        pbar: tqdm,
    ) -> bool:
        """从备选源下载图片（英文 webp）"""
        # 构建备选源 URL（英文）
        url = self.get_fallback_url(set_code, number)
        # 保存为 .webp 格式
        filepath = self.get_image_path(lang, set_code, number, ext="webp")
        png_path = self.get_image_path(lang, set_code, number, ext="png")

        # 本地已有 webp：跳过网络下载，仅在 png 缺失时尝试转换
        if filepath.exists():
            if not png_path.exists():
                self.convert_webp_to_png(
                    webp_path=filepath,
                    png_path=png_path,
                    set_code=set_code,
                    number=number,
                    lang=lang,
                    source_url=url,
                )
            return True

        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                if response.status == 404:
                    return False

                response.raise_for_status()

                # 确保目录存在
                filepath.parent.mkdir(parents=True, exist_ok=True)

                # 流式写入文件
                async with aiofiles.open(filepath, "wb") as f:
                    async for chunk in response.content.iter_chunked(8192):
                        await f.write(chunk)

                self.stats["downloaded_fallback"][lang] += 1
                self.fallback_items.append((set_code, number, lang, url))

                # 简单策略：若 png 不存在，则尝试将已下载的 webp 转换为 png
                if not png_path.exists():
                    self.convert_webp_to_png(
                        webp_path=filepath,
                        png_path=png_path,
                        set_code=set_code,
                        number=number,
                        lang=lang,
                        source_url=url,
                    )

                return True
        except Exception:
            return False
        finally:
            pbar.update(1)

    async def process_card(
        self,
        session: aiohttp.ClientSession,
        card_set: CardSet,
        number: int,
        lang: str,
        pbar: tqdm,
        is_probe_mode: bool = False,
    ) -> tuple[bool, bool]:
        """处理单张卡牌下载

        Args:
            is_probe_mode: 是否为探测模式（探测模式的 404 是正常的，不记录为缺失）

        Returns:
            (success, is_404):
            - success: 是否成功下载
            - is_404: 是否是404错误
        """
        # 检查是否在黑名单中
        is_blacklisted = (card_set.set_code, number) in BLACKLIST

        if is_blacklisted:
            # 黑名单卡牌优先使用本地 fallback 资源，避免重复网络下载
            webp_path = self.get_image_path(lang, card_set.set_code, number, ext="webp")
            png_path = self.get_image_path(lang, card_set.set_code, number, ext="png")

            # 本地已有 webp：不再请求备用源；若缺 png 则尝试转换
            if webp_path.exists():
                if not png_path.exists():
                    self.convert_webp_to_png(
                        webp_path=webp_path,
                        png_path=png_path,
                        set_code=card_set.set_code,
                        number=number,
                        lang=lang,
                        source_url=self.get_fallback_url(card_set.set_code, number),
                    )
                self.stats["skipped"][lang] += 1
                pbar.update(1)
                return True, False

            # 本地没有 webp，说明需要首次从备用源拉取；先删除旧 png（若有）避免保留错误版本
            if png_path.exists():
                try:
                    png_path.unlink()
                    print(f"  [黑名单] 删除旧文件: {png_path}")
                except Exception as e:
                    print(f"  [警告] 无法删除旧文件 {png_path}: {e}")

            async with self.semaphore:
                success = await self.download_from_fallback(
                    session, card_set.set_code, number, lang, pbar
                )
            if not success:
                self.stats["failed"][lang] += 1
                self.failed_items.append(
                    (
                        card_set.set_code,
                        number,
                        lang,
                        self.get_fallback_url(card_set.set_code, number),
                    )
                )
            return success, False

        # 正常流程：先尝试主源
        filepath = self.get_image_path(lang, card_set.set_code, number)

        # 检查文件是否已存在
        if filepath.exists():
            self.stats["skipped"][lang] += 1
            pbar.update(1)
            return True, False

        url = self.get_image_url(card_set.id, number, lang)

        async with self.semaphore:
            try:
                success, is_404 = await self.download_image(
                    session, url, filepath, pbar
                )
                if success:
                    # 主源下载成功
                    self.stats["downloaded"][lang] += 1
                    pbar.update(1)
                    return True, False
                elif is_404:
                    # 主源 404
                    if is_probe_mode:
                        # 探测模式：404 是正常的探测结果，不尝试备用源，不记录缺失
                        pbar.update(1)
                        return False, True
                    else:
                        # 批量模式：尝试备选源兜底
                        fallback_success = await self.download_from_fallback(
                            session, card_set.set_code, number, lang, pbar
                        )
                        if not fallback_success:
                            # 备选源也失败，记录为缺失
                            self.missing_items.append(
                                (card_set.set_code, number, lang, url)
                            )
                        return fallback_success, False
                else:
                    # 其他失败
                    self.stats["failed"][lang] += 1
                    self.failed_items.append((card_set.set_code, number, lang, url))
                    pbar.update(1)
                    return False, False
            except Exception:
                self.stats["failed"][lang] += 1
                self.failed_items.append((card_set.set_code, number, lang, url))
                pbar.update(1)
                return False, False

    async def probe_cards(
        self,
        session: aiohttp.ClientSession,
        card_set: CardSet,
        lang: str,
        pbar: tqdm,
        max_number: int = 200,
    ):
        """探测模式：从1开始递增获取，遇到404停止或达到上限"""
        consecutive_404 = 0
        max_consecutive_404 = 3  # 连续3个404停止

        for number in range(1, max_number + 1):
            success, is_404 = await self.process_card(
                session, card_set, number, lang, pbar, is_probe_mode=True
            )

            if is_404:
                consecutive_404 += 1
                if consecutive_404 >= max_consecutive_404:
                    # 连续404达到阈值，停止探测
                    break
            else:
                # 重置404计数
                consecutive_404 = 0

            if number >= max_number:
                # 达到上限
                break

    async def process_set(
        self,
        session: aiohttp.ClientSession,
        card_set: CardSet,
        pbar: tqdm,
    ):
        """处理单个卡牌集合"""
        total_cards = card_set.set_n_cards + card_set.set_n_secrets

        if total_cards == 0:
            mode_desc = "探测模式"
            expected_desc = f"每语言最多 200 张，语言数 {len(self.languages)}"
        else:
            mode_desc = "批量模式"
            expected_desc = (
                f"每语言 {total_cards} 张，共 {total_cards * len(self.languages)} 张"
            )

        print(
            f"[开始] 系列 {card_set.series} / 子包 {card_set.set_code} | {mode_desc} | {expected_desc}"
        )

        if total_cards == 0:
            # 使用探测模式
            tasks = []
            for lang in self.languages:
                task = self.probe_cards(session, card_set, lang, pbar)
                tasks.append(task)

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        else:
            # 使用批量模式
            tasks = []
            for lang in self.languages:
                for number in range(1, total_cards + 1):
                    task = self.process_card(session, card_set, number, lang, pbar)
                    tasks.append(task)

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        print(f"[完成] 系列 {card_set.series} / 子包 {card_set.set_code}")

    async def run(self):
        """运行下载器"""
        print("开始下载 PTCGP 卡牌图片...")
        print(f"目标目录: {self.base_dir}")
        print(f"语言: {', '.join(self.languages)}")
        print(f"系列: {', '.join(self.series_list)}")
        print(f"并发数: {self.max_concurrency}")
        print(f"详细日志: {'开启' if self.verbose else '关闭'}")
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

                if sets:
                    print(f"系列 {series} 子包列表:")
                    for s in sorted(sets, key=lambda x: x.set_code):
                        total_cards = s.set_n_cards + s.set_n_secrets
                        if total_cards == 0:
                            print(f"  - {s.set_code}: 探测模式（API 返回 0）")
                        else:
                            print(
                                f"  - {s.set_code}: {s.set_n_cards}+{s.set_n_secrets}={total_cards} 张"
                            )

            if not all_sets:
                print("没有找到任何卡牌集合")
                return

            # 按 expansion code 精确过滤
            if self.expansions:
                all_sets = [s for s in all_sets if s.set_code in self.expansions]
                print(f"按 expansion code 过滤后: {len(all_sets)} 个集合 {[s.set_code for s in all_sets]}")
                if not all_sets:
                    print("过滤后无匹配集合")
                    return

            print(f"\n总共 {len(all_sets)} 个集合待处理")
            print()

            # 计算总任务数
            # 对于探测模式（卡牌数为0的集合），预估每个语言50张
            PROBE_ESTIMATE = 50
            total_tasks = 0
            for card_set in all_sets:
                total_cards = card_set.set_n_cards + card_set.set_n_secrets
                if total_cards == 0:
                    # 探测模式：使用预估数量
                    total_cards = PROBE_ESTIMATE
                total_tasks += total_cards * len(self.languages)

            self.stats_total = total_tasks
            print(f"预计需要处理 {total_tasks} 张图片（探测模式按预估计算）")
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
        print("\n" + "=" * 60)
        print("下载完成!")
        print()

        # 按语言汇总
        for lang in self.languages:
            d = self.stats["downloaded"][lang]
            f = self.stats["downloaded_fallback"][lang]
            c = self.stats["converted_png"][lang]
            cf = self.stats["convert_failed"][lang]
            s = self.stats["skipped"][lang]
            fa = self.stats["failed"][lang]
            total = d + f + c + cf + s + fa
            print(f"  [{lang}] 共 {total} 张")
            print(f"    主源下载: {d}")
            print(f"    备选源下载: {f}")
            print(f"    webp->png 转换: {c} (失败 {cf})")
            print(f"    已存在跳过: {s}")
            if fa > 0:
                print(f"    失败: {fa}")
            print()

        # 汇总
        total_downloaded = sum(self.stats["downloaded"].values())
        total_fallback = sum(self.stats["downloaded_fallback"].values())
        total_converted = sum(self.stats["converted_png"].values())
        total_convert_failed = sum(self.stats["convert_failed"].values())
        total_skipped = sum(self.stats["skipped"].values())
        total_failed = sum(self.stats["failed"].values())
        print("  " + "-" * 30)
        print(f"  总计: {total_downloaded + total_fallback + total_converted + total_convert_failed + total_skipped + total_failed}")
        print(f"    主源下载: {total_downloaded}")
        print(f"    备选源下载: {total_fallback}")
        print(f"    webp->png 转换: {total_converted} (失败 {total_convert_failed})")
        print(f"    已存在跳过: {total_skipped}")
        if total_failed > 0:
            print(f"    失败: {total_failed}")
        print("=" * 60)

        # 输出转换明细
        if self.converted_items:
            print(f"\n转换明细 ({len(self.converted_items)} 个):")
            # 按语言分组
            by_lang_conv: Dict[str, Dict[str, List[int]]] = defaultdict(lambda: defaultdict(list))
            for set_code, number, lang in self.converted_items:
                by_lang_conv[lang][set_code].append(number)

            for lang in self.languages:
                if lang not in by_lang_conv:
                    continue
                print(f"\n  [{lang}]")
                for set_code in sorted(by_lang_conv[lang].keys()):
                    numbers = sorted(by_lang_conv[lang][set_code])
                    cards = ", ".join(f"#{n}" for n in numbers)
                    print(f"    {set_code}: {cards}")

        # 输出缺失项（主源 404 且备选源也失败）
        if self.missing_items:
            print(f"\n缺失项 (404) ({len(self.missing_items)} 个):")
            # 按语言分组
            by_lang: Dict[str, Dict[str, List[int]]] = defaultdict(lambda: defaultdict(list))
            for set_code, number, lang, url in self.missing_items:
                by_lang[lang][set_code].append(number)

            for lang in self.languages:
                if lang not in by_lang:
                    continue
                print(f"\n  [{lang}]")
                for set_code in sorted(by_lang[lang].keys()):
                    numbers = sorted(by_lang[lang][set_code])
                    cards = ", ".join(f"#{n}" for n in numbers)
                    print(f"    {set_code}: {cards}")

        # 输出备选源下载成功项
        if self.fallback_items:
            print(f"\n备选源下载成功 ({len(self.fallback_items)} 个):")
            # 按语言分组
            by_lang_fb: Dict[str, Dict[str, List[int]]] = defaultdict(lambda: defaultdict(list))
            for set_code, number, lang, url in self.fallback_items:
                by_lang_fb[lang][set_code].append(number)

            for lang in self.languages:
                if lang not in by_lang_fb:
                    continue
                print(f"\n  [{lang}]")
                for set_code in sorted(by_lang_fb[lang].keys()):
                    numbers = sorted(by_lang_fb[lang][set_code])
                    cards = ", ".join(f"#{n}" for n in numbers)
                    print(f"    {set_code}: {cards}")

        # 输出失败项
        if self.failed_items:
            print(f"\n失败项 ({len(self.failed_items)} 个):")
            # 按语言分组
            by_lang_fail: Dict[str, Dict[str, List[Tuple[int, str]]]] = defaultdict(
                lambda: defaultdict(list)
            )
            for set_code, number, lang, detail in self.failed_items:
                by_lang_fail[lang][set_code].append((number, detail))

            for lang in self.languages:
                if lang not in by_lang_fail:
                    continue
                print(f"\n  [{lang}]")
                for set_code in sorted(by_lang_fail[lang].keys()):
                    items = by_lang_fail[lang][set_code]
                    if self.verbose:
                        print(f"    {set_code}:")
                        for number, detail in items:
                            print(f"      #{number}: {detail}")
                    else:
                        cards = ", ".join(f"#{n}" for n, _ in items)
                        print(f"    {set_code}: {cards}")


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
        help="要下载的系列大组，逗号分隔 (默认: a,b)",
    )
    parser.add_argument(
        "--expansions",
        type=str,
        default=None,
        help="按 expansion code 精确过滤，逗号分隔（如 B3b,A1）；不传则下载 series 全部",
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
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="显示详细日志（包括具体 URL）",
    )

    args = parser.parse_args()

    # 解析参数
    base_dir = Path(args.base_dir).resolve()
    languages = [lang.strip() for lang in args.langs.split(",")]
    series_list = [s.strip() for s in args.series.split(",")]
    expansions = (
        [e.strip() for e in args.expansions.split(",") if e.strip()]
        if args.expansions
        else None
    )

    # 创建下载器并运行
    downloader = PTCGPDownloader(
        base_dir=base_dir,
        languages=languages,
        series_list=series_list,
        max_concurrency=args.concurrency,
        max_retries=args.max_retries,
        verbose=args.verbose,
        expansions=expansions,
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
