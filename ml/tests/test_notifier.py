"""
Phase 1 通知モジュールのユニットテスト。

- 外部通信は一切行わない（urlopen をモック）
- pandas / LightGBM 等の重い依存は不要
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from notifier import notify_bet_candidates  # noqa: E402
from notifier.discord_notifier import (  # noqa: E402
    MAX_CANDIDATES_PER_MESSAGE,
    _build_embed,
    _chunked,
    send_bet_candidates_to_discord,
)
from notifier.formatter import (  # noqa: E402
    format_candidate_line,
    format_candidates_text,
    format_stadium,
)


def _sample_candidate(i: int = 1) -> dict:
    return {
        "race_id": f"2026042301{i:02d}",
        "stadium_id": 1,
        "race_no": 12,
        "combination": "1-2-3",
        "win_probability": 0.085,
        "expected_value": 2.30,
        "odds": 27.1,
    }


class FormatterTests(unittest.TestCase):
    def test_format_stadium_known(self):
        self.assertEqual(format_stadium(1), "桐生")
        self.assertEqual(format_stadium(11), "びわこ")
        self.assertEqual(format_stadium(24), "大村")

    def test_format_stadium_unknown_or_missing(self):
        self.assertEqual(format_stadium(None), "?")
        self.assertEqual(format_stadium(99), "場99")

    def test_format_candidate_line_typical(self):
        line = format_candidate_line(_sample_candidate())
        self.assertIn("桐生", line)
        self.assertIn("12R", line)
        self.assertIn("1-2-3", line)
        self.assertIn("prob=8.5%", line)
        self.assertIn("EV=2.30", line)
        self.assertIn("odds=27.1x", line)

    def test_format_candidate_line_missing_fields_safe(self):
        line = format_candidate_line({"combination": "3-4-5"})
        # 欠損があっても例外にならず "?" でフォールバックする
        self.assertIn("3-4-5", line)
        self.assertIn("?", line)

    def test_format_candidates_text_header(self):
        text = format_candidates_text([_sample_candidate(1), _sample_candidate(2)])
        self.assertTrue(text.startswith("2件のベット候補"))
        self.assertEqual(len(text.splitlines()), 3)


class DiscordNotifierTests(unittest.TestCase):
    def test_chunked_splits_correctly(self):
        items = [_sample_candidate(i) for i in range(25)]
        chunks = _chunked(items, 10)
        self.assertEqual([len(c) for c in chunks], [10, 10, 5])

    def test_build_embed_shape(self):
        chunk = [_sample_candidate(1), _sample_candidate(2)]
        embed = _build_embed(chunk, index=0, total_chunks=1)
        self.assertIn("title", embed)
        self.assertIn("description", embed)
        self.assertIn("2件", embed["title"])
        self.assertNotIn("/", embed["title"])  # total_chunks=1 のとき "(1/1)" が付かない

    def test_build_embed_pagination_suffix(self):
        embed = _build_embed([_sample_candidate()], index=1, total_chunks=3)
        self.assertIn("(2/3)", embed["title"])

    def test_send_uses_urlopen_with_json_payload(self):
        items = [_sample_candidate(i) for i in range(3)]

        captured = {}

        class _FakeResp:
            status = 204

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def _fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode("utf-8"))
            captured["method"] = req.get_method()
            captured["content_type"] = req.get_header("Content-type")
            return _FakeResp()

        with patch("notifier.discord_notifier._urlrequest.urlopen", side_effect=_fake_urlopen):
            sent = send_bet_candidates_to_discord(
                items, webhook_url="https://discord.example/webhook/abc"
            )

        self.assertEqual(sent, 1)
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["content_type"], "application/json")
        self.assertEqual(captured["url"], "https://discord.example/webhook/abc")
        self.assertIn("embeds", captured["body"])
        self.assertEqual(len(captured["body"]["embeds"]), 1)
        self.assertIn("description", captured["body"]["embeds"][0])

    def test_send_splits_messages_above_chunk_size(self):
        items = [_sample_candidate(i) for i in range(MAX_CANDIDATES_PER_MESSAGE + 5)]
        call_count = {"n": 0}

        class _FakeResp:
            status = 204

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def _fake_urlopen(req, timeout=None):
            call_count["n"] += 1
            return _FakeResp()

        with patch("notifier.discord_notifier._urlrequest.urlopen", side_effect=_fake_urlopen):
            sent = send_bet_candidates_to_discord(
                items, webhook_url="https://discord.example/webhook/abc"
            )

        self.assertEqual(sent, 2)
        self.assertEqual(call_count["n"], 2)

    def test_send_empty_candidates_noop(self):
        with patch("notifier.discord_notifier._urlrequest.urlopen") as mocked:
            sent = send_bet_candidates_to_discord(
                [], webhook_url="https://discord.example/webhook/abc"
            )
        self.assertEqual(sent, 0)
        mocked.assert_not_called()


class FacadeTests(unittest.TestCase):
    def test_notify_skips_when_webhook_env_missing(self):
        items = [_sample_candidate()]
        with patch.dict("os.environ", {}, clear=False):
            # 確実に unset
            import os
            os.environ.pop("DISCORD_WEBHOOK_URL", None)
            with patch("notifier.discord_notifier._urlrequest.urlopen") as mocked:
                notify_bet_candidates(items)
            mocked.assert_not_called()

    def test_notify_skips_when_no_candidates(self):
        with patch.dict("os.environ", {"DISCORD_WEBHOOK_URL": "https://x/y"}, clear=False):
            with patch("notifier.discord_notifier._urlrequest.urlopen") as mocked:
                notify_bet_candidates([])
            mocked.assert_not_called()

    def test_notify_sends_when_webhook_set(self):
        items = [_sample_candidate()]

        class _FakeResp:
            status = 204

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        calls = []

        def _fake_urlopen(req, timeout=None):
            calls.append(req.full_url)
            return _FakeResp()

        with patch.dict(
            "os.environ",
            {"DISCORD_WEBHOOK_URL": "https://discord.example/webhook/abc"},
            clear=False,
        ):
            with patch(
                "notifier.discord_notifier._urlrequest.urlopen",
                side_effect=_fake_urlopen,
            ):
                notify_bet_candidates(items)

        self.assertEqual(calls, ["https://discord.example/webhook/abc"])

    def test_notify_swallows_transport_errors(self):
        items = [_sample_candidate()]

        def _raise(req, timeout=None):
            raise OSError("boom")

        with patch.dict(
            "os.environ",
            {"DISCORD_WEBHOOK_URL": "https://discord.example/webhook/abc"},
            clear=False,
        ):
            with patch(
                "notifier.discord_notifier._urlrequest.urlopen",
                side_effect=_raise,
            ):
                # 本体処理を止めないことを期待（例外が漏れなければ OK）
                notify_bet_candidates(items)


if __name__ == "__main__":
    unittest.main()
