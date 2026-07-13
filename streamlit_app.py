"""Minamoto 統括CRM — 3 タブ (AI / 職人 / 統括=名刺) を単一 Streamlit アプリで。

- Supabase(Postgres) バックエンド。
- 職人シートは 502 件・既存挙動を保全（フィルタは sidebar → 各タブ内 expander へ）。
- AI (ai_contacts) と 統括 (people) は Excel 風 data_editor + 個別追加フォーム。
- 名刺インテークは Gemini 2.5 Flash に複数枚を一括投入 → 抽出 → レビュー → 保存。

Secrets:
  SUPABASE_URL, SUPABASE_KEY, GOOGLE_MAPS_API_KEY, GEMINI_API_KEY, APP_PASSWORD(任意)
"""
from __future__ import annotations

import html
import json
from urllib.parse import quote

import pandas as pd
import streamlit as st
from streamlit_geolocation import streamlit_geolocation

from lib import db, gemini

STATUS_RGB = {"未訪問": "#e8453c", "訪問済": "#4285F4", "前向き": "#34A853",
              "確定": "#F9AB00", "断り": "#9AA0A6"}

st.set_page_config(page_title="Minamoto 統括CRM", page_icon="📇", layout="wide")


# ---- shared -----------------------------------------------------------------
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


def haversine_km(a_lat, a_lng, b_lat, b_lng):
    from math import radians, sin, cos, asin, sqrt
    p1, p2 = radians(a_lat), radians(b_lat)
    dp, dl = radians(b_lat - a_lat), radians(b_lng - a_lng)
    h = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * 6371 * asin(sqrt(h))


def maps_link(name, place_id) -> str:
    q = quote(str(name or ""))
    pid = str(place_id or "")
    if pid:
        return f"https://www.google.com/maps/search/?api=1&query={q}&query_place_id={pid}"
    return f"https://www.google.com/maps/search/?api=1&query={q}"


# ---- Tab 1: 職人 (stores) ---------------------------------------------------
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
    data = json.dumps(markers)
    me_js = json.dumps(me) if me else "null"
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


def _save_store_changes(edited: pd.DataFrame, original: pd.DataFrame) -> int:
    orig = original.set_index("place_id")
    n = 0
    for _, row in edited.iterrows():
        pid = row["place_id"]
        if pid not in orig.index:
            continue
        patch = {}
        for c in db.STORE_EDITABLE:
            new = None if pd.isna(row.get(c)) else row.get(c)
            old = orig.at[pid, c]
            old = None if pd.isna(old) else old
            if str(new or "") != str(old or ""):
                patch[c] = new
        if patch:
            db.update_store(pid, patch)
            n += 1
    return n


def render_stores_tab():
    st.caption("スマホから status・訪問日・メモを編集して保存できます。データは Supabase に保存。")

    df = db.fetch_stores()
    if df.empty:
        st.warning("データがありません。Supabase に seed（supabase_seed.sql）を流しましたか？")
        return

    df["map_url"] = df.apply(lambda r: maps_link(r.get("name"), r.get("place_id")), axis=1)

    with st.expander("🔍 フィルタ", expanded=False):
        cat = st.radio("分類", ["すべて", "飲食", "その他"], horizontal=True, key="store_cat")
        areas = st.multiselect("エリア", sorted(df["area_cluster"].dropna().unique()), key="store_areas")
        crafts = st.multiselect("業種", sorted(df["type_or_craft"].dropna().unique()), key="store_crafts")
        tiers = st.multiselect("Tier", sorted(df["tier"].dropna().unique()), key="store_tiers")
        stats = st.multiselect("状態", db.STORE_STATUS_VALUES, key="store_stats")
        if st.button("🔄 最新を取得", key="store_refresh"):
            st.rerun()

    f = df.copy()
    if cat != "すべて" and "category" in f:
        f = f[f["category"] == cat]
    if areas:  f = f[f["area_cluster"].isin(areas)]
    if crafts: f = f[f["type_or_craft"].isin(crafts)]
    if tiers:  f = f[f["tier"].isin(tiers)]
    if stats:  f = f[f["status"].isin(stats)]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("表示", len(f))
    c2.metric("未訪問", int((f["status"] == "未訪問").sum()))
    c3.metric("前向き", int((f["status"] == "前向き").sum()))
    c4.metric("訪問済", int((f["status"] == "訪問済").sum()))

    key = st.secrets.get("GOOGLE_MAPS_API_KEY", "")
    st.subheader("地図")
    st.caption("現在地を地図に出す→ 下のアイコンを押して「許可」")
    gl = streamlit_geolocation()
    if gl and gl.get("latitude") is not None:
        st.session_state["me"] = {"lat": gl["latitude"], "lng": gl["longitude"],
                                  "acc": gl.get("accuracy") or 30}
    me = st.session_state.get("me")

    mc1, mc2 = st.columns([1, 2])
    only_unvisited = mc1.checkbox("未訪問だけ", value=True, key="store_unvisited")
    dot = mc2.slider("ドット", 2, 12, 5, key="store_dot")
    msrc = f[f["status"] == "未訪問"] if only_unvisited else f
    msrc = msrc.dropna(subset=["lat", "lng"])
    if key and len(msrc):
        st.components.v1.html(google_map(msrc.to_dict("records"), key, dot, me=me), height=480)
        st.caption("🔴未訪問 🔵訪問済 🟢前向き 🟡確定 ⚪断り｜青=現在地｜ピンをタップで店名・住所")
    elif not key:
        st.info("地図には Secrets の GOOGLE_MAPS_API_KEY が必要です。")

    st.subheader("リスト（編集して保存）")
    has_loc = bool(me and me.get("lat") is not None)
    if has_loc:
        def _dkm(r):
            try:
                return haversine_km(me["lat"], me["lng"], float(r["lat"]), float(r["lng"]))
            except Exception:
                return None
        f = f.copy()
        f["_dist"] = f.apply(_dkm, axis=1)
        f = f.sort_values("_dist", na_position="last")
        st.caption("**現在地から近い順**に並んでいます。状態セルで選択→「保存」。住所は📍でマップ。")
    else:
        st.caption("状態セルをタップ→選択。（地図の📍で現在地を許可すると『近い順』に並びます）")

    view_cols = ["name", "owner_name", "owner_kana", "status", "visit_date", "memo",
                 "category", "type_or_craft", "tier", "area_cluster", "map_url", "phone",
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
                "状態", options=db.STORE_STATUS_VALUES, required=True, width="small"),
            "visit_date": st.column_config.TextColumn("訪問日"),
            "memo": st.column_config.TextColumn("メモ", width="large"),
            "category": st.column_config.TextColumn("分類", disabled=True, width="small"),
            "type_or_craft": st.column_config.TextColumn("業種", disabled=True),
            "tier": st.column_config.TextColumn("Tier", disabled=True),
            "area_cluster": st.column_config.TextColumn("エリア", disabled=True),
            "map_url": st.column_config.LinkColumn(
                "住所（地図）", display_text="📍 地図で開く", disabled=True),
            "phone": st.column_config.TextColumn("電話", disabled=True),
            "independent_confidence": st.column_config.TextColumn("独立度", disabled=True),
            "place_id": st.column_config.TextColumn("id", disabled=True),
        },
        key="store_editor",
    )
    if st.button("💾 保存", type="primary", key="store_save"):
        n = _save_store_changes(edited, f)
        st.success(f"{n} 件を保存しました。") if n else st.info("変更はありませんでした。")
        st.rerun()


# ---- Tab 2: AI (ai_contacts / 買い手) ----------------------------------------
def _save_ai_changes(edited: pd.DataFrame, original: pd.DataFrame) -> tuple[int, int, int]:
    """(insert, update, delete) の件数を返す。"""
    orig_by_id = {r["id"]: r for _, r in original.iterrows() if pd.notna(r.get("id"))}
    edited_ids = {int(r["id"]) for _, r in edited.iterrows() if pd.notna(r.get("id"))}
    ins = upd = 0
    for _, row in edited.iterrows():
        rd = row.to_dict()
        if pd.isna(rd.get("id")):
            # new row
            payload = {k: v for k, v in rd.items() if k in db.AI_EDITABLE and pd.notna(v)}
            if not payload.get("company"):
                continue
            db.upsert_ai_contact(payload)
            ins += 1
        else:
            rid = int(rd["id"])
            old = orig_by_id.get(rid)
            if old is None:
                continue
            patch = {}
            for c in db.AI_EDITABLE:
                new = None if pd.isna(rd.get(c)) else rd.get(c)
                oldv = None if pd.isna(old.get(c)) else old.get(c)
                if str(new or "") != str(oldv or ""):
                    patch[c] = new
            if patch:
                patch["id"] = rid
                db.upsert_ai_contact(patch)
                upd += 1
    dels = 0
    for orig_id in orig_by_id:
        if orig_id not in edited_ids:
            db.delete_ai_contact(int(orig_id))
            dels += 1
    return ins, upd, dels


def render_ai_tab():
    st.caption("買い手 (AI ラボ / VLA / World Model 等) を会社単位で管理。担当者は 統括タブ (people) で紐付け。")

    df = db.fetch_ai_contacts()
    if df.empty:
        st.info("まだ登録された会社がありません。下の表で行を追加してください。")

    with st.expander("🔍 フィルタ", expanded=False):
        f_status = st.multiselect("状態", db.AI_STATUS_VALUES, key="ai_status")
        f_field = st.text_input("field 部分一致", "", key="ai_field")
        if st.button("🔄 最新を取得", key="ai_refresh"):
            st.rerun()

    f = df.copy()
    if f_status:
        f = f[f["status"].isin(f_status)]
    if f_field and "field" in f:
        f = f[f["field"].fillna("").str.contains(f_field, case=False, na=False)]

    if not df.empty:
        cols = st.columns(len(db.AI_STATUS_VALUES) + 1)
        cols[0].metric("表示", len(f))
        for i, s in enumerate(db.AI_STATUS_VALUES, start=1):
            cols[i].metric(s, int((df["status"] == s).sum()))

    view_cols = [
        "id", "company", "status", "field", "primary_contact_name",
        "primary_contact_role", "primary_contact_email", "linkedin_url", "website",
        "source", "last_contact_date", "notes",
    ]
    for c in view_cols:
        if c not in f.columns:
            f[c] = None

    edited = st.data_editor(
        f[view_cols],
        hide_index=True,
        use_container_width=True,
        num_rows="dynamic",
        column_order=view_cols,
        column_config={
            "id": st.column_config.NumberColumn("id", disabled=True, width="small"),
            "company": st.column_config.TextColumn("会社名", required=True),
            "status": st.column_config.SelectboxColumn(
                "状態", options=db.AI_STATUS_VALUES, required=True, width="small"),
            "field": st.column_config.TextColumn("field"),
            "primary_contact_name":  st.column_config.TextColumn("担当者"),
            "primary_contact_role":  st.column_config.TextColumn("役職"),
            "primary_contact_email": st.column_config.TextColumn("email"),
            "linkedin_url":  st.column_config.LinkColumn("LinkedIn"),
            "website":       st.column_config.LinkColumn("website"),
            "source":        st.column_config.TextColumn("source"),
            "last_contact_date": st.column_config.TextColumn("最終接触", help="YYYY-MM-DD"),
            "notes":         st.column_config.TextColumn("notes", width="large"),
        },
        key="ai_editor",
    )
    if st.button("💾 保存", type="primary", key="ai_save"):
        ins, upd, dels = _save_ai_changes(edited, f)
        parts = []
        if ins:  parts.append(f"追加 {ins} 件")
        if upd:  parts.append(f"更新 {upd} 件")
        if dels: parts.append(f"削除 {dels} 件")
        st.success("・".join(parts)) if parts else st.info("変更はありませんでした。")
        st.rerun()


# ---- Tab 3: 統括 (people = 名刺) ---------------------------------------------
def _meishi_intake_section():
    """複数枚アップロード → Gemini 抽出 → レビュー・修正 → 保存。"""
    st.subheader("📸 名刺インテーク（画像 → 抽出 → 保存）")

    gemini_key = st.secrets.get("GEMINI_API_KEY", "")
    if not gemini_key:
        st.warning(
            "⚠️ Secrets に GEMINI_API_KEY が設定されていません。"
            "Google AI Studio で API key を発行し、Streamlit Cloud の Secrets に追加してください。"
        )

    uploads = st.file_uploader(
        "📎 名刺画像をまとめてドラッグ&ドロップ or 選択（**複数枚OK**・Cmd/Ctrl+Click で複数選択）",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        key="meishi_uploads",
        help="1回のアップロードで複数枚を同時に選べます。全部まとめて Gemini に投げて JSON で抽出します。",
    )

    if uploads:
        n = len(uploads)
        st.caption(f"✅ **{n} 枚** アップロード済み・合計 {sum(len(u.getvalue()) for u in uploads)/1024:.0f} KB")
        if n > 15:
            st.warning(f"⚠️ {n} 枚は多すぎるかも（Gemini がタイムアウトする可能性）。10 枚以下推奨。")
        # サムネイル一覧（最大 10 枚まで表示）
        with st.expander(f"📸 プレビュー ({n} 枚)", expanded=False):
            preview_cols = st.columns(min(5, n))
            for i, u in enumerate(uploads[:10]):
                with preview_cols[i % 5]:
                    st.image(u.getvalue(), caption=u.name, use_container_width=True)
            if n > 10:
                st.caption(f"... 他 {n - 10} 枚")

    # まとめて紐付け（一括で related_store / related_ai_contact を設定）
    stores_df = db.fetch_stores()
    ai_df = db.fetch_ai_contacts()
    store_map = {"（紐付けなし）": None}
    for _, r in stores_df.iterrows():
        label = f"{r['name']}（{r.get('area_cluster') or ''}）"
        store_map[label] = r["place_id"]
    ai_map = {"（紐付けなし）": None}
    for _, r in ai_df.iterrows():
        ai_map[str(r["company"])] = int(r["id"])

    c1, c2 = st.columns(2)
    linked_store = c1.selectbox("この名刺群 → 職人 (店)", list(store_map.keys()), key="meishi_link_store")
    linked_ai    = c2.selectbox("この名刺群 → AI (会社)",   list(ai_map.keys()),    key="meishi_link_ai")

    can_extract = bool(uploads) and bool(gemini_key)
    btn_label = f"🤖 {len(uploads)} 枚をまとめて抽出" if uploads else "🤖 抽出する"
    if st.button(btn_label, type="primary", disabled=not can_extract, key="meishi_extract"):
        model_name = st.secrets.get("GEMINI_MODEL", gemini.MODEL_DEFAULT)
        with st.spinner(f"{len(uploads)} 枚を Gemini ({model_name}) で解析中..."):
            images = [u.read() for u in uploads]
            try:
                extracted = gemini.extract_meishi_batch(gemini_key, images, model=model_name)
            except Exception as e:
                st.error(f"抽出失敗: {e}")
                extracted = []
        # 画像枚数と結果件数が不一致なら警告
        if len(extracted) != len(uploads):
            st.warning(f"⚠️ 画像 {len(uploads)} 枚に対し抽出 {len(extracted)} 件でした（不一致）。")
        # sensible defaults
        for r in extracted:
            r.setdefault("related_store_place_id", store_map.get(linked_store))
            r.setdefault("related_ai_contact_id",  ai_map.get(linked_ai))
            r.setdefault("source", "名刺スキャン")
            r.setdefault("memo", "")
        st.session_state["meishi_draft"] = extracted

    draft = st.session_state.get("meishi_draft", [])
    if draft:
        st.markdown("### レビュー・修正して保存")
        draft_df = pd.DataFrame(draft)
        for c in ["name", "kana", "company", "title", "email", "phone",
                  "related_store_place_id", "related_ai_contact_id", "memo", "source"]:
            if c not in draft_df.columns:
                draft_df[c] = None
        # NumberColumn の型互換 (nullable Int64) に揃える
        if "related_ai_contact_id" in draft_df:
            draft_df["related_ai_contact_id"] = pd.to_numeric(
                draft_df["related_ai_contact_id"], errors="coerce"
            ).astype("Int64")
        edited = st.data_editor(
            draft_df,
            hide_index=True,
            use_container_width=True,
            num_rows="dynamic",
            column_order=[
                "name", "kana", "company", "title", "email", "phone",
                "memo", "related_store_place_id", "related_ai_contact_id", "source",
            ],
            column_config={
                "name": st.column_config.TextColumn("氏名", required=True),
                "kana": st.column_config.TextColumn("ふりがな"),
                "company": st.column_config.TextColumn("会社"),
                "title": st.column_config.TextColumn("肩書"),
                "email": st.column_config.TextColumn("email"),
                "phone": st.column_config.TextColumn("電話"),
                "memo":  st.column_config.TextColumn("メモ", width="large"),
                "related_store_place_id": st.column_config.TextColumn("→ store place_id"),
                "related_ai_contact_id":  st.column_config.NumberColumn("→ ai_contacts id"),
                "source": st.column_config.TextColumn("source"),
            },
            key="meishi_editor",
        )
        c1, c2 = st.columns(2)
        if c1.button("💾 全部を people に保存", type="primary", key="meishi_save"):
            n = 0
            for _, row in edited.iterrows():
                rd = row.to_dict()
                if not rd.get("name"):
                    continue
                payload = {}
                for k in db.PEOPLE_EDITABLE:
                    v = rd.get(k)
                    if pd.notna(v) and v not in ("", None):
                        payload[k] = v
                payload.setdefault("status", "active")
                payload.setdefault("source", "名刺スキャン")
                db.insert_person(payload)
                n += 1
            st.success(f"{n} 件を people に保存しました。")
            st.session_state.pop("meishi_draft", None)
            st.rerun()
        if c2.button("🗑️ ドラフトを破棄", key="meishi_discard"):
            st.session_state.pop("meishi_draft", None)
            st.rerun()


def _people_list_section():
    st.subheader("📋 people 一覧（編集して保存）")
    df = db.fetch_people()
    if df.empty:
        st.info("まだ登録された人がいません。上のインテークで追加してください。")
        return

    with st.expander("🔍 フィルタ", expanded=False):
        f_status = st.multiselect("状態", db.PEOPLE_STATUS_VALUES, default=["active"], key="ppl_status")
        f_company = st.text_input("会社 部分一致", "", key="ppl_company")
        if st.button("🔄 最新を取得", key="ppl_refresh"):
            st.rerun()

    f = df.copy()
    if f_status:
        f = f[f["status"].isin(f_status)]
    if f_company and "company" in f:
        f = f[f["company"].fillna("").str.contains(f_company, case=False, na=False)]

    view_cols = [
        "id", "name", "kana", "company", "title", "email", "phone",
        "related_store_place_id", "related_ai_contact_id",
        "memo", "source", "status",
    ]
    for c in view_cols:
        if c not in f.columns:
            f[c] = None

    edited = st.data_editor(
        f[view_cols],
        hide_index=True,
        use_container_width=True,
        num_rows="dynamic",
        column_order=view_cols,
        column_config={
            "id": st.column_config.NumberColumn("id", disabled=True, width="small"),
            "name": st.column_config.TextColumn("氏名", required=True),
            "kana": st.column_config.TextColumn("ふりがな"),
            "company": st.column_config.TextColumn("会社"),
            "title": st.column_config.TextColumn("肩書"),
            "email": st.column_config.TextColumn("email"),
            "phone": st.column_config.TextColumn("電話"),
            "related_store_place_id": st.column_config.TextColumn("→ store"),
            "related_ai_contact_id":  st.column_config.NumberColumn("→ ai"),
            "memo": st.column_config.TextColumn("メモ", width="large"),
            "source": st.column_config.TextColumn("source"),
            "status": st.column_config.SelectboxColumn(
                "状態", options=db.PEOPLE_STATUS_VALUES, required=True, width="small"),
        },
        key="ppl_editor",
    )
    if st.button("💾 保存", type="primary", key="ppl_save"):
        orig_by_id = {int(r["id"]): r for _, r in f.iterrows() if pd.notna(r.get("id"))}
        edited_ids = {int(r["id"]) for _, r in edited.iterrows() if pd.notna(r.get("id"))}
        ins = upd = dels = 0
        for _, row in edited.iterrows():
            rd = row.to_dict()
            if pd.isna(rd.get("id")):
                if not rd.get("name"):
                    continue
                payload = {k: v for k, v in rd.items() if k in db.PEOPLE_EDITABLE and pd.notna(v) and v != ""}
                payload.setdefault("status", "active")
                payload.setdefault("source", "手入力")
                db.insert_person(payload)
                ins += 1
            else:
                rid = int(rd["id"])
                old = orig_by_id.get(rid)
                if old is None:
                    continue
                patch = {}
                for c in db.PEOPLE_EDITABLE:
                    new = None if pd.isna(rd.get(c)) else rd.get(c)
                    oldv = None if pd.isna(old.get(c)) else old.get(c)
                    if str(new or "") != str(oldv or ""):
                        patch[c] = new
                if patch:
                    patch["id"] = rid
                    db.upsert_person(patch)
                    upd += 1
        for orig_id in orig_by_id:
            if orig_id not in edited_ids:
                db.delete_person(int(orig_id))
                dels += 1
        parts = []
        if ins:  parts.append(f"追加 {ins} 件")
        if upd:  parts.append(f"更新 {upd} 件")
        if dels: parts.append(f"削除 {dels} 件")
        st.success("・".join(parts)) if parts else st.info("変更はありませんでした。")
        st.rerun()


def render_people_tab():
    _meishi_intake_section()
    st.divider()
    _people_list_section()


# ---- app --------------------------------------------------------------------
def main():
    st.title("📇 Minamoto 統括CRM")
    tab_ai, tab_stores, tab_people = st.tabs(
        ["🤝 AI (買い手)", "🗺️ 職人 (店)", "📇 統括 (名刺)"]
    )
    with tab_ai:
        render_ai_tab()
    with tab_stores:
        render_stores_tab()
    with tab_people:
        render_people_tab()


if gate():
    main()
