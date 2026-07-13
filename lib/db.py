"""Supabase client + per-table fetch/save helpers.

stores (既存・職人 502件) には破壊的変更を加えない。
ai_contacts / people は新テーブル (2026-07-13 migration)。
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
from supabase import Client, create_client


@st.cache_resource
def client() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


# ---- stores (職人) -----------------------------------------------------------
STORE_STATUS_VALUES = ["未訪問", "訪問済", "前向き", "確定", "断り"]
STORE_EDITABLE = ["status", "visit_date", "memo"]


def fetch_stores() -> pd.DataFrame:
    rows = client().table("stores").select("*").order("priority_rank").execute().data
    df = pd.DataFrame(rows)
    for c in ("lat", "lng"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in (*STORE_EDITABLE, "owner_name", "owner_kana", "category"):
        if c not in df:
            df[c] = None
    return df


def update_store(place_id: str, patch: dict) -> None:
    patch["updated_at"] = pd.Timestamp.utcnow().isoformat()
    client().table("stores").update(patch).eq("place_id", place_id).execute()


# ---- ai_contacts (会社単位=買い手) --------------------------------------------
AI_STATUS_VALUES = [
    "not_contacted", "connection_sent", "message_sent",
    "connected", "success", "rejected",
]
AI_EDITABLE = [
    "company", "field", "status", "source", "website", "linkedin_url",
    "primary_contact_name", "primary_contact_role", "primary_contact_email",
    "last_contact_date", "notes",
]


def fetch_ai_contacts() -> pd.DataFrame:
    rows = client().table("ai_contacts").select("*").order("id").execute().data
    return pd.DataFrame(rows)


def upsert_ai_contact(row: dict) -> dict:
    """id があれば update、なければ insert。"""
    payload = {k: (None if pd.isna(v) else v) for k, v in row.items() if k != "id"}
    if row.get("id"):
        return client().table("ai_contacts").update(payload).eq("id", int(row["id"])).execute().data[0]
    return client().table("ai_contacts").insert(payload).execute().data[0]


def delete_ai_contact(cid: int) -> None:
    client().table("ai_contacts").delete().eq("id", int(cid)).execute()


# ---- people (名刺=個人) ------------------------------------------------------
PEOPLE_STATUS_VALUES = ["active", "archived"]
PEOPLE_EDITABLE = [
    "name", "kana", "company", "title", "email", "phone",
    "related_store_place_id", "related_ai_contact_id", "memo", "source", "status",
]


def fetch_people() -> pd.DataFrame:
    rows = client().table("people").select("*").order("id", desc=True).execute().data
    return pd.DataFrame(rows)


def upsert_person(row: dict) -> dict:
    payload = {k: (None if pd.isna(v) else v) for k, v in row.items() if k != "id"}
    if row.get("id"):
        return client().table("people").update(payload).eq("id", int(row["id"])).execute().data[0]
    return client().table("people").insert(payload).execute().data[0]


def insert_person(row: dict) -> dict:
    payload = {k: (None if pd.isna(v) else v) for k, v in row.items() if k not in ("id",)}
    return client().table("people").insert(payload).execute().data[0]


def delete_person(pid: int) -> None:
    client().table("people").delete().eq("id", int(pid)).execute()
