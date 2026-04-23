"""
Discord Webhook 経由で通知を送るモジュール。

- Webhook URL は環境変数 DISCORD_WEBHOOK_URL から取得（ファサード側で渡す）
- 1 メッセージに最大 MAX_CANDIDATES_PER_MESSAGE 件を埋め込み、rate limit を避ける
- Discord の Embed 形式で会場・R 番号・組番・確率・EV・オッズを表示
- ネットワーク失敗時は例外を投げる（呼び出し側でログ化）
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable
from urllib import request as _urlrequest
from urllib.error import HTTPError, URLError

from .formatter import format_candidate_line

logger = logging.getLogger(__name__)

# Discord の embed fields 上限は 25。余裕を見て 20 件ごとに分割する。
MAX_CANDIDATES_PER_MESSAGE = 20
# 1 embed 内の content 文字数上限は 4096。1 件 80 文字想定で 20 件 = 1600 文字。
EMBED_COLOR_ALERT = 0x2ECC71  # green

JST = timezone(timedelta(hours=9))


def _chunked(items: list[dict], size: int) -> list[list[dict]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _build_embed(chunk: list[dict], index: int, total_chunks: int) -> dict:
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    title = f"ベット候補 {len(chunk)}件"
    if total_chunks > 1:
        title += f" ({index + 1}/{total_chunks})"

    description = "\n".join(format_candidate_line(c) for c in chunk)
    return {
        "title": title,
        "description": description,
        "color": EMBED_COLOR_ALERT,
        "footer": {"text": f"boatrace-bot · {now} JST"},
    }


def _post_webhook(webhook_url: str, payload: dict, timeout: float = 10.0) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = _urlrequest.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _urlrequest.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            if status >= 300:
                raise RuntimeError(f"Discord webhook returned status {status}")
    except HTTPError as exc:
        raise RuntimeError(f"Discord webhook HTTP error: {exc.code} {exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"Discord webhook network error: {exc.reason}") from exc


def send_bet_candidates_to_discord(
    candidates: Iterable[dict],
    webhook_url: str,
    *,
    chunk_size: int = MAX_CANDIDATES_PER_MESSAGE,
) -> int:
    """
    ベット候補を Discord に送信する。

    Returns
    -------
    int : 送信したメッセージ数（分割送信する場合があるため）
    """
    items = list(candidates)
    if not items:
        return 0

    chunks = _chunked(items, chunk_size)
    for idx, chunk in enumerate(chunks):
        embed = _build_embed(chunk, idx, len(chunks))
        payload = {"embeds": [embed]}
        _post_webhook(webhook_url, payload)
        logger.info(
            "Discord notification sent (%d/%d, %d candidates)",
            idx + 1, len(chunks), len(chunk),
        )

    return len(chunks)
