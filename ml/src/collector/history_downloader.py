"""
boatrace.jp 公式サイトから歴史データ（2002年〜）を取得する
LZH形式 → CSVを展開してパース
"""
import io
import os
from pathlib import Path
from typing import Iterator
import requests


HISTORY_BASE_URL = "https://www.boatrace.jp/owpc/pc/race/index"
DATA_DIR = Path(__file__).parents[3] / "data" / "history"


def download_year_data(year: int) -> Path:
    """指定年の全データをダウンロードして保存"""
    # TODO: 公式サイトのLZHファイルURL体系に合わせて実装
    raise NotImplementedError


def parse_result_csv(filepath: Path) -> Iterator[dict]:
    """着順CSVをパースしてレコードを yield する"""
    raise NotImplementedError
