"""
訪問先CRM（ホスト版・スマホから編集可）— Supabase(Postgres) バックエンド。
- データは Supabase に永続（再起動で消えない・複数端末で共有）。
- status / 訪問日 / メモ をこの画面から編集→保存。
- Secrets: SUPABASE_URL, SUPABASE_KEY, GOOGLE_MAPS_API_KEY, APP_PASSWORD(任意)
"""
from __future__ import annotations

import html
from urllib.parse import quote

import pandas as pd
import streamlit as st
from supabase import create_client
from streamlit_geolocation import streamlit_geolocation

STATUS_VALUES = ["未訪問", "訪問済", "前向き", "断り"]


def maps_link(name, place_id) -> str:
    """Google Maps URL that opens the exact business (by place_id)."""
    q = quote(str(name or ""))
    pid = str(place_id or "")
    if pid:
        return f"https://www.google.com/maps/search/?api=1&query={q}&query_place_id={pid}"
    return f"https://www.google.com/maps/search/?api=1&query={q}"
STATUS_RGB = {"未訪問": "#e8453c", "訪問済": "#4285F4", "前向き": "#34A853", "断り": "#9AA0A6"}
EDITABLE = ["status", "visit_date", "memo"]

st.set_page_config(page_title="訪問先CRM", page_icon="🗺️", layout="wide")


# ---- optional password gate -------------------------------------------------
def gate() -> bool:
    pw = st.secrets.get("APP_PASSWORD", "")
    if not pw:
        return True
    if st.session_state.get("authed"):
        return True
    with st.form("login"):
        st.subheader("🔒 合言葉")
        entry = st.text_input("パスワード", type="password")
        if st.form_submit_button("入る") and entry == pw:
            st.session_state["authed"] = True
            st.rerun()
    return False


@st.cache_resource
def client():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


def fetch() -> pd.DataFrame:
    rows = client().table("stores").select("*").order("priority_rank").execute().data
    df = pd.DataFrame(rows)
    for c in ("lat", "lng"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in (*EDITABLE, "owner_name", "owner_kana"):
        if c not in df:
            df[c] = None
    if not df.empty:
        df["map_url"] = df.apply(lambda r: maps_link(r.get("name"), r.get("place_id")), axis=1)
    return df


def save_changes(edited: pd.DataFrame, original: pd.DataFrame):
    orig = original.set_index("place_id")
    n = 0
    for _, row in edited.iterrows():
        pid = row["place_id"]
        if pid not in orig.index:
            continue
        patch = {}
        for c in EDITABLE:
            new = None if pd.isna(row.get(c)) else row.get(c)
            old = orig.at[pid, c]
            old = None if pd.isna(old) else old
            if str(new or "") != str(old or ""):
                patch[c] = new
        if patch:
            patch["updated_at"] = pd.Timestamp.utcnow().isoformat()
            client().table("stores").update(patch).eq("place_id", pid).execute()
            n += 1
    return n


# ---- google map (colored, clickable markers) --------------------------------
def google_map(rows: list[dict], key: str, scale: int, me: dict | None = None,
               height: int = 460) -> str:
    markers = [{
        "lat": r["lat"], "lng": r["lng"], "c": STATUS_RGB.get(r["status"], "#e8453c"),
        "t": (f"<div style='font:13px sans-serif;max-width:250px;line-height:1.5'>"
              f"<b>{html.escape(str(r['name']))}</b><br>"
              + (f"店主: {html.escape(str(r.get('owner_name')))}"
                 + (f"（{html.escape(str(r.get('owner_kana')))}）" if r.get('owner_kana') else "")
                 + "<br>" if r.get('owner_name') else "") +
              f"Type: {html.escape(str(r['type_or_craft']))}<br>"
              f"エリア: {html.escape(str(r['area_cluster']))}<br>"
              f"状態: {html.escape(str(r['status']))}<br>"
              f"<span style='color:#666'>{html.escape(str(r.get('address') or ''))}</span><br>"
              f"<a href='{html.escape(maps_link(r.get('name'), r.get('place_id')))}' "
              f"target='_blank' rel='noopener'>📍 Googleマップで開く</a></div>"),
    } for r in rows]
    import json
    data = json.dumps(markers)
    me_js = json.dumps(me) if me else "null"
    # center on the user if we have their location, else on the stores
    clat = me["lat"] if me else sum(r["lat"] for r in rows) / len(rows)
    clng = me["lng"] if me else sum(r["lng"] for r in rows) / len(rows)
    return f"""
<div id="map" style="height:{height}px;width:100%;border-radius:8px"></div>
<div id="geo" style="font:12px sans-serif;color:#888;margin-top:4px"></div>
<script>
  const M={data};
  function initMap(){{
    const map=new google.maps.Map(document.getElementById("map"),
      {{center:{{lat:{clat},lng:{clng}}},zoom:14,streetViewControl:false}});
    const info=new google.maps.InfoWindow();
    M.forEach(m=>{{
      const mk=new google.maps.Marker({{position:{{lat:m.lat,lng:m.lng}},map,
        icon:{{path:google.maps.SymbolPath.CIRCLE,scale:{scale},fillColor:m.c,
               fillOpacity:1,strokeColor:"#fff",strokeWeight:1.5}}}});
      mk.addListener("click",()=>{{info.setContent(m.t);info.open(map,mk);}});
    }});

    // ---- current location: coords come from Python (streamlit_geolocation),
    //      because this map iframe itself is not allowed to call geolocation ----
    const geo=document.getElementById("geo");
    const ME={me_js};
    if(ME && ME.lat!=null){{
      const p={{lat:ME.lat,lng:ME.lng}};
      new google.maps.Marker({{position:p,map,zIndex:9999,title:"現在地",
        icon:{{path:google.maps.SymbolPath.CIRCLE,scale:7,fillColor:"#4285F4",
               fillOpacity:1,strokeColor:"#fff",strokeWeight:3}}}});
      new google.maps.Circle({{map,center:p,radius:(ME.acc||30),fillColor:"#4285F4",
        fillOpacity:0.12,strokeColor:"#4285F4",strokeOpacity:0.35,strokeWeight:1}});
      const btn=document.createElement("button");
      btn.textContent="📍 現在地へ";
      btn.style.cssText="margin:8px;padding:8px 12px;border:none;border-radius:6px;"
        +"background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.3);font:13px sans-serif;cursor:pointer";
      btn.onclick=()=>{{ map.setCenter(p); map.setZoom(16); }};
      map.controls[google.maps.ControlPosition.TOP_RIGHT].push(btn);
      geo.textContent="現在地を表示中（青い点）";
    }} else {{
      geo.textContent="現在地を出すには、地図の上の「📍位置情報」ボタンを押して許可してください。";
    }}
  }}
</script>
<script async src="https://maps.googleapis.com/maps/api/js?key={key}&callback=initMap&language=ja&region=JP"></script>
"""


# ---- app --------------------------------------------------------------------
def main():
    st.title("🗺️ 訪問先CRM — 個人経営×熟練手技")
    st.caption("スマホから status・訪問日・メモを編集して保存できます。データは Supabase に保存。")

    df = fetch()
    if df.empty:
        st.warning("データがありません。Supabase に seed（supabase_seed.sql）を流しましたか？")
        st.stop()

    # sidebar filters
    with st.sidebar:
        st.header("フィルタ")
        areas = st.multiselect("エリア", sorted(df["area_cluster"].dropna().unique()))
        crafts = st.multiselect("業種", sorted(df["type_or_craft"].dropna().unique()))
        tiers = st.multiselect("Tier", sorted(df["tier"].dropna().unique()))
        stats = st.multiselect("状態", STATUS_VALUES)
        if st.button("🔄 最新を取得"):
            st.rerun()

    f = df.copy()
    if areas:  f = f[f["area_cluster"].isin(areas)]
    if crafts: f = f[f["type_or_craft"].isin(crafts)]
    if tiers:  f = f[f["tier"].isin(tiers)]
    if stats:  f = f[f["status"].isin(stats)]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("表示", len(f))
    c2.metric("未訪問", int((f["status"] == "未訪問").sum()))
    c3.metric("前向き", int((f["status"] == "前向き").sum()))
    c4.metric("訪問済", int((f["status"] == "訪問済").sum()))

    # map
    key = st.secrets.get("GOOGLE_MAPS_API_KEY", "")
    st.subheader("地図")

    # current location — obtained OUTSIDE the map iframe (this component is allowed
    # to prompt for geolocation, the raw html() map iframe is not). Tap → allow.
    st.caption("現在地を地図に出す→ 下のアイコンを押して「許可」")
    gl = streamlit_geolocation()
    if gl and gl.get("latitude") is not None:
        st.session_state["me"] = {"lat": gl["latitude"], "lng": gl["longitude"],
                                  "acc": gl.get("accuracy") or 30}
    me = st.session_state.get("me")

    mc1, mc2 = st.columns([1, 2])
    only_unvisited = mc1.checkbox("未訪問だけ", value=True)
    dot = mc2.slider("ドット", 2, 12, 5)
    msrc = f[f["status"] == "未訪問"] if only_unvisited else f
    msrc = msrc.dropna(subset=["lat", "lng"])
    if key and len(msrc):
        st.components.v1.html(google_map(msrc.to_dict("records"), key, dot, me=me), height=480)
        st.caption("🔴未訪問 🔵訪問済 🟢前向き ⚪断り｜青=現在地｜ピンをタップで店名・住所")
    elif not key:
        st.info("地図には Secrets の GOOGLE_MAPS_API_KEY が必要です。")

    # editable table
    st.subheader("リスト（編集して保存）")
    st.caption("**状態**セルをタップ→プルダウンで選択。住所は📍でGoogleマップが開く。編集後に「保存」。")
    view_cols = ["name", "owner_name", "owner_kana", "status", "visit_date", "memo",
                 "type_or_craft", "tier", "area_cluster", "map_url", "phone",
                 "independent_confidence", "place_id"]
    view_cols = [c for c in view_cols if c in f.columns]
    edited = st.data_editor(
        f[view_cols],
        hide_index=True,
        use_container_width=True,
        column_order=view_cols,
        column_config={
            "name": st.column_config.TextColumn("店名", disabled=True),
            "owner_name": st.column_config.TextColumn("店主", disabled=True),
            "owner_kana": st.column_config.TextColumn("ふりがな", disabled=True),
            "status": st.column_config.SelectboxColumn(
                "状態", options=STATUS_VALUES, required=True, width="small"),
            "visit_date": st.column_config.TextColumn("訪問日"),
            "memo": st.column_config.TextColumn("メモ", width="large"),
            "type_or_craft": st.column_config.TextColumn("Type", disabled=True),
            "tier": st.column_config.TextColumn("Tier", disabled=True),
            "area_cluster": st.column_config.TextColumn("エリア", disabled=True),
            "map_url": st.column_config.LinkColumn(
                "住所（地図）", display_text="📍 地図で開く", disabled=True),
            "phone": st.column_config.TextColumn("電話", disabled=True),
            "independent_confidence": st.column_config.TextColumn("独立度", disabled=True),
            "place_id": st.column_config.TextColumn("id", disabled=True),
        },
        key="editor",
    )
    if st.button("💾 保存", type="primary"):
        n = save_changes(edited, f)
        st.success(f"{n} 件を保存しました。") if n else st.info("変更はありませんでした。")
        st.rerun()


if gate():
    main()
