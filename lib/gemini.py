"""名刺画像から個人情報を抽出する。Gemini 2.5 Flash + JSON schema。

複数画像を 1 リクエストで一括抽出できる（画像順=配列順）。
"""
from __future__ import annotations

import io
import json
from typing import Any

from google import genai
from google.genai import types
from PIL import Image

MODEL_DEFAULT = "gemini-2.5-flash"

# JSON schema (OpenAPI style, Gemini structured output)
MEISHI_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "name":    {"type": "STRING"},
            "kana":    {"type": "STRING"},
            "company": {"type": "STRING"},
            "title":   {"type": "STRING"},
            "email":   {"type": "STRING"},
            "phone":   {"type": "STRING"},
        },
        "required": ["name", "kana", "company", "title", "email", "phone"],
    },
}

PROMPT = """\
以下の名刺画像をそれぞれ 1 枚ずつ読み取り、記載されている情報を JSON 配列として返してください。
画像の順番と配列の順番は必ず一致させてください（画像 N 枚に対し配列要素 N 個）。
各名刺で抽出できないフィールドは空文字 "" にしてください。

フィールド:
- name: 氏名（姓名の間にスペース）
- kana: ふりがな（ひらがな or カタカナで名刺に記載されている場合のみ。ローマ字は不可）
- company: 会社名 or 所属団体（部署名は含めない）
- title: 肩書・役職（例: 代表取締役、マネージャー）
- email: メールアドレスそのまま
- phone: 電話番号そのまま（ハイフン・括弧は保持）
"""


def _to_jpeg_bytes(img_bytes: bytes) -> bytes:
    """入力画像を JPEG に正規化（PIL 経由）。HEIC 等の非対応形式は上位で弾く前提。"""
    pil = Image.open(io.BytesIO(img_bytes))
    if pil.mode in ("RGBA", "P", "LA"):
        pil = pil.convert("RGB")
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def extract_meishi_batch(
    api_key: str,
    images: list[bytes],
    model: str = MODEL_DEFAULT,
) -> list[dict[str, Any]]:
    """複数の名刺画像から情報を一括抽出する。

    Returns:
        [{"name": str|None, "kana": str|None, "company": str|None,
          "title": str|None, "email": str|None, "phone": str|None}, ...]
        空文字 "" は None に正規化して返す。
    """
    if not images:
        return []
    cli = genai.Client(api_key=api_key)
    contents: list[Any] = [PROMPT]
    for raw in images:
        contents.append(
            types.Part.from_bytes(
                data=_to_jpeg_bytes(raw),
                mime_type="image/jpeg",
            )
        )
    resp = cli.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=MEISHI_SCHEMA,
            temperature=0,
        ),
    )
    data = json.loads(resp.text)
    for r in data:
        for k in list(r.keys()):
            if r[k] == "":
                r[k] = None
    return data
