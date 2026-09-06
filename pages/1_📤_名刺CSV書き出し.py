"""名刺 → CSV 書き出し（DB 保存なし・受け渡し専用ページ）

このページは Supabase に一切書き込まない。
名刺画像をアップロード → Gemini で抽出 → 表で修正 → CSV ダウンロード、で完結する。
CTO など、社内 CRM とは別に名刺データを渡したい相手向け。
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import gemini

COLUMNS = ["name", "kana", "company", "title", "email", "phone", "memo"]
COLUMN_LABELS = {
    "name": "氏名",
    "kana": "ふりがな",
    "company": "会社",
    "title": "肩書",
    "email": "email",
    "phone": "電話",
    "memo": "メモ",
}

st.set_page_config(page_title="名刺CSV書き出し", page_icon="📤", layout="wide")


def gate() -> bool:
    pw = st.secrets.get("APP_PASSWORD", "")
    if not pw:
        return True
    if st.session_state.get("authed"):
        return True
    with st.form("login_csv"):
        st.subheader("🔒 合言葉")
        entry = st.text_input("パスワード", type="password")
        if st.form_submit_button("入る") and entry == pw:
            st.session_state["authed"] = True
            st.rerun()
    return False


def main():
    st.title("📤 名刺 → CSV 書き出し")
    st.caption(
        "このページは **Supabase に保存しません**。名刺を読み取って CSV にするだけの受け渡し専用です。"
    )

    gemini_key = st.secrets.get("GEMINI_API_KEY", "")
    if not gemini_key:
        st.error("Secrets に GEMINI_API_KEY が設定されていません。")
        st.stop()

    uploads = st.file_uploader(
        "📎 名刺画像をまとめてドラッグ&ドロップ or 選択（**複数枚OK**・1枚に複数名刺が写っていても可）",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        key="csv_uploads",
    )

    if uploads:
        n = len(uploads)
        total_kb = sum(len(u.getvalue()) for u in uploads) / 1024
        st.caption(f"✅ **{n} 枚** アップロード済み・合計 {total_kb:.0f} KB")
        if n > 15:
            st.warning(f"⚠️ {n} 枚は多すぎるかも（Gemini がタイムアウトする可能性）。10 枚以下推奨。")
        with st.expander(f"📸 プレビュー ({n} 枚)", expanded=False):
            cols = st.columns(min(5, n))
            for i, u in enumerate(uploads[:10]):
                with cols[i % 5]:
                    st.image(u.getvalue(), caption=u.name, use_container_width=True)
            if n > 10:
                st.caption(f"... 他 {n - 10} 枚")

    btn_label = f"🤖 {len(uploads)} 枚をまとめて抽出" if uploads else "🤖 抽出する"
    if st.button(btn_label, type="primary", disabled=not uploads, key="csv_extract"):
        model_name = st.secrets.get("GEMINI_MODEL", gemini.MODEL_DEFAULT)
        with st.spinner(f"{len(uploads)} 枚を Gemini ({model_name}) で解析中..."):
            images = [u.read() for u in uploads]
            try:
                extracted = gemini.extract_meishi_batch(gemini_key, images, model=model_name)
            except Exception as e:
                st.error(f"抽出失敗: {e}")
                extracted = []
        if extracted:
            st.success(f"✅ {len(extracted)} 名を抽出しました。")
        for r in extracted:
            r.setdefault("memo", "")
        st.session_state["csv_draft"] = extracted

    draft = st.session_state.get("csv_draft", [])
    if not draft:
        st.info("名刺をアップロードして「抽出する」を押してください。")
        return

    st.subheader("レビュー・修正")
    st.caption("表を直接編集できます。行の追加・削除も可能です。")

    df = pd.DataFrame(draft)
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = None
    df = df[COLUMNS]

    edited = st.data_editor(
        df,
        hide_index=True,
        use_container_width=True,
        num_rows="dynamic",
        column_config={c: st.column_config.TextColumn(COLUMN_LABELS[c]) for c in COLUMNS},
        key="csv_editor",
    )

    clean = edited.dropna(how="all").fillna("")
    clean = clean[clean["name"].astype(str).str.strip() != ""]

    st.divider()
    c1, c2 = st.columns([2, 1])
    with c1:
        st.metric("書き出し件数", len(clean))
    with c2:
        if st.button("🗑️ クリア", key="csv_clear"):
            st.session_state.pop("csv_draft", None)
            st.rerun()

    if len(clean):
        # Excel で開いても文字化けしないよう BOM 付き UTF-8
        csv_bytes = clean.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "⬇️ CSV をダウンロード",
            data=csv_bytes,
            file_name=f"meishi_{pd.Timestamp.now(tz='Asia/Tokyo'):%Y%m%d_%H%M}.csv",
            mime="text/csv",
            type="primary",
        )
    else:
        st.warning("氏名が入っている行がありません。")


if gate():
    main()
