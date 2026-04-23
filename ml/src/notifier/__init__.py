"""
ベット候補レースの通知ファサード。

Phase 1: Discord Webhook 経由で通知。
Phase 2 以降で Gmail SMTP 等のチャンネルを追加予定。
"""
from __future__ import annotations

import logging
import os
from typing import Iterable

from .discord_notifier import send_bet_candidates_to_discord

logger = logging.getLogger(__name__)


def notify_bet_candidates(candidates: Iterable[dict]) -> None:
    """
    ベット候補レースをスマホ等へ通知する。

    現状は Discord Webhook のみ。環境変数 DISCORD_WEBHOOK_URL が未設定なら
    警告ログのみ残してスキップする（本体処理は止めない）。

    Parameters
    ----------
    candidates : Iterable[dict]
        最低限 combination, win_probability, expected_value を持つ dict の列。
        race_id, stadium_id, race_no, odds などが入っていれば表示に使う。
    """
    items = list(candidates)
    if not items:
        logger.info("notify_bet_candidates: no candidates, skipping")
        return

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if webhook_url:
        try:
            send_bet_candidates_to_discord(items, webhook_url=webhook_url)
        except Exception as exc:  # 通知失敗で本体処理を止めない
            logger.warning("Discord notification failed: %s", exc)
    else:
        logger.warning(
            "DISCORD_WEBHOOK_URL is not set; skipping Discord notification"
        )
