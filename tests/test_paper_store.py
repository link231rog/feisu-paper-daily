from datetime import datetime, timedelta

from zotero_arxiv_daily.paper_store import PaperStore, MAX_ENTRIES
from zotero_arxiv_daily.protocol import Paper


def make_paper(**kw) -> Paper:
    base = dict(source="arxiv", title="T", authors=["A"], abstract="abs", url="u")
    base.update(kw)
    return Paper(**base)  # type: ignore[arg-type]


class TestDedup:
    def test_merges_by_doi_across_sources(self):
        a = make_paper(doi="10.1/abc", sources=["arxiv"])
        b = make_paper(doi="https://doi.org/10.1/ABC", sources=["huggingface"])
        out = PaperStore.__new__(PaperStore).dedup([a, b])
        assert len(out) == 1
        assert out[0].sources is not None and set(out[0].sources) == {"arxiv", "huggingface"}

    def test_falls_back_to_arxiv_id(self):
        a = make_paper(arxiv_id="2401.00001")
        b = make_paper(arxiv_id="2401.00001", full_text="full")
        out = PaperStore.__new__(PaperStore).dedup([a, b])
        assert len(out) == 1
        assert out[0].full_text == "full"

    def test_falls_back_to_title(self):
        a = make_paper(title="Attention Is All You Need!")
        b = make_paper(title="attention is all you need")
        out = PaperStore.__new__(PaperStore).dedup([a, b])
        assert len(out) == 1

    def test_prefers_earliest_published_date(self):
        d1 = datetime(2024, 1, 5)
        d2 = datetime(2024, 1, 1)
        a = make_paper(doi="10.1/x", published_date=d1)
        b = make_paper(doi="10.1/x", published_date=d2)
        out = PaperStore.__new__(PaperStore).dedup([a, b])
        assert out[0].published_date == d2


class TestFilterAndMark:
    def test_filter_drops_marked_keeps_new(self, tmp_path):
        store = PaperStore(str(tmp_path / "pushed.json"))
        p1 = make_paper(doi="10.1/a")
        p2 = make_paper(doi="10.1/b")
        store.mark_pushed([p1])
        assert store.filter_already_pushed([p1, p2]) == [p2]

    def test_mark_pushed_reload_roundtrip(self, tmp_path):
        path = str(tmp_path / "pushed.json")
        p = make_paper(doi="10.1/rt")
        PaperStore(path).mark_pushed([p])
        store2 = PaperStore(path)
        assert store2.filter_already_pushed([p]) == []
        data = store2.load()
        assert data["version"] == 1
        assert "10.1/rt" in data["pushed"]

    def test_mark_pushed_custom_timestamp(self, tmp_path):
        store = PaperStore(str(tmp_path / "pushed.json"))
        p = make_paper(doi="10.1/ts")
        ts = datetime(2024, 6, 1, 12, 0, 0)
        store.mark_pushed([p], pushed_at=ts)
        assert store.data["pushed"]["10.1/ts"] == ts.isoformat()

    def test_ingestion_tracking(self, tmp_path):
        store = PaperStore(str(tmp_path / "pushed.json"))
        p = make_paper(doi="10.1/ingest_test")
        assert not store.is_ingested(p)
        assert store.filter_already_ingested([p]) == [p]

        store.mark_ingested(p, {"wiki_url": "https://feishu.cn/wiki/test"})
        assert store.is_ingested(p)
        assert store.filter_already_ingested([p]) == []

        # Roundtrip reload
        store2 = PaperStore(str(tmp_path / "pushed.json"))
        assert store2.is_ingested(p)
        assert store2.data["ingested"]["10.1/ingest_test"]["wiki_url"] == "https://feishu.cn/wiki/test"


class TestCap:
    def test_caps_at_max_entries(self, tmp_path):
        store = PaperStore(str(tmp_path / "pushed.json"))
        base = datetime(2024, 1, 1)
        for i in range(MAX_ENTRIES + 10):
            store.data["pushed"][f"k{i}"] = (base + timedelta(seconds=i)).isoformat()
        store.save()
        store2 = PaperStore(str(tmp_path / "pushed.json"))
        assert len(store2.data["pushed"]) == MAX_ENTRIES
        assert "k0" not in store2.data["pushed"]
        assert f"k{MAX_ENTRIES + 9}" in store2.data["pushed"]
