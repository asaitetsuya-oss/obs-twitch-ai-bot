# obs-twitch-ai-bot

OBSと連携するTwitch AI自動返信Botです。

視聴者のコメントにAIが返信し、配信者の発言にもリアクションします。**キャラクター設定はプロンプトを書き換えるだけ。** 自分だけのBotを作ってください。

---

## 必要なもの

- Python 3.10以上
- OBS Studio
- Gemini APIキー（[Google AI Studio](https://aistudio.google.com/) で無料取得）
- Twitch Developerアカウント

---

## セットアップ

### 1. ライブラリのインストール

```powershell
pip install websockets httpx google-genai
```

### 2. Twitchアプリの登録

[Twitch Developer Console](https://dev.twitch.tv/console) でアプリを新規作成します。

- OAuth Redirect URLs: `http://localhost`
- Category: `Chat Bot`

作成後、**Client ID** と **Client Secret** を控えます。

### 3. BotアカウントのユーザートークンとIDを取得

Bot用のTwitchアカウントを用意します（メインアカウントとは別推奨）。

**ユーザートークンの取得：**
ブラウザで以下のURLにアクセスしてBotアカウントでログインします。`YOUR_CLIENT_ID` は手順2で取得したものに置き換えてください。

```
https://id.twitch.tv/oauth2/authorize?response_type=token&client_id=YOUR_CLIENT_ID&redirect_uri=http://localhost&scope=user:write:chat
```

リダイレクト後のURLに含まれる `access_token=` 以降の文字列がトークンです。

**ユーザーIDの取得：**
[StreamWeasels](https://www.streamweasels.com/tools/convert-twitch-username-to-user-id/) でアカウント名から数字のIDに変換できます。

### 4. bot_config.json を作成

以下の内容で `bot_config.json` を作成します。

```json
{
    "CLIENT_ID":      "TwitchアプリのClient ID",
    "CLIENT_SECRET":  "TwitchアプリのClient Secret",
    "BOT_ID":         "BotアカウントのユーザーID（数字）",
    "OWNER_ID":       "配信者アカウントのユーザーID（数字）",
    "BOT_TOKEN":      "手順3で取得したアクセストークン",
    "GEMINI_API_KEY": "GeminiのAPIキー",
    "SYSTEM_PROMPT":        "ここにBotのキャラクター設定を書く",
    "STREAMER_REACT_PROMPT": "ここに配信者発言へのリアクション設定を書く"
}
```

### 5. OBSにスクリプトを登録

OBS → ツール → スクリプト → `+` → `twitch_gpt_bot_obs.py` を追加します。

スクリプトUIの各フィールドに入力します。

| フィールド | 内容 |
|---|---|
| Python実行ファイルのパス | PowerShell で `(Get-Command python).Source` を実行すると確認できます |
| Bot本体スクリプトのパス | `twitch_gpt_bot.py` を置いた場所 |
| bot_config.jsonのパス | `bot_config.json` を置いた場所 |

入力後「▶ Bot 起動」で起動します。

---

## キャラクター設定

`SYSTEM_PROMPT` にBotの名前・口調・知識範囲を書くだけで自分だけのBotになります。

**コツ：**
- 「1〜2文で返す」と書くとチャットに馴染む
- 「AIっぽい返し禁止」を入れると自然な発言になりやすい

OBSのスクリプトUI上でも編集・保存できます（「💾 JSONに保存」→「■ Bot 停止」→「▶ Bot 起動」で反映）。

---

## パラメータ

`bot_config.json` に追記することで挙動を調整できます。

| キー | デフォルト | 説明 |
|---|---|---|
| `COOLDOWN_SEC` | 15 | 返信間隔（秒） |
| `USER_COOLDOWN_SEC` | 60 | 同一ユーザーへの返信間隔（秒） |
| `REPLY_PROB` | 0.4 | 視聴者コメントへの返信確率（0〜1） |
| `STREAMER_REACT_PROB` | 0.25 | 配信者発言へのリアクション確率 |
| `STREAMER_COOLDOWN_SEC` | 30 | 配信者発言へのリアクション間隔（秒） |
| `HISTORY_SIZE` | 30 | 保持するチャット履歴の件数 |
| `GEMINI_MODEL` | gemini-2.5-flash | 使用するGeminiモデル |

---

## 字幕スクリプトとの連携

faster-whisper等のリアルタイム字幕スクリプトと連携すると、配信者の音声をBotが読んでリアクションします。字幕スクリプトが以下の形式でJSONを書き出す場合に動作します。

```json
{"line": "発言テキスト", "final": true}
```

JSONのパスは `SUBTITLE_JSON` で指定できます（デフォルト: `D:/obs-script/subtitle_data.json`）。
