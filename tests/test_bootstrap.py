"""啟動與安裝流程測試。"""
from __future__ import annotations

from pathlib import Path


REQUIREMENTS_TEXT = Path("requirements.txt").read_text(encoding="utf-8")


def test_requirements_declares_utf8_encoding_for_windows_pip():
    """功能：避免 Windows 繁中 locale 的舊版 pip 用 cp950 讀取 UTF-8 中文註解失敗。"""
    first_line = REQUIREMENTS_TEXT.splitlines()[0]

    assert "coding: utf-8" in first_line.lower()


def test_requirements_pin_huggingface_hub_below_one_for_gradio_4():
    """功能：避免 Gradio 4.44 匯入已從 huggingface_hub 1.x 移除的 HfFolder 時啟動失敗。"""
    normalized = REQUIREMENTS_TEXT.replace("_", "-").lower()

    assert "huggingface-hub<1.0" in normalized


def test_requirements_pin_pydantic_for_gradio_4_api_schema():
    """功能：避免 Gradio 4 API schema 遇到新版 pydantic additionalProperties bool 後啟動失敗。"""
    normalized = REQUIREMENTS_TEXT.replace("_", "-").lower()

    assert "pydantic<2.11" in normalized
