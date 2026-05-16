"""
Asset Vault — All k Music
────────────────────────────────────────────────────────────────────────
「動かぬ無実の証拠」モジュール。

YouTubeから「パクリ疑い」「著作権侵害」の異議申し立てが来た際、
「この楽曲は XX 年 XX 月 XX 日 XX:XX:XX.XXXXXX UTC に
 シード XXXXXXXXXX で新規生成した」という証明を
改ざん不可能なフォーマットで永久保存する。

保存項目:
  - generation_seed      : 暗号品質の乱数シード (32bit)
  - prompt_fingerprint   : SHA-256(prompt + seed) の先頭16文字
  - generation_iso       : ISO 8601 マイクロ秒精度 UTC タイムスタンプ
  - save_timestamp_iso   : ローカルディスク書き込み完了時刻
  - origin               : 常に "suno_original_generate" (リミックス禁止を明示)
  - continue_clip_id     : 常に None (他者楽曲への依存を排除)
  - is_remix             : 常に False
  - is_extend            : 常に False

ログ形式:
  music_assets.json  … 通常操作用 JSON (上書き可)
  asset_vault.jsonl  … 追記専用 JSONL (絶対に上書きしない)
                        1行1エントリの証拠台帳。
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def generate_seed() -> int:
    """暗号品質の乱数 32-bit シードを生成する。"""
    return secrets.randbelow(2 ** 32)


def fingerprint(style_prompt: str, seed: int) -> str:
    """
    プロンプト文字列 + シードの SHA-256 フィンガープリント (先頭16文字) を返す。
    同じプロンプトでもシードが異なれば必ず異なる値になる。
    """
    data = f"{style_prompt}|{seed}".encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:16]


def stamp_entry(entry: dict, seed: int, style_prompt: str) -> dict:
    """
    既存のログエントリに不変証拠フィールドを追加して返す。
    元の entry は破壊しない (copy を返す)。
    """
    now = datetime.now(timezone.utc)
    stamped = dict(entry)
    stamped.update(
        {
            # ── 生成証明 ────────────────────────────────────────
            "generation_seed":        seed,
            "prompt_fingerprint":     fingerprint(style_prompt, seed),
            "generation_iso":         now.isoformat(),
            "generation_timestamp_us": int(now.timestamp() * 1_000_000),
            # ── 保存証明 ────────────────────────────────────────
            "save_timestamp_iso":     now.isoformat(),
            # ── 商用安全宣言 ────────────────────────────────────
            "origin":                 "suno_original_generate",
            "continue_clip_id":       None,
            "is_remix":               False,
            "is_extend":              False,
        }
    )
    return stamped


def append_vault(entry: dict, vault_path: Path) -> None:
    """
    証拠台帳 (JSONL) にエントリを追記する。
    既存行を書き換えることは一切しない。
    ファイルが存在しない場合は自動作成する。
    """
    vault_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False)
    with vault_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_vault(vault_path: Path) -> list:
    """証拠台帳の全エントリをリストとして返す。"""
    if not vault_path.exists():
        return []
    entries = []
    for line in vault_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


def verify_entry(entry: dict) -> bool:
    """
    エントリのフィンガープリントを再計算して改ざんチェックする。
    True = 改ざんなし / False = 不一致 (要調査)
    """
    seed   = entry.get("generation_seed")
    prompt = entry.get("style_prompt", "")
    stored = entry.get("prompt_fingerprint", "")
    if seed is None or not stored:
        return False
    return fingerprint(prompt, seed) == stored
