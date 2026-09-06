# CLAUDE.md — Minamoto CRM アプリ（store-crm-web）

このリポは **Streamlit CRM アプリのコード**。
アウトリーチの文面・ルールはここではなく **`JDATA/plans/outreach-rules.md`** を読むこと。

---

## 構成

- `streamlit_app.py` — 3 タブ（AI 買い手 / 職人 / 統括=名刺）+ 名刺インテーク（Gemini 抽出）
- `pages/1_📤_名刺CSV書き出し.py` — DB 保存なしの CSV 受け渡し専用ページ（CTO 用）
- `lib/db.py` — Supabase client + fetch/upsert/delete
- `lib/gemini.py` — 名刺画像の一括抽出（複数枚 / 1 枚に複数名刺も可）
- デプロイ: GitHub `Shunsuke0401/crm` main → Streamlit Cloud 自動デプロイ
- Secrets: SUPABASE_URL / SUPABASE_KEY / GOOGLE_MAPS_API_KEY / GEMINI_API_KEY / GEMINI_MODEL / APP_PASSWORD

## DB（Supabase）

- Project: `rlowtjfouvwmcjksjvvj`／アカウントは **nakatani@minamoto.ai**（個人 Gmail 側ではない）
- `stores`（職人 502+）: **破壊的変更禁止**。編集可能列は status / visit_date / memo のみ
- `ai_contacts`: 買い手。会社単位（1 行 = 1 社）
- `people`: 名刺 = 個人。related_store_place_id / related_ai_contact_id で紐付け
- テーブル削除・列変更・移行は **founder 承認 + 事前バックアップ**

## 既知の落とし穴

- **`st.data_editor` の型互換**: Supabase の DATE は文字列で返る → DateColumn 不可（TextColumn を使う）。
  id 系は nullable Int64 に cast（`lib/db.py` の fetch 参照）
- **numpy 型は Supabase 送信前に Python native へ**（`lib/db.py` の `_py()` / `_clean()` 経由。直接 insert しない）
- **Gemini モデル ID は deprecate される** → Secrets の `GEMINI_MODEL` で上書き（コード変更不要）
- Supabase 無料枠は inactivity で pause することがある → Dashboard から Restore
- 名刺 batch が二重実行されると people に重複が入る → 取り込み後に重複チェック

## ルール

1. 動作確認前に「直った」と言わない
2. push 前に `python3 -m py_compile` で構文チェック
3. main 直 push で Streamlit Cloud に即反映される。壊れた状態を push しない
