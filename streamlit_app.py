"""
訪問先 CRM — 公開・閲覧専用版（iPhone からどこでも見る用）。

- 編集はしない（現場では「どこに行くか」を見るだけ）。記録はローカル版(store-crm/app.py)で。
- データは同梱スナップショット data/stores.csv（ローカルで export_snapshot.py → push で更新）。
- パスワードゲート + Google Maps キーは Streamlit secrets から読む（リポジトリには入れない）。

Deploy: Streamlit Community Cloud → main file = streamlit_app.py。
Secrets（Streamlit Cloud の Settings → Secrets）:
    APP_PASSWORD = "……"
    GOOGLE_MAPS_API_KEY = "……"
"""
from __future__ import annotations

import html
import io
import json
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "stores.csv"   # local-dev fallback only (gitignored, PII)
STATUS_VALUES = ["未訪問", "訪問済", "前向き", "断り"]

st.set_page_config(page_title="訪問先マップ — 職人・店", layout="wide")


# --- password gate -----------------------------------------------------------
def check_password() -> bool:
    want = st.secrets.get("APP_PASSWORD")
    if not want:
        # パスワード任意: 未設定なら鍵なし（ランダムURLのみが保護）。
        return True
    if st.session_state.get("authed"):
        return True
    with st.form("login"):
        pw = st.text_input("パスワード", type="password")
        if st.form_submit_button("入る") and pw == want:
            st.session_state["authed"] = True
            st.rerun()
        elif pw and pw != want:
            st.error("パスワードが違います。")
    return st.session_state.get("authed", False)


if not check_password():
    st.stop()


# --- data --------------------------------------------------------------------
@st.cache_data
def load() -> pd.DataFrame:
    # public repo holds NO data (PII). On the hosted app the store list comes from
    # the STORES_CSV secret; locally it falls back to the gitignored data/stores.csv.
    csv_text = st.secrets.get("STORES_CSV")
    if csv_text:
        df = pd.read_csv(io.StringIO(csv_text))
    elif DATA.exists():
        df = pd.read_csv(DATA)
    else:
        st.error("データがありません。Streamlit Cloud の Secrets に STORES_CSV を設定してください。")
        st.stop()
    for c in ("lat", "lng"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if "memo" not in df.columns:
        df["memo"] = ""
    return df


df = load()

st.title("訪問先マップ — 個人経営×熟練手技の店")
st.caption("閲覧専用。現場で「どこに行くか」を見る用。記録はローカル版で。")

# --- filters -----------------------------------------------------------------
st.sidebar.header("フィルタ")
areas = sorted(df["area_cluster"].dropna().unique().tolist())
crafts = sorted(df["type_or_craft"].dropna().unique().tolist())
tiers = sorted(df["tier"].dropna().unique().tolist())
area_f = st.sidebar.multiselect("エリア", areas, default=areas)
tier_f = st.sidebar.multiselect("Tier", tiers, default=tiers)
craft_f = st.sidebar.multiselect("業種 / craft", crafts, default=[])
status_f = st.sidebar.multiselect("ステータス", STATUS_VALUES, default=STATUS_VALUES)
q = st.sidebar.text_input("検索（店名 / 住所 / メモ）")

f = df.copy()
if area_f:
    f = f[f["area_cluster"].isin(area_f)]
if tier_f:
    f = f[f["tier"].isin(tier_f)]
if craft_f:
    f = f[f["type_or_craft"].isin(craft_f)]
if status_f:
    f = f[f["status"].isin(status_f)]
if q:
    ql = q.strip().lower()
    hay = (f["name"].fillna("") + " || " + f["address"].fillna("") + " || "
           + f["memo"].fillna("")).str.lower()
    f = f[hay.str.contains(ql)]

counts = f["status"].value_counts().to_dict()
cols = st.columns(len(STATUS_VALUES) + 1)
cols[0].metric("表示中", len(f))
for col, s in zip(cols[1:], STATUS_VALUES):
    col.metric(s, counts.get(s, 0))


# --- Google map --------------------------------------------------------------
def google_map_html(rows, key, scale, height=540):
    color = {"未訪問": "#e8453c", "訪問済": "#4285F4", "前向き": "#34A853", "断り": "#9AA0A6"}
    markers = [{
        "lat": r["lat"], "lng": r["lng"], "c": color.get(r["status"], "#e8453c"),
        "t": (f"<div style='font:13px sans-serif;max-width:240px'>"
              f"<b>{html.escape(str(r['name']))}</b><br>"
              f"{html.escape(str(r['type_or_craft']))} ・ {html.escape(str(r['area_cluster']))}<br>"
              f"<span style='color:#666'>{html.escape(str(r.get('address') or ''))}</span><br>"
              f"状態: {html.escape(str(r['status']))}</div>"),
    } for r in rows]
    clat = sum(r["lat"] for r in rows) / len(rows)
    clng = sum(r["lng"] for r in rows) / len(rows)
    return f"""
<div id="map" style="height:{height}px;width:100%;border-radius:8px"></div>
<script>
  const MARKERS = {json.dumps(markers)};
  function initMap() {{
    const map = new google.maps.Map(document.getElementById("map"), {{
      center: {{lat: {clat}, lng: {clng}}}, zoom: 14, mapTypeControl: true,
      streetViewControl: false, fullscreenControl: true }});
    const info = new google.maps.InfoWindow();
    MARKERS.forEach(m => {{
      const mk = new google.maps.Marker({{position: {{lat: m.lat, lng: m.lng}}, map,
        icon: {{path: google.maps.SymbolPath.CIRCLE, scale: {scale}, fillColor: m.c,
                fillOpacity: 1, strokeColor: "#fff", strokeWeight: 1.5}} }});
      mk.addListener("click", () => {{ info.setContent(m.t); info.open(map, mk); }});
    }});
  }}
</script>
<script async src="https://maps.googleapis.com/maps/api/js?key={key}&callback=initMap&language=ja&region=JP"></script>
"""


st.subheader("地図（Google マップ）")
mc1, mc2 = st.columns([1, 2])
unv = mc1.checkbox("未訪問だけ表示", value=True)
dot = mc2.slider("マーカーの大きさ", 4, 12, 6)
msrc = f[f["status"] == "未訪問"] if unv else f
mdf = msrc[["lat", "lng", "name", "type_or_craft", "area_cluster", "status", "address"]]\
    .dropna(subset=["lat", "lng"]).copy()
key = st.secrets.get("GOOGLE_MAPS_API_KEY")
if not len(mdf):
    st.info("表示できる座標がありません（フィルタを緩めてください）。")
elif not key:
    st.warning("GOOGLE_MAPS_API_KEY が未設定です（Streamlit Cloud の Secrets）。")
else:
    components.html(google_map_html(mdf.to_dict("records"), key, dot), height=560)
    st.caption("🔴未訪問 🔵訪問済 🟢前向き ⚪断り｜マーカーをタップで店名・住所を表示。")

# --- read-only table ---------------------------------------------------------
st.subheader("訪問先リスト")
show = ["priority_rank", "status", "name", "type_or_craft", "tier", "area_cluster",
        "address", "phone", "website", "independent_confidence", "memo"]
st.dataframe(
    f[[c for c in show if c in f.columns]],
    hide_index=True, use_container_width=True, height=520,
    column_config={
        "priority_rank": st.column_config.NumberColumn("順", width="small"),
        "website": st.column_config.LinkColumn("web"),
        "phone": st.column_config.TextColumn("電話"),
    },
)
st.caption("閲覧専用。編集・訪問記録はローカル版（Mac の store-crm）で行い、"
           "`export_snapshot.py` → git push で反映されます。")
