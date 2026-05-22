#!/usr/bin/env python3
"""
Suno Cookie 動作確認ツール
──────────────────────────────────────────────────────────────────────
Phase 1 を実行する前に、SUNO_COOKIE が正しく機能するか確認する。

実行方法:
  SUNO_COOKIE="<貼り付け>" python tools/test_suno_cookie.py
  または
  python tools/test_suno_cookie.py  # → 入力プロンプトが表示される

確認内容:
  ① Cookie から session ID を取得できるか
  ② clerk.suno.com / clerk.suno.ai で JWT を取得できるか
  ③ studio-api.suno.ai に接続できるか
  ④ 生成リクエストを送信できるか (実際に1曲生成する)
"""

import base64
import json
import os
import sys
import time
import urllib.parse

try:
    import requests
except ImportError:
    print("pip install requests が必要です。")
    sys.exit(1)

_CLERK_CANDIDATES = [
    "https://clerk.suno.com",
    "https://clerk.suno.ai",
]
_SUNO_BASE = "https://studio-api.suno.ai"
_MODEL     = "chirp-v4-5"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer":         "https://suno.com/",
    "Origin":          "https://suno.com",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept":          "application/json, text/plain, */*",
}


def _sep(title: str = "") -> None:
    print(f"\n{'━'*55}")
    if title:
        print(f"  {title}")
        print(f"{'━'*55}")


def _extract_session_id(cookie: str) -> str:
    for segment in cookie.split(";"):
        segment = segment.strip()
        if not segment.startswith("__client="):
            continue
        jwt_raw = urllib.parse.unquote(segment[len("__client="):])
        parts   = jwt_raw.split(".")
        if len(parts) < 2:
            continue
        pad     = parts[1] + "=" * (-len(parts[1]) % 4)
        try:
            payload = json.loads(base64.b64decode(pad))
            sid     = payload.get("lastActiveSessionId", "")
            if sid:
                return sid
        except Exception:
            pass
    raise ValueError(
        "__client Cookie から session ID を取得できませんでした。\n"
        "  → DevTools で __client の Value 列をコピーしましたか？\n"
        "     (Name 列ではなく Value 列です)"
    )


def step1_extract_session(cookie: str) -> str:
    _sep("STEP 1: Cookie から session ID を取得")
    try:
        sid = _extract_session_id(cookie)
        print(f"  ✓ session ID: {sid[:12]}…")
        return sid
    except ValueError as e:
        print(f"  ✗ 失敗: {e}")
        sys.exit(1)


def step2_get_jwt(cookie: str, session_id: str) -> str:
    _sep("STEP 2: Clerk から JWT を取得")
    sess = requests.Session()
    sess.headers.update(_HEADERS)

    for clerk in _CLERK_CANDIDATES:
        url = f"{clerk}/v1/client/sessions/{session_id}/tokens"
        print(f"  接続中: {clerk} …", end=" ", flush=True)
        try:
            resp = sess.post(url, headers={"Cookie": cookie}, timeout=15)
            print(f"HTTP {resp.status_code}")

            if resp.status_code in (401, 403):
                print(f"  ✗ Cookie が無効または期限切れ (HTTP {resp.status_code})")
                print(f"    response: {resp.text[:200]}")
                print()
                print("  【対処法】")
                print("  ① suno.com を開いてログインし直す")
                print("  ② DevTools → Application → Cookies → __client の Value を再コピー")
                print("  ③ このスクリプトを再実行")
                sys.exit(1)

            if not resp.ok:
                print(f"  → HTTP {resp.status_code} — 次を試します  body: {resp.text[:100]}")
                continue

            jwt = resp.json().get("jwt", "")
            if not jwt:
                print(f"  → JWT が空 — 次を試します")
                continue

            print(f"  ✓ JWT 取得成功 (clerk={clerk}  長さ={len(jwt)})")
            sess.headers["Authorization"] = f"Bearer {jwt}"
            return jwt

        except requests.exceptions.ConnectionError:
            print(f"  → 接続失敗 — 次を試します")

    print("  ✗ 全 Clerk ドメインで JWT 取得失敗")
    sys.exit(1)


def step3_test_connection(jwt: str) -> None:
    _sep("STEP 3: Suno Studio API への接続確認")
    sess = requests.Session()
    sess.headers.update({**_HEADERS, "Authorization": f"Bearer {jwt}"})
    # フィード API を叩いて疎通確認 (ID なしでも 200 が返ることが多い)
    try:
        resp = sess.get(f"{_SUNO_BASE}/api/feed/", params={"ids": ""}, timeout=15)
        print(f"  studio-api.suno.ai → HTTP {resp.status_code}")
        if resp.ok:
            print("  ✓ 接続 OK")
        else:
            print(f"  ⚠ HTTP {resp.status_code}  body: {resp.text[:200]}")
    except Exception as e:
        print(f"  ✗ 接続失敗: {e}")


def step4_generate(cookie: str, jwt: str) -> None:
    _sep("STEP 4: テスト楽曲を生成 (lofi / 30秒程度待機)")
    sess = requests.Session()
    sess.headers.update({**_HEADERS, "Authorization": f"Bearer {jwt}"})

    payload = {
        "gpt_description_prompt": None,
        "mv":                     _MODEL,
        "prompt":                 "",
        "generation_type":        "TEXT",
        "tags":                   "chill lofi beats, vinyl crackle, cozy late night",
        "negative_tags":          "vocals, lyrics, singing",
        "title":                  "Test — All k Music",
        "make_instrumental":      True,
        "infill_start_s":         None,
        "infill_end_s":           None,
        "continue_clip_id":       None,
        "continue_at":            None,
        "task":                   None,
        "clip_id":                None,
    }

    print(f"  モデル: {_MODEL}")
    print(f"  タグ:   {payload['tags']}")
    print("  生成リクエスト送信中…", end=" ", flush=True)

    try:
        resp = sess.post(f"{_SUNO_BASE}/api/generate/v2/", json=payload, timeout=30)
        print(f"HTTP {resp.status_code}")
    except Exception as e:
        print(f"\n  ✗ リクエスト失敗: {e}")
        return

    if resp.status_code == 402:
        print("  ✗ クレジット不足 (HTTP 402) — suno.com でプランを確認してください")
        return
    if resp.status_code == 429:
        print("  ✗ レートリミット (HTTP 429) — 少し待ってから再試行してください")
        return
    if not resp.ok:
        print(f"  ✗ エラー HTTP {resp.status_code}\n  response: {resp.text[:400]}")
        return

    data     = resp.json()
    clips    = data.get("clips", [])
    clip_ids = [c["id"] for c in clips if "id" in c]
    if not clip_ids:
        print(f"  ✗ clip ID が取得できませんでした。response: {str(data)[:400]}")
        return

    print(f"  ✓ 生成開始！ clip IDs: {clip_ids}")
    print("  ポーリング中 (最大90秒)…")

    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        time.sleep(8)
        try:
            pr = sess.get(
                f"{_SUNO_BASE}/api/feed/",
                params={"ids": ",".join(clip_ids)},
                timeout=15,
            )
            raw   = pr.json()
            items = raw if isinstance(raw, list) else raw.get("clips", [])
            done  = [c for c in items if c.get("status") == "complete"]
            print(f"    complete={len(done)}/{len(clip_ids)}", end="\r", flush=True)
            if done:
                print()
                c = done[0]
                print(f"\n  ✓ 生成完了！")
                print(f"    title    : {c.get('title', '?')}")
                print(f"    audio_url: {c.get('audio_url', '?')[:80]}")
                print(f"    duration : {c.get('duration', '?')} 秒")
                return
        except Exception as e:
            print(f"  ポーリングエラー: {e}")

    print("\n  ⚠ タイムアウト — 生成に時間がかかっています。Phase 1 を実行してみてください。")


def main() -> None:
    print("=" * 55)
    print("  Suno Cookie 動作確認ツール")
    print("=" * 55)

    cookie = os.environ.get("SUNO_COOKIE", "").strip()
    if not cookie:
        print()
        print("SUNO_COOKIE 環境変数が未設定です。")
        print("取得方法:")
        print("  ① suno.com にログイン")
        print("  ② DevTools (Cmd+Option+I) → Application → Cookies")
        print("  ③ __client の Value をコピー")
        print()
        cookie = input("__client Cookie の値を貼り付けてください: ").strip()
        if not cookie:
            print("キャンセルしました。")
            sys.exit(0)

    # Cookie に __client= プレフィックスがなければ補完
    if not cookie.startswith("__client="):
        cookie = f"__client={cookie}"

    session_id = step1_extract_session(cookie)
    jwt        = step2_get_jwt(cookie, session_id)
    step3_test_connection(jwt)
    step4_generate(cookie, jwt)

    _sep()
    print("  全ステップ完了。Phase 1 を実行できます。")
    print("=" * 55)


if __name__ == "__main__":
    main()
