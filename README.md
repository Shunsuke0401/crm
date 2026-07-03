# 訪問先マップ — 公開・閲覧専用版（iPhone からどこでも）

常時オンのウェブサイトとして公開する版。**閲覧専用**（現場では地図・リストを見るだけ。
訪問記録はローカル版 `../store-crm/` で付ける）。

**この repo は public。PII（店名・住所・電話）はここに入れない** —
店データは Streamlit の **Secrets（`STORES_CSV`）** に入れる。Maps キー・パスワードも Secrets。

---

## デプロイ手順（★はあなたの作業）

### 1. コードだけを public リポジトリに push（データは含めない）
`.gitignore` が `data/` と `_secrets_to_paste.txt` を除外するので、PII は push されない。
```bash
cd prospecting/store-crm-web
git add -A && git commit -m "update"
git push
```

### 2. ★ 貼り付け用の Secrets ブロックを生成
```bash
cd ../store-crm && .venv/bin/python make_secrets.py
```
→ `../store-crm-web/_secrets_to_paste.txt` ができる（123件の店データ入り・gitignored）。
開いて `GOOGLE_MAPS_API_KEY` の行に **`prospecting/.env` のキー値**を貼る。

### 3. ★ Streamlit Community Cloud にデプロイ
1. https://share.streamlit.io → GitHub でサインイン
2. **Create app** → Repository = `Shunsuke0401/crm`、Branch = `main`、Main file = `streamlit_app.py`
3. **Advanced settings → Secrets** に、`_secrets_to_paste.txt` の中身を**丸ごと**貼る
   （`GOOGLE_MAPS_API_KEY` / `APP_PASSWORD`(任意) / `STORES_CSV`）
4. **Deploy** → `https://….streamlit.app` が発行される

### 4. ★ Google キーをドメイン制限（推奨）
Google Cloud Console → 認証情報 → キー → **HTTP リファラー**：
```
https://*.streamlit.app/*
http://localhost:*/*
```

---

## データを最新にする（訪問状況を反映）
```bash
cd prospecting/store-crm && .venv/bin/python export_snapshot.py   # stores.db → web/data/stores.csv
.venv/bin/python make_secrets.py                                  # → _secrets_to_paste.txt 更新
```
→ Streamlit Cloud の **Secrets の STORES_CSV を貼り直す**（保存で自動再起動）。
※ public repo 方式ではデータが Secrets にあるため、コード変更が無ければ push は不要。

## セキュリティの整理
- **repo は public だがコードのみ**＝PII は GitHub に一切載らない（Secrets は非公開）。
- **閲覧専用**＝URLが漏れても書き換え不可。`APP_PASSWORD` を入れればさらに鍵付き。
- Maps キーは Secrets ＋ リファラ制限で流用防止。
