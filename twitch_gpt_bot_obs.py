"""
D:/obs-script/twitch_gpt_bot_obs.py
OBSのスクリプトUIからbotプロセスを起動/停止するランチャー
"""

import obspython as obs
import subprocess
import json
from pathlib import Path

_DEFAULT_PYTHON_EXE      = r"C:\Users\YOUR_NAME\AppData\Local\Programs\Python\Python310\python.exe"
_DEFAULT_BOT_SCRIPT_PATH = r"D:\obs-script\twitch_gpt_bot.py"
_DEFAULT_CONFIG_JSON     = r"D:\obs-script\bot_config.json"

_proc = None
_system_prompt: str      = ""
_streamer_react_prompt: str = ""
_python_exe: str         = _DEFAULT_PYTHON_EXE
_bot_script_path: str    = _DEFAULT_BOT_SCRIPT_PATH
_config_json_path: str   = _DEFAULT_CONFIG_JSON


def _load_json() -> dict:
    try:
        return json.loads(Path(_config_json_path).read_text(encoding="utf-8"))
    except Exception as e:
        obs.script_log(obs.LOG_WARNING, f"[GptBotOBS] JSON読み込み失敗: {e}")
        return {}


def _save_json(data: dict) -> bool:
    try:
        Path(_config_json_path).write_text(
            json.dumps(data, ensure_ascii=False, indent=4),
            encoding="utf-8",
        )
        return True
    except Exception as e:
        obs.script_log(obs.LOG_WARNING, f"[GptBotOBS] JSON保存失敗: {e}")
        return False


def script_description():
    return (
        "<b>Twitch GPT自動返信Bot</b><br>"
        "ボタンでbotプロセスを起動/停止します。<br><br>"
        "<b>Pythonのパスは PowerShell で (Get-Command python).Source で確認できます。</b><br><br>"
        "<b>プロンプト編集後は「JSONに保存」→「Bot再起動」で反映されます。</b>"
    )


def script_properties():
    props = obs.obs_properties_create()

    # ── パス設定 ──────────────────────────────────────────────────────────────
    obs.obs_properties_add_text(props, "python_exe",      "Python実行ファイルのパス", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_text(props, "bot_script_path", "Bot本体スクリプトのパス", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_text(props, "config_json",     "bot_config.jsonのパス",   obs.OBS_TEXT_DEFAULT)

    # ── Bot 操作ボタン ────────────────────────────────────────────────────────
    obs.obs_properties_add_button(props, "btn_start",  "▶ Bot 起動", on_start)
    obs.obs_properties_add_button(props, "btn_stop",   "■ Bot 停止", on_stop)
    obs.obs_properties_add_button(props, "btn_status", "● 状態確認", on_status)

    # ── プロンプト編集 ────────────────────────────────────────────────────────
    obs.obs_properties_add_text(props, "system_prompt",         "システムプロンプト（視聴者コメント用）", obs.OBS_TEXT_MULTILINE)
    obs.obs_properties_add_text(props, "streamer_react_prompt", "ストリーマーリアクションプロンプト",    obs.OBS_TEXT_MULTILINE)
    obs.obs_properties_add_button(props, "btn_save_json", "💾 JSONに保存",      on_save_json)
    obs.obs_properties_add_button(props, "btn_reload",    "🔄 JSONから読み込み", on_reload_json)

    return props


def on_save_json(props, prop):
    data = _load_json()
    data["SYSTEM_PROMPT"]         = _system_prompt
    data["STREAMER_REACT_PROMPT"] = _streamer_react_prompt
    if _save_json(data):
        obs.script_log(obs.LOG_INFO, "[GptBotOBS] プロンプトをJSONに保存しました")
    return True


def on_reload_json(props, prop):
    global _system_prompt, _streamer_react_prompt
    data = _load_json()
    if "SYSTEM_PROMPT" in data:
        _system_prompt = data["SYSTEM_PROMPT"]
    if "STREAMER_REACT_PROMPT" in data:
        _streamer_react_prompt = data["STREAMER_REACT_PROMPT"]
    obs.script_log(obs.LOG_INFO, "[GptBotOBS] JSONからプロンプトを読み込みました")
    return True


def on_start(props, prop):
    global _proc
    if _proc and _proc.poll() is None:
        obs.script_log(obs.LOG_INFO, "[GptBotOBS] 既に起動中です")
        return True
    try:
        log_dir = Path(_bot_script_path).parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = open(log_dir / "gpt_bot.log", "a", encoding="utf-8")
        si = subprocess.STARTUPINFO()
        si.dwFlags     = subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        _proc = subprocess.Popen(
            [_python_exe, _bot_script_path],
            stdout=log_file,
            stderr=log_file,
            creationflags=0,
            startupinfo=si,
        )
        obs.script_log(obs.LOG_INFO, f"[GptBotOBS] 起動しました (PID: {_proc.pid})")
    except Exception as e:
        obs.script_log(obs.LOG_WARNING, f"[GptBotOBS] 起動失敗: {e}")
    return True


def on_stop(props, prop):
    global _proc
    if _proc and _proc.poll() is None:
        _proc.terminate()
        obs.script_log(obs.LOG_INFO, "[GptBotOBS] 停止しました")
    else:
        obs.script_log(obs.LOG_INFO, "[GptBotOBS] 起動していません")
    _proc = None
    return True


def on_status(props, prop):
    if _proc and _proc.poll() is None:
        obs.script_log(obs.LOG_INFO, f"[GptBotOBS] 動作中 (PID: {_proc.pid})")
    else:
        obs.script_log(obs.LOG_INFO, "[GptBotOBS] 停止中")
    return True


def script_defaults(settings):
    obs.obs_data_set_default_string(settings, "python_exe",      _DEFAULT_PYTHON_EXE)
    obs.obs_data_set_default_string(settings, "bot_script_path", _DEFAULT_BOT_SCRIPT_PATH)
    obs.obs_data_set_default_string(settings, "config_json",     _DEFAULT_CONFIG_JSON)


def script_update(settings):
    global _python_exe, _bot_script_path, _config_json_path
    global _system_prompt, _streamer_react_prompt

    v = obs.obs_data_get_string(settings, "python_exe")
    if v: _python_exe = v

    v = obs.obs_data_get_string(settings, "bot_script_path")
    if v: _bot_script_path = v

    v = obs.obs_data_get_string(settings, "config_json")
    if v: _config_json_path = v

    _system_prompt         = obs.obs_data_get_string(settings, "system_prompt")
    _streamer_react_prompt = obs.obs_data_get_string(settings, "streamer_react_prompt")


def script_load(settings):
    script_update(settings)
    on_reload_json(None, None)
    on_start(None, None)


def script_unload():
    on_stop(None, None)
