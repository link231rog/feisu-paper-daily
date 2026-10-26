"""Minimal WeChat Official Account client: upload a cover and create a draft.

API flow adapted from MIT-licensed imraywang/wewrite:
https://github.com/imraywang/wewrite/blob/main/src/wewrite/toolkit/wechat_api.py
"""

import json
import mimetypes
import time
from pathlib import Path

import requests

from .daily_report import DailyReport

_TOKEN_CACHE: dict[str, tuple[str, float]] = {}


def _response(response: requests.Response) -> dict:
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"WeChat returned non-JSON response ({response.status_code})") from exc
    if data.get("errcode", 0):
        raise RuntimeError(f"WeChat API error {data['errcode']}: {data.get('errmsg', 'unknown')}")
    return data


def get_access_token(app_id: str, app_secret: str) -> str:
    now = time.time()
    cached = _TOKEN_CACHE.get(app_id)
    if cached and now < cached[1]:
        return cached[0]
    data = _response(requests.get(
        "https://api.weixin.qq.com/cgi-bin/token",
        params={"grant_type": "client_credential", "appid": app_id, "secret": app_secret},
        timeout=30,
    ))
    token = data.get("access_token")
    if not token:
        raise RuntimeError("WeChat token response has no access_token")
    _TOKEN_CACHE[app_id] = (token, now + int(data.get("expires_in", 7200)) - 300)
    return token


def upload_cover(access_token: str, image_path: str) -> str:
    path = Path(image_path)
    if not path.is_file():
        raise ValueError(f"WeChat cover image not found: {path.name}")
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with path.open("rb") as image:
        data = _response(requests.post(
            "https://api.weixin.qq.com/cgi-bin/material/add_material",
            params={"access_token": access_token, "type": "image"},
            files={"media": (path.name, image, content_type)},
            timeout=30,
        ))
    if not data.get("media_id"):
        raise RuntimeError("WeChat cover upload response has no media_id")
    return data["media_id"]


def create_draft(
    config: dict,
    report: DailyReport,
) -> str:
    """Create a draft only; this function never publishes it."""
    token = get_access_token(str(config["app_id"]), str(config["app_secret"]))
    thumb_media_id = config.get("thumb_media_id")
    if not thumb_media_id:
        if not config.get("cover_path"):
            raise ValueError("Set wechat.thumb_media_id or wechat.cover_path before creating a draft")
        thumb_media_id = upload_cover(token, str(config["cover_path"]))
    article = {
        "title": report.title,
        "author": str(config.get("author") or "Feishu Paper Daily")[:16],
        "digest": report.digest,
        "content": report.html,
        "thumb_media_id": thumb_media_id,
        "show_cover_pic": 0,
        "need_open_comment": 0,
        "only_fans_can_comment": 0,
    }
    if config.get("content_source_url"):
        article["content_source_url"] = str(config["content_source_url"])
    data = _response(requests.post(
        "https://api.weixin.qq.com/cgi-bin/draft/add",
        params={"access_token": token},
        data=json.dumps({"articles": [article]}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=30,
    ))
    if not data.get("media_id"):
        raise RuntimeError("WeChat draft response has no media_id")
    return data["media_id"]
