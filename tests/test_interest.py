from omegaconf import OmegaConf

from zotero_arxiv_daily.interest import build_corpus_from_topics, get_interest_corpus
from zotero_arxiv_daily.protocol import CorpusPaper


def test_build_corpus_from_dict_topics():
    topics = [
        {
            "name": "LLM Agents",
            "keywords": ["planning", "tool use", "multi-agent"],
            "description": "Studies on autonomous LLM agent systems and decision making.",
        },
        {
            "name": "Diffusion Models",
            "keywords": ["flow matching", "transformer"],
            "description": "Advances in generative diffusion and flow matching.",
        },
    ]
    corpus = build_corpus_from_topics(topics)
    assert len(corpus) == 2
    assert corpus[0].title == "LLM Agents"
    assert "Keywords: planning, tool use, multi-agent" in corpus[0].abstract
    assert "autonomous LLM agent" in corpus[0].abstract
    assert corpus[0].paths == ["topics/LLM Agents"]

    assert corpus[1].title == "Diffusion Models"
    assert "Keywords: flow matching, transformer" in corpus[1].abstract


def test_build_corpus_from_string_topics():
    topics = ["Reinforcement Learning from Human Feedback", "Retrieval Augmented Generation"]
    corpus = build_corpus_from_topics(topics)
    assert len(corpus) == 2
    assert corpus[0].title == "Topic 1"
    assert corpus[0].abstract == "Reinforcement Learning from Human Feedback"


def test_get_interest_corpus_from_config():
    cfg = OmegaConf.create({
        "topics": [
            {"name": "Security", "keywords": ["jailbreak"], "description": "AI security"}
        ]
    })
    corpus = get_interest_corpus(cfg)
    assert len(corpus) == 1
    assert corpus[0].title == "Security"
    assert "jailbreak" in corpus[0].abstract


def test_get_interest_corpus_empty():
    cfg = OmegaConf.create({"topics": None})
    corpus = get_interest_corpus(cfg)
    assert corpus == []
