"""
CleverTap Campaign Scheduler — mobile-friendly web form.

Run locally:
    streamlit run app.py

Deploy for free (so you can use it from your phone) via Streamlit
Community Cloud — see the deployment guide provided alongside this file.

Credentials live in Streamlit's "secrets" (st.secrets), NOT in this file,
so they're never exposed in the page or in your GitHub repo.
"""

import json
import os
from datetime import date, datetime
from datetime import time as dtime

import requests
import streamlit as st

st.set_page_config(page_title="Campaign Scheduler", page_icon="📣", layout="centered")

TZ_ABBREVIATIONS = {
    "IST", "GMT", "UTC", "BST", "EST", "EDT", "CST", "CDT", "MST", "MDT",
    "PST", "PDT", "CET", "CEST", "AEST", "AEDT", "SGT", "IDT",
}


# --------------------------------------------------------------------------
# CleverTap API helpers
# --------------------------------------------------------------------------

def post_campaign(account_id: str, passcode: str, region: str, payload: dict) -> dict:
    url = f"https://{region}.api.clevertap.com/1/targets/create.json"
    headers = {
        "X-CleverTap-Account-Id": account_id,
        "X-CleverTap-Passcode": passcode,
        "Content-Type": "application/json",
    }
    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
    try:
        data = resp.json()
    except ValueError:
        resp.raise_for_status()
        raise RuntimeError(f"Non-JSON response: {resp.text}")
    if data.get("status") == "fail":
        raise RuntimeError(f"CleverTap error (code {data.get('code')}): {data.get('error')}")
    return data


def build_push_content(title: str, body: str, buttons: list, image_url: str) -> dict:
    content: dict = {"title": title, "body": body}
    if buttons:
        content["wzrk_acts"] = [
            {"l": b["label"], "dl": b["url"], "id": f"btn{i + 1}"}
            for i, b in enumerate(buttons)
        ]
    if image_url:
        content["background_image"] = image_url  # Android
        ios = content.setdefault("platform_specific", {}).setdefault("ios", {})
        ios["mutable-content"] = "true"
        ios["ct_mediaUrl"] = image_url
    return content


def build_webpush_content(
    title: str, body: str, buttons: list, deep_link: str, icon_url: str, image_url: str
) -> dict:
    platform_specific: dict = {}
    for browser in ("chrome", "firefox", "safari"):
        entry: dict = {"ttl": 10}
        if deep_link:
            entry["deep_link"] = deep_link
        if icon_url and browser in ("chrome", "firefox"):
            entry["icon"] = icon_url
        if image_url and browser == "chrome":
            entry["image"] = image_url
        if buttons and browser == "chrome":
            entry["require_interaction"] = True
            for i, b in enumerate(buttons[:2], start=1):
                entry[f"cta_title{i}"] = b["label"]
                entry[f"cta_link{i}"] = b["url"]
                btn_icon = b.get("icon") or icon_url
                if btn_icon:
                    entry[f"cta_iconlink{i}"] = btn_icon
        platform_specific[browser] = entry
    return {"title": title, "body": body, "platform_specific": platform_specific}


# --------------------------------------------------------------------------
# Match-info parsing helpers (same logic as the CLI wizard)
# --------------------------------------------------------------------------

def parse_match_block(text: str) -> dict:
    fields = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip().lower()] = value.strip()
    return fields


def build_title_body(fields: dict) -> tuple[str, str]:
    event = fields.get("event", "").strip()
    match_no = fields.get("match no", "").strip()
    date_ = fields.get("date", "").strip()
    time_ = fields.get("time", "").strip()
    venue = fields.get("venue", "").strip()
    key_msg = fields.get("key msg", "").strip()

    title = event or "Match Alert"
    if match_no:
        title = f"{title} – {match_no}"

    parts = []
    if key_msg:
        parts.append(key_msg)
    when_where = ", ".join(p for p in [f"{date_} {time_}".strip(), venue] if p)
    if when_where:
        parts.append(f"({when_where})")
    body = " ".join(parts).strip() or "Don't miss this match!"
    return title, body


def to_date_obj(date_str: str):
    for fmt in ("%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


def to_time_obj(time_str: str):
    parts = time_str.strip().split()
    if parts and parts[-1].upper() in TZ_ABBREVIATIONS:
        cleaned = " ".join(parts[:-1])
    else:
        cleaned = time_str.strip()
    for fmt in ("%I:%M %p", "%H:%M"):
        try:
            return datetime.strptime(cleaned, fmt).time()
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------
# Load brand accounts from Streamlit secrets
# --------------------------------------------------------------------------

def load_accounts() -> dict:
    # Works on Streamlit Community Cloud (secrets set via their Secrets UI)
    try:
        accounts = {k: dict(v) for k, v in st.secrets["accounts"].items()}
        if accounts:
            return accounts
    except Exception:
        pass
    # Works on Hugging Face Spaces / Render / anywhere else: set ONE secret
    # named CLEVERTAP_ACCOUNTS_JSON containing a JSON object, e.g.
    # {"BrandA": {"account_id": "...", "passcode": "...", "region": "eu1"}}
    raw = os.environ.get("CLEVERTAP_ACCOUNTS_JSON")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            st.error("CLEVERTAP_ACCOUNTS_JSON is not valid JSON — check for typos/missing commas.")
    return {}


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

st.title("📣 Campaign Scheduler")

accounts = load_accounts()
if not accounts:
    st.error(
        "No brand accounts configured yet. Add them under **Settings → Secrets** "
        "in Streamlit Cloud (see the setup guide you were given)."
    )
    st.stop()

brand = st.selectbox("Brand", list(accounts.keys()))
channel = st.radio("Channel", ["Mobile Push", "Web Push"], horizontal=True)
is_webpush = channel == "Web Push"

st.subheader("Match info")
raw_block = st.text_area(
    "Paste your match info block",
    height=160,
    placeholder=(
        "Event: Team A vs Team B\n"
        "Tournament: Some League 2026\n"
        "Match No: 19th Match\n"
        "Date: 03 Aug 2026\n"
        "Time: 11:00 PM IST\n"
        "Venue: Some Stadium\n"
        "Key Msg: Some hook line here"
    ),
)
fields = parse_match_block(raw_block) if raw_block else {}
suggested_title, suggested_body = build_title_body(fields) if fields else ("", "")

title = st.text_input("Title", value=suggested_title)
body = st.text_area("Body", value=suggested_body, height=80)
default_name = f"{fields.get('event', '')} {fields.get('match no', '')}".strip() or "New Campaign"
campaign_name = st.text_input("Campaign name (shown in CleverTap dashboard)", value=default_name)

st.subheader("Action buttons (optional)")
max_buttons = 2 if is_webpush else 3
buttons = []
for i in range(max_buttons):
    with st.expander(f"Button {i + 1}", expanded=(i == 0)):
        label = st.text_input("Label", key=f"btn_label_{i}", placeholder="e.g. Predict Now")
        url = st.text_input("URL", key=f"btn_url_{i}", placeholder="https://...")
        icon = ""
        if is_webpush:
            icon = st.text_input(
                "Icon URL (recommended — Chrome may not show the button without one)",
                key=f"btn_icon_{i}",
                placeholder="https://.../icon.png",
            )
        if label and url:
            b = {"label": label, "url": url}
            if icon:
                b["icon"] = icon
            buttons.append(b)

st.subheader("Media")
image_url = st.text_input(
    "Image URL (optional)",
    help="Android big-picture / iOS rich media for Mobile Push; banner image for Chrome web push.",
)
deep_link = ""
notif_icon = ""
if is_webpush:
    default_deep_link = buttons[0]["url"] if buttons else ""
    deep_link = st.text_input(
        "Deep link (required — Safari mandates this)", value=default_deep_link
    )
    notif_icon = st.text_input("Notification icon URL (optional)")

st.subheader("Schedule")
send_mode = st.radio("When should this be sent?", ["Send now", "Schedule for later"], horizontal=True)
when: object = "now"
if send_mode == "Schedule for later":
    default_date = to_date_obj(fields["date"]) if fields.get("date") else None
    default_time = to_time_obj(fields["time"]) if fields.get("time") else None
    col1, col2 = st.columns(2)
    with col1:
        sched_date = st.date_input("Date", value=default_date or date.today())
    with col2:
        sched_time = st.time_input("Time", value=default_time or dtime(hour=9, minute=0))
    st.caption(
        "⏱️ Interpreted in your CleverTap account's default timezone "
        "(Dashboard → Settings → General)."
    )
    when = {
        "type": "later",
        "delivery_date_time": [f"{sched_date.strftime('%Y%m%d')} {sched_time.strftime('%H:%M')}"],
        "delivery_timezone": "account",
    }

st.divider()
col_a, col_b = st.columns(2)
estimate_clicked = col_a.button("🔍 Estimate reach", use_container_width=True)
send_clicked = col_b.button("🚀 Schedule / Send", type="primary", use_container_width=True)

if estimate_clicked or send_clicked:
    if not title.strip() or not body.strip():
        st.error("Title and body are required.")
        st.stop()
    if is_webpush and not deep_link.strip():
        st.error("Deep link is required for Web Push (Safari mandates it).")
        st.stop()

    acc = accounts[brand]
    account_id = acc["account_id"]
    passcode = acc["passcode"]
    region = acc.get("region", "eu1")

    if is_webpush:
        content = build_webpush_content(title, body, buttons, deep_link, notif_icon, image_url)
        target_mode = "webpush"
        extra: dict = {}
    else:
        content = build_push_content(title, body, buttons, image_url)
        target_mode = "push"
        extra = {"devices": ["ios", "android"]}

    payload = {
        "name": campaign_name,
        "target_mode": target_mode,
        "content": content,
        "where": {},
        "when": when,
        "estimate_only": estimate_clicked,
        "draft": False,
    }
    payload.update(extra)

    try:
        with st.spinner("Talking to CleverTap..."):
            result = post_campaign(account_id, passcode, region, payload)
        st.success("Estimated reach:" if estimate_clicked else "Scheduled successfully!")
        st.json(result)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Error: {exc}")
