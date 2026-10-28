import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

from ..protocol import Paper

MAX_ENTRIES = 5000


class PaperStore:
    def __init__(self, store_path: Optional[str] = None):
        self.store_path = Path(store_path) if store_path else None
        if self.store_path:
            self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self.load()

    def load(self) -> dict:
        if self.store_path and self.store_path.exists():
            try:
                with open(self.store_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "pushed" not in data:
                    data["pushed"] = {}
                if "ingested" not in data:
                    data["ingested"] = {}
                if "discarded" not in data:
                    data["discarded"] = {}
                return data
            except (json.JSONDecodeError, OSError):
                pass
        return {"version": 1, "pushed": {}, "ingested": {}, "discarded": {}}

    def save(self) -> None:
        if not self.store_path:
            return
        # FIFO eviction: keep MAX_ENTRIES most recent by pushed_at
        pushed = self.data["pushed"]
        if len(pushed) > MAX_ENTRIES:
            ordered = sorted(pushed.items(), key=lambda kv: kv[1])
            pushed = dict(ordered[-MAX_ENTRIES:])
            self.data["pushed"] = pushed
        fd, tmp = tempfile.mkstemp(dir=str(self.store_path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f)
            os.replace(tmp, self.store_path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def dedup(self, papers: list[Paper]) -> list[Paper]:
        merged: dict[str, Paper] = {}
        for p in papers:
            key = p.dedup_key()
            existing = merged.get(key)
            if existing is None:
                merged[key] = p
                continue
            # keep the record with the most information: full_text > abstract
            def info_rank(x: Paper) -> int:
                if x.full_text:
                    return 2
                if x.abstract:
                    return 1
                return 0
            keep, drop = (p, existing) if info_rank(p) > info_rank(existing) else (existing, p)
            # merge sources
            srcs = []
            for s in (keep.sources or []) + (drop.sources or []):
                if s not in srcs:
                    srcs.append(s)
            keep.sources = srcs or None
            # fill missing identifiers from the dropped record
            if not keep.doi and drop.doi:
                keep.doi = drop.doi
            if not keep.arxiv_id and drop.arxiv_id:
                keep.arxiv_id = drop.arxiv_id
            if not keep.affiliations and drop.affiliations:
                keep.affiliations = drop.affiliations
            if not keep.tldr_en and drop.tldr_en:
                keep.tldr_en = drop.tldr_en
            if not keep.tldr_zh and drop.tldr_zh:
                keep.tldr_zh = drop.tldr_zh
            if not keep.tldr and drop.tldr:
                keep.tldr = drop.tldr
            if not getattr(keep, "venue", None) and getattr(drop, "venue", None):
                keep.venue = drop.venue
            if not getattr(keep, "code_url", None) and getattr(drop, "code_url", None):
                keep.code_url = drop.code_url
            if not getattr(keep, "project_url", None) and getattr(drop, "project_url", None):
                keep.project_url = drop.project_url
            keep_upvotes = getattr(keep, "hf_upvotes", None)
            drop_upvotes = getattr(drop, "hf_upvotes", None)
            if drop_upvotes is not None and (keep_upvotes is None or drop_upvotes > keep_upvotes):
                keep.hf_upvotes = drop_upvotes
            # prefer earliest published_date (normalize to naive UTC to avoid offset mismatch)
            def _utc_naive(dt: Optional[datetime]) -> Optional[datetime]:
                if dt is None:
                    return None
                if dt.tzinfo is not None:
                    return dt.astimezone(timezone.utc).replace(tzinfo=None)
                return dt

            dates = [_utc_naive(d) for d in (keep.published_date, drop.published_date) if d is not None]
            keep.published_date = min(dates) if dates else None
            merged[key] = keep
        return list(merged.values())

    def dedup_trending(self, items: list[Any]) -> list[Any]:
        merged: dict[str, Any] = {}
        for item in items:
            key = item.dedup_key()
            existing = merged.get(key)
            if existing is None:
                merged[key] = item
                continue
            # merge tags and keep highest stars
            if hasattr(item, "tags") and hasattr(existing, "tags"):
                for t in item.tags:
                    if t not in existing.tags:
                        existing.tags.append(t)
            if getattr(item, "stars", None) and (not getattr(existing, "stars", None) or item.stars > existing.stars):
                existing.stars = item.stars
            if not getattr(existing, "description", None) and getattr(item, "description", None):
                existing.description = item.description
            merged[key] = existing
        return list(merged.values())

    def filter_already_pushed(self, items: list[Any], allow_same_day: bool = False) -> list[Any]:
        pushed = self.data.get("pushed", {})
        discarded = self.data.get("discarded", {})
        ingested = self.data.get("ingested", {})
        today_prefix = datetime.now().date().isoformat()
        result = []
        for p in items:
            k = p.dedup_key()
            if k in discarded or k in ingested:
                continue
            if k in pushed:
                if allow_same_day and str(pushed[k]).startswith(today_prefix):
                    result.append(p)
                    continue
                continue
            result.append(p)
        return result

    def is_channel_delivered(self, channel: str, date_str: str) -> bool:
        """True if the report channel was already delivered on date_str (YYYY-MM-DD)."""
        deliveries = self.data.get("daily_deliveries", {})
        return channel in deliveries.get(date_str, [])

    def mark_channel_delivered(self, channel: str, date_str: str) -> None:
        """Records that a report channel was successfully delivered today."""
        deliveries = self.data.setdefault("daily_deliveries", {})
        day_channels = deliveries.setdefault(date_str, [])
        if channel not in day_channels:
            day_channels.append(channel)
        self.save()

    def mark_pushed(self, items: list[Any], pushed_at: Optional[datetime] = None) -> None:
        ts = (pushed_at or datetime.now()).isoformat()
        for p in items:
            self.data["pushed"][p.dedup_key()] = ts
        self.save()

    def is_ingested(self, item_or_key: Any) -> bool:
        key = item_or_key.dedup_key() if hasattr(item_or_key, "dedup_key") else str(item_or_key)
        return key in self.data.get("ingested", {})

    def mark_ingested(self, item_or_key: Any, metadata: Optional[dict[str, Any]] = None) -> None:
        key = item_or_key.dedup_key() if hasattr(item_or_key, "dedup_key") else str(item_or_key)
        if "ingested" not in self.data:
            self.data["ingested"] = {}
        entry: dict[str, Any] = {"ingested_at": datetime.now().isoformat()}
        if metadata:
            entry.update(metadata)
        self.data["ingested"][key] = entry
        self.save()

    def filter_already_ingested(self, items: list[Any]) -> list[Any]:
        ingested = self.data.get("ingested", {})
        return [p for p in items if (p.dedup_key() if hasattr(p, "dedup_key") else str(p)) not in ingested]

    def is_discarded(self, item_or_key: Any) -> bool:
        key = item_or_key.dedup_key() if hasattr(item_or_key, "dedup_key") else str(item_or_key)
        return key in self.data.get("discarded", {})

    def mark_discarded(self, item_or_key: Any, metadata: Optional[dict[str, Any]] = None) -> None:
        key = item_or_key.dedup_key() if hasattr(item_or_key, "dedup_key") else str(item_or_key)
        if "discarded" not in self.data:
            self.data["discarded"] = {}
        entry: dict[str, Any] = {"discarded_at": datetime.now().isoformat()}
        if hasattr(item_or_key, "title") and getattr(item_or_key, "title", None):
            entry.setdefault("title", getattr(item_or_key, "title"))
        if hasattr(item_or_key, "abstract") and getattr(item_or_key, "abstract", None):
            entry.setdefault("abstract", getattr(item_or_key, "abstract"))
        if metadata:
            entry.update(metadata)
        self.data["discarded"][key] = entry
        self.save()

    def recent_discarded(self, limit: int = 200) -> list[dict[str, Any]]:
        """Returns metadata for the most recently discarded items, newest first."""
        discarded = self.data.get("discarded", {})
        ordered = sorted(
            discarded.items(),
            key=lambda kv: kv[1].get("discarded_at", ""),
            reverse=True,
        )
        recent: list[dict[str, Any]] = []
        for key, entry in ordered:
            title = str(entry.get("title") or key)
            if not entry.get("title") and title.startswith(("http://", "https://")):
                continue  # URL-only records carry no title to compare against
            recent.append({
                "title": title,
                "abstract": str(entry.get("abstract") or entry.get("tldr") or ""),
                "url": entry.get("url") or "",
            })
            if len(recent) >= limit:
                break
        return recent

    def recent_discarded_texts(self, limit: int = 200) -> list[str]:
        """Returns combined title + abstract strings for Rocchio negative prototype feedback."""
        texts: list[str] = []
        for item in self.recent_discarded(limit=limit):
            title = (item.get("title") or "").strip()
            abstract = (item.get("abstract") or "").strip()
            combined = f"{title}. {abstract}".strip(". ")
            if combined:
                texts.append(combined)
        return texts

    def filter_discarded(self, items: list[Any]) -> list[Any]:
        discarded = self.data.get("discarded", {})
        return [p for p in items if (p.dedup_key() if hasattr(p, "dedup_key") else str(p)) not in discarded]

