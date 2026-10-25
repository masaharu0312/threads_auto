"""Threads API（graph.threads.net）の最小限のラッパー。"""
from __future__ import annotations

import time

import requests

GRAPH = "https://graph.threads.net"
BASE = f"{GRAPH}/v1.0"


class ThreadsError(Exception):
    pass


def _call(method: str, url: str, **params) -> dict:
    if method == "GET":
        r = requests.get(url, params=params, timeout=60)
    else:
        r = requests.post(url, data=params, timeout=60)
    try:
        data = r.json()
    except ValueError:
        raise ThreadsError(f"HTTP {r.status_code}: {r.text[:200]}")
    if r.status_code >= 400 or "error" in data:
        err = data.get("error", {})
        raise ThreadsError(f"HTTP {r.status_code}: {err.get('message', data)}")
    return data


def get_me(token: str) -> dict:
    return _call("GET", f"{BASE}/me", fields="id,username", access_token=token)


def exchange_token(short_token: str, app_secret: str) -> str:
    """短期トークン → 長期トークン（60日）。"""
    data = _call("GET", f"{GRAPH}/access_token", grant_type="th_exchange_token",
                 client_secret=app_secret, access_token=short_token)
    return data["access_token"]


def refresh_token(token: str) -> str:
    """長期トークンの期限を延長する（発行から24時間以上たっている必要がある）。"""
    data = _call("GET", f"{GRAPH}/refresh_access_token",
                 grant_type="th_refresh_token", access_token=token)
    return data["access_token"]


def post_image(user_id: str, token: str, text: str, image_url: str) -> tuple[str, str]:
    """画像付きで投稿し、(投稿ID, 投稿URL) を返す。"""
    container = _call("POST", f"{BASE}/{user_id}/threads", media_type="IMAGE",
                      image_url=image_url, text=text, access_token=token)["id"]

    # コンテナの処理完了を待つ
    for _ in range(24):
        time.sleep(5)
        status = _call("GET", f"{BASE}/{container}", fields="status,error_message", access_token=token)
        if status.get("status") == "FINISHED":
            break
        if status.get("status") in ("ERROR", "EXPIRED"):
            raise ThreadsError(f"画像の処理に失敗: {status.get('error_message', status)}")
    else:
        raise ThreadsError("画像の処理が2分以内に終わりませんでした")

    media_id = _call("POST", f"{BASE}/{user_id}/threads_publish",
                     creation_id=container, access_token=token)["id"]
    permalink = _call("GET", f"{BASE}/{media_id}", fields="permalink", access_token=token).get("permalink", "")
    return media_id, permalink
