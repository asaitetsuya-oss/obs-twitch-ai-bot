"""
Twitch GPT自動返信Bot (Gemini版・会話履歴あり)
twitchioを使わずwebsockets + httpxで直接EventSub WebSocketに接続
依存: pip install websockets httpx google-genai
設定: bot_config.json のパスは下記 CONFIG_PATH を環境に合わせて変更してください
{
    "CLIENT_ID":      "...",
    "CLIENT_SECRET":  "...",
    "BOT_ID":         "...",
    "OWNER_ID":       "...",
    "BOT_TOKEN":      "...",
    "GEMINI_API_KEY": "..."
}
"""

import asyncio
import json
import random
import sys
import time
from collections import deque
from pathlib import Path

import httpx
import websockets
from google import genai


def safe_print(*args, **kwargs):
    """Geminiの返答にEM dashなど非cp932文字が含まれても落ちないprint"""
    text = " ".join(str(a) for a in args)
    try:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
    except UnicodeEncodeError:
        sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))
        sys.stdout.buffer.flush()

# ============================================================
# 設定読み込み
# ============================================================
# bot_config.json のパスを環境に合わせて変更してください
CONFIG_PATH = Path(r"D:/obs-script/bot_config.json")

_cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

# コード内のデフォルト値（bot_config.json で上書き可能）
_DEFAULTS = {
    "GEMINI_MODEL":          "gemini-2.5-flash",
    "COOLDOWN_SEC":          15,
    "USER_COOLDOWN_SEC":     60,
    "REPLY_PROB":            0.4,
    "STREAMER_REACT_PROB":   0.25,
    "STREAMER_COOLDOWN_SEC": 30,
    "HISTORY_SIZE":          30,
    "SUBTITLE_JSON":         r"D:/obs-script/subtitle_data.json",
    "GEMINI_RETRY_COUNT":    3,    # 503等でのリトライ回数
    "GEMINI_RETRY_WAIT":     2.0,  # リトライ初回待機秒（指数バックオフ）
    "SYSTEM_PROMPT": (
        "あなたは配信者のアシスタントBotです。\n"
        "視聴者のコメントに対して、短く（1〜2文）日本語で返してください。\n"
        "キャラクターや口調はここで自由に設定できます。\n"
        "絶対禁止：長文・箇条書き・AIっぽい返し"
    ),
    "STREAMER_REACT_PROMPT": (
        "あなたは配信者のアシスタントBotです。\n"
        "配信者の発言（字幕テキスト）を読んで、短く（1文）リアクションしてください。\n"
        "チャットに自然に流れる独り言のような感じで。\n"
        "絶対禁止：長文・@メンション・AIっぽい返し"
    ),
}

# JSONの値でデフォルトを上書き → CONFIG確定
CONFIG = {**_DEFAULTS, **_cfg}
CONFIG["SUBTITLE_JSON"] = Path(CONFIG["SUBTITLE_JSON"])

gemini_client = genai.Client(api_key=CONFIG["GEMINI_API_KEY"])
last_reply_time: float = 0.0
last_streamer_react_time: float = 0.0
user_last_reply: dict[str, float] = {}
chat_history: deque = deque(maxlen=CONFIG["HISTORY_SIZE"])
seen_message_ids: deque = deque(maxlen=200)

HEADERS = {
    "Authorization": f"Bearer {CONFIG['BOT_TOKEN']}",
    "Client-Id": CONFIG["CLIENT_ID"],
    "Content-Type": "application/json",
}


# ============================================================
# Gemini
# ============================================================
async def ask_gemini(prompt: str, system_prompt: str) -> str:
    history_text = "\n".join(chat_history) + "\n" if chat_history else ""
    full_prompt = (
        f"{system_prompt}\n\n"
        f"直近のチャット履歴:\n{history_text}"
        f"{prompt}"
    )
    retry_count = int(CONFIG.get("GEMINI_RETRY_COUNT", 3))
    retry_wait  = float(CONFIG.get("GEMINI_RETRY_WAIT", 2.0))
    last_exc: Exception | None = None
    for attempt in range(retry_count):
        try:
            response = await asyncio.to_thread(
                gemini_client.models.generate_content,
                model=CONFIG["GEMINI_MODEL"],
                contents=full_prompt,
            )
            return response.text.strip()
        except Exception as e:
            last_exc = e
            err_str = str(e)
            # 503 / 429 (過負荷・レート制限) のみリトライ
            if "503" in err_str or "429" in err_str or "UNAVAILABLE" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                wait = retry_wait * (2 ** attempt)
                safe_print(f"[Gemini] {e} — {wait:.1f}秒後にリトライ ({attempt + 1}/{retry_count})")
                await asyncio.sleep(wait)
            else:
                raise  # それ以外はリトライしない
    raise last_exc


# ============================================================
# チャットメッセージ送信
# ============================================================
async def send_chat(client: httpx.AsyncClient, message: str, reply_to_id: str | None = None) -> None:
    body: dict = {
        "broadcaster_id": CONFIG["OWNER_ID"],
        "sender_id":      CONFIG["BOT_ID"],
        "message":        message,
    }
    if reply_to_id:
        body["reply_parent_message_id"] = reply_to_id

    resp = await client.post(
        "https://api.twitch.tv/helix/chat/messages",
        json=body,
        headers=HEADERS,
    )
    safe_print(f"[Bot] 送信レスポンス: {resp.status_code} {resp.text[:200]}")
    if resp.status_code not in (200, 204):
        safe_print(f"[Bot] 送信失敗: {resp.status_code} {resp.text}")


# ============================================================
# EventSub WebSocket購読
# ============================================================
async def subscribe_chat(client: httpx.AsyncClient, session_id: str) -> None:
    body = {
        "type":    "channel.chat.message",
        "version": "1",
        "condition": {
            "broadcaster_user_id": CONFIG["OWNER_ID"],
            "user_id":             CONFIG["BOT_ID"],
        },
        "transport": {
            "method":     "websocket",
            "session_id": session_id,
        },
    }
    resp = await client.post(
        "https://api.twitch.tv/helix/eventsub/subscriptions",
        json=body,
        headers=HEADERS,
    )
    if resp.status_code == 202:
        safe_print("[Bot] チャット購読完了")
    else:
        safe_print(f"[Bot] 購読失敗: {resp.status_code} {resp.text}")


# ============================================================
# 視聴者コメント処理
# ============================================================
async def handle_viewer_message(client: httpx.AsyncClient, event: dict) -> None:
    global last_reply_time, last_streamer_react_time

    chatter_id   = event["chatter_user_id"]
    chatter_name = event["chatter_user_login"]
    text         = event["message"]["text"]
    message_id   = event["message_id"]
    now          = time.time()

    # 重複排除
    if message_id in seen_message_ids:
        return
    seen_message_ids.append(message_id)

    # ボット自身は無視
    if chatter_id == CONFIG["BOT_ID"]:
        return

    # コマンドは無視
    if text.startswith("!"):
        return

    # ── 配信者本人のコメント ──────────────────────────────────────────────────
    if chatter_id == CONFIG["OWNER_ID"]:
        chat_history.append(f"浅井: {text}")
        safe_print(f"[Bot] 浅井のチャット発言: {text}")

        if now - last_streamer_react_time < CONFIG["STREAMER_COOLDOWN_SEC"]:
            return
        if random.random() > CONFIG["STREAMER_REACT_PROB"]:
            safe_print(f"[Bot] スキップ（確率）: 浅井チャット")
            return

        try:
            prompt = f"浅井のチャット発言:\n{text}"
            reply = await ask_gemini(prompt, CONFIG["STREAMER_REACT_PROMPT"])
            await send_chat(client, reply, reply_to_id=message_id)
            chat_history.append(f"さてじ: {reply}")
            last_streamer_react_time = now
            last_reply_time = now
            safe_print(f"[Bot] 浅井チャット返信: {reply}")
        except Exception as e:
            safe_print(f"[Bot] エラー（浅井チャット）: {e}")
        return

    # ── 視聴者コメント ────────────────────────────────────────────────────────
    # 履歴に積む（返信しなくても文脈として残す）
    chat_history.append(f"{chatter_name}: {text}")

    # クールダウンチェック
    if now - last_reply_time < CONFIG["COOLDOWN_SEC"]:
        return
    if now - user_last_reply.get(chatter_name, 0) < CONFIG["USER_COOLDOWN_SEC"]:
        return

    # 確率間引き
    if random.random() > CONFIG["REPLY_PROB"]:
        safe_print(f"[Bot] スキップ（確率）: {chatter_name}: {text}")
        return

    safe_print(f"[Bot] 返信対象: {chatter_name}: {text}")

    try:
        prompt = f"新しいコメント:\n{chatter_name}: {text}"
        reply = await ask_gemini(prompt, CONFIG["SYSTEM_PROMPT"])
        # 視聴者へはメンション付きで返信
        await send_chat(client, reply, reply_to_id=message_id)
        chat_history.append(f"さてじ: {reply}")
        last_reply_time = now
        user_last_reply[chatter_name] = now
        safe_print(f"[Bot] 返信送信: {reply}")
    except Exception as e:
        safe_print(f"[Bot] エラー: {e}")


# ============================================================
# 字幕監視 → 配信者トーク反応
# ============================================================
async def subtitle_watcher(client: httpx.AsyncClient) -> None:
    """subtitle_whisper.py が書き出す subtitle_data.json を監視し、
    final=true の新しい発言を検知して確率でリアクションする"""
    global last_streamer_react_time, last_reply_time

    subtitle_path: Path = CONFIG["SUBTITLE_JSON"]
    last_updated: float = 0.0
    last_text: str = ""

    safe_print(f"[字幕監視] 開始: {subtitle_path}")

    while True:
        await asyncio.sleep(0.5)

        if not subtitle_path.exists():
            continue

        try:
            stat = subtitle_path.stat()
            if stat.st_mtime <= last_updated:
                continue

            data = json.loads(subtitle_path.read_text(encoding="utf-8"))
            last_updated = stat.st_mtime

            # final=true の確定発言のみ対象
            if not data.get("final", False):
                continue

            text = data.get("line", "").strip()
            if not text or text == last_text:
                continue

            last_text = text

            # 履歴に積む（返信しなくても文脈として残す）
            chat_history.append(f"浅井: {text}")
            safe_print(f"[字幕] 浅井の発言: {text}")

            now = time.time()

            # クールダウン・確率チェック
            if now - last_streamer_react_time < CONFIG["STREAMER_COOLDOWN_SEC"]:
                continue
            if random.random() > CONFIG["STREAMER_REACT_PROB"]:
                safe_print(f"[字幕] スキップ（確率）")
                continue

            safe_print(f"[字幕] リアクション対象: {text}")

            try:
                prompt = f"浅井の発言:\n{text}"
                reply = await ask_gemini(prompt, CONFIG["STREAMER_REACT_PROMPT"])
                # 配信者トークへはメンションなし・自然発言
                await send_chat(client, reply, reply_to_id=None)
                chat_history.append(f"さてじ: {reply}")
                last_streamer_react_time = now
                # 視聴者返信のクールダウンも兼用（連投防止）
                last_reply_time = now
                safe_print(f"[字幕] リアクション送信: {reply}")
            except Exception as e:
                safe_print(f"[字幕] リアクションエラー: {e}")

        except Exception as e:
            safe_print(f"[字幕監視] 読み込みエラー: {e}")


# ============================================================
# WebSocketメインループ
# ============================================================
async def main() -> None:
    async with httpx.AsyncClient() as http_client:
        # 字幕監視タスクをバックグラウンドで起動
        asyncio.create_task(subtitle_watcher(http_client))

        while True:
            try:
                async with websockets.connect("wss://eventsub.wss.twitch.tv/ws") as ws:
                    safe_print("[Bot] WebSocket接続完了")
                    async for raw in ws:
                        msg = json.loads(raw)
                        msg_type = msg.get("metadata", {}).get("message_type")

                        if msg_type == "session_welcome":
                            session_id = msg["payload"]["session"]["id"]
                            safe_print(f"[Bot] セッションID: {session_id}")
                            await subscribe_chat(http_client, session_id)

                        elif msg_type == "notification":
                            event = msg["payload"]["event"]
                            await handle_viewer_message(http_client, event)

                        elif msg_type == "session_keepalive":
                            pass

                        elif msg_type == "session_reconnect":
                            url = msg["payload"]["session"]["reconnect_url"]
                            safe_print(f"[Bot] 再接続: {url}")
                            break

            except Exception as e:
                safe_print(f"[Bot] 接続エラー: {e} - 5秒後に再接続")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())