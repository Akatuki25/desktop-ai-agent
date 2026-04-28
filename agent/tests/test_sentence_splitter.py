"""SentenceSplitter — incremental sentence boundary detection."""

from __future__ import annotations

from agent.voice.sentence_splitter import SentenceSplitter


def _drive(splitter: SentenceSplitter, chunks: list[str]) -> tuple[list[str], str]:
    out: list[str] = []
    for c in chunks:
        out.extend(splitter.feed(c))
    return out, splitter.flush()


def test_single_japanese_sentence_emitted_on_terminator() -> None:
    sentences, tail = _drive(SentenceSplitter(), ["こんにちは、ぼくはずんだもんなのだ。"])
    assert sentences == ["こんにちは、ぼくはずんだもんなのだ。"]
    assert tail == ""


def test_chunked_input_is_buffered_until_terminator() -> None:
    # LLM streams character-by-character.
    sentences, tail = _drive(
        SentenceSplitter(),
        ["こ", "ん", "に", "ち", "は", "、", "元", "気", "?"],
    )
    assert sentences == ["こんにちは、元気?"]
    assert tail == ""


def test_multiple_sentences_emitted_in_order() -> None:
    sentences, tail = _drive(
        SentenceSplitter(),
        ["最初の文です。", "次の文だよ！", "三つ目の質問は?"],
    )
    assert sentences == ["最初の文です。", "次の文だよ！", "三つ目の質問は?"]
    assert tail == ""


def test_short_fragment_below_min_chars_is_held() -> None:
    # "はい。" is 3 chars, below default min 8 — should not flush yet.
    sentences, tail = _drive(SentenceSplitter(), ["はい。", "本当に短いね。"])
    # The "はい。" terminator is ignored because length < min_chars.
    # The next terminator after enough chars triggers a flush.
    assert sentences == ["はい。本当に短いね。"]
    assert tail == ""


def test_newline_breaks_list_items() -> None:
    sentences, tail = _drive(
        SentenceSplitter(),
        ["- 項目その一です\n", "- 項目その二は別の文\n", "- 三つ目最後"],
    )
    assert "- 項目その一です" in sentences
    assert "- 項目その二は別の文" in sentences
    assert tail == "- 三つ目最後"


def test_flush_returns_unterminated_tail() -> None:
    sp = SentenceSplitter()
    sentences = list(sp.feed("途中で切れて"))
    assert sentences == []
    assert sp.flush() == "途中で切れて"


def test_flush_empty_when_buffer_empty() -> None:
    sp = SentenceSplitter()
    list(sp.feed("最初の文。"))  # consume
    assert sp.flush() == ""


def test_english_terminators() -> None:
    sentences, _ = _drive(
        SentenceSplitter(),
        ["This is a sentence. ", "Another one! ", "And a question?"],
    )
    assert sentences == ["This is a sentence.", "Another one!", "And a question?"]
