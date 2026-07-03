# 訪問先CRM — ホスト版（スマホから編集・Supabase バックエンド）

常時オンのウェブアプリ。**スマホから status・訪問日・メモを編集して保存**できる。
データは **Supabase(Postgres)** に永続（再起動で消えない・PC/スマホで同じデータ）。

- repo は **private**（`Shunsuke0401/crm`）。コードのみ。**PII は Supabase 側**にありリポには無い。
- 認証情報（Supabase/Maps キー）は **Streamlit Secrets**（リポに入れない）。

---

## セットアップ（★=あなたの作業、一度だけ）

### 1. Supabase プロジェクトを作る
1. https://supabase.com → GitHub でログイン → **New project**（無料）。DBパスワードは任意。
2. 立ち上がったら左メニュー **SQL Editor** を開く。

### 2. ★ テーブル作成＋初期データ投入（seed を流す）
ローカルで seed を生成（既に生成済みなら省略）：
```bash
cd prospecting/store-crm && .venv/bin/python generate_supabase_seed.py
open supabase_seed.sql          # 中身を全部コピー
```
Supabase の **SQL Editor に貼り付け → Run**。123件の `stores` テーブルができる。
（冪等：再実行しても既存行は消えない＝訪問メモは保たれ、新規店だけ追加）

### 3. ★ 接続情報を控える
Supabase **Project Settings → API**：
- `Project URL` → `SUPABASE_URL`
- `anon public` key → `SUPABASE_KEY`

### 4. ★ Streamlit Community Cloud にデプロイ
1. https://share.streamlit.io → GitHub サインイン
2. **Create app** → Repository=`Shunsuke0401/crm`、Branch=`main`、Main file=`streamlit_app.py`
3. **Advanced settings → Secrets** に貼る（`.streamlit/secrets.toml.example` 参照）：
   ```toml
   SUPABASE_URL = "https://xxxx.supabase.co"
   SUPABASE_KEY = "eyJ...（anon public）"
   GOOGLE_MAPS_API_KEY = "AIza..."   # prospecting/.env の値
   APP_PASSWORD = ""                  # 任意
   ```
4. **Deploy** → `https://….streamlit.app` → iPhone で開く（ホーム画面に追加でアプリ風）。

### 5. ★ Google キーをドメイン制限（推奨）
Google Cloud Console → 認証情報 → キー → HTTP リファラー：
`https://*.streamlit.app/*` と `http://localhost:*/*`

---

## 使い方
- サイドバーでエリア/業種/Tier/状態で絞る → 地図に未訪問ピン → タップで店名。
- 下の表で **status（プルダウン）・訪問日・メモ**を編集 → **💾保存** で Supabase に反映。
- 別端末は「🔄最新を取得」で反映。**スマホでもPCでも同じデータ**。

## 店リストを増やしたとき（新エリア深掘り等）
```bash
cd prospecting/store-crm && .venv/bin/python export_snapshot.py   # 使わない（旧CSV用）
.venv/bin/python generate_supabase_seed.py                        # 最新の123+件でseed再生成
```
→ seed を Supabase SQL Editor で再Run（`on conflict do nothing`＝新規だけ追加・編集は保持）。

## セキュリティ
- repo private・コードのみ。PII は Supabase、キーは Secrets（サーバ側）。
- `APP_PASSWORD` で合言葉ロック可。Maps キーはリファラ制限。
- anon key はサーバ側 Secrets 保持（ブラウザ非露出）。厳密にやるなら Supabase の RLS を後で有効化。
