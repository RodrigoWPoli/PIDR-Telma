"""
dashboard.py
Streamlit real-time fault detection dashboard for the TELMA platform.

Usage:
    pip install streamlit plotly
    streamlit run dashboard.py
"""

import csv as csv_module
import glob
import os
import socket
import subprocess
import time
import pandas as pd
import pymongo
import streamlit as st
import plotly.graph_objects as go
from datetime import datetime
from dateutil import parser as dateutil_parser
from update_ontology import infer_state, load_ontology, update_data_properties


# ── VPN check ─────────────────────────────────────────────────────────────────
def check_vpn() -> tuple[bool, str]:
    try:
        s = socket.create_connection(("100.65.63.65", 4840), timeout=2)
        s.close()
        return True, "VPN connected · PLC reachable"
    except OSError:
        return False, "VPN disconnected · PLC unreachable"


# ── Configuration ──────────────────────────────────────────────────────────────
MONGO_URI         = "mongodb://localhost:27017/"
DATABASE_NAME     = "telma"
COLLECTION_NAME   = "data"
REFRESH_INTERVAL  = 2
HISTORY_POINTS    = 60
MAX_STATE_HISTORY = 20
ALERT_THRESHOLD   = 21.73
ALARM_THRESHOLD   = 23.85

STATE_CONFIG = {
    "Healthy": {"color": "#1D9E75", "bg": "#E1F5EE"},
    "Alert":   {"color": "#BA7517", "bg": "#FAEEDA"},
    "Alarm":   {"color": "#E24B4A", "bg": "#FCEBEB"},
    "Faulty":  {"color": "#444441", "bg": "#F1EFE8"},
    "Stopped": {"color": "#888780", "bg": "#F1EFE8"},
    None:      {"color": "#888780", "bg": "#F1EFE8"},
}

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TELMA — Fault Detection",
    page_icon="⚙",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
.block-container { padding-top: 1.5rem; padding-bottom: 1rem; max-width: 1200px; }
.state-card { border: 1px solid #e5e5e5; border-radius: 12px; padding: 2rem; text-align: center; margin-bottom: 0.5rem; }
.state-label { font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: #888; margin-bottom: 0.5rem; }
.state-value { font-size: 52px; font-weight: 500; line-height: 1.1; margin-bottom: 0.4rem; }
.state-sub { font-size: 13px; color: #888; }
.panel-title { font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: #888; margin-bottom: 0.75rem; }
.chain-item { display: flex; align-items: flex-start; gap: 10px; margin-bottom: 10px; font-size: 13px; }
.chain-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; margin-top: 3px; }
.chain-text { font-weight: 500; }
.chain-sub { color: #888; font-size: 11px; }
.hist-item { display: flex; align-items: center; gap: 10px; font-size: 12px; padding: 5px 0; border-bottom: 0.5px solid #f0f0f0; }
.hist-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.hist-time { color: #888; min-width: 55px; font-family: monospace; }
.signal-row { display: flex; justify-content: space-between; font-size: 13px; padding: 5px 0; border-bottom: 0.5px solid #f5f5f5; }
.signal-label { color: #888; }
.signal-true { color: #1D9E75; font-weight: 500; }
.signal-false { color: #888; }
div[data-testid="metric-container"] { background: #f8f8f7; border-radius: 8px; padding: 0.75rem 1rem; }
[data-testid="stMetricLabel"] { font-size: 12px !important; color: #888 !important; }
[data-testid="stMetricValue"] { font-size: 24px !important; font-weight: 500 !important; }
</style>
""", unsafe_allow_html=True)


# ── Data helpers ───────────────────────────────────────────────────────────────
@st.cache_resource
def get_mongo():
    return pymongo.MongoClient(MONGO_URI)

@st.cache_resource
def get_ontology():
    onto, _ = load_ontology()
    return onto

def get_latest_values():
    col = get_mongo()[DATABASE_NAME][COLLECTION_NAME]
    variables = [
        "Otr_acc", "Rfrd_acc", "Ent_bob_cour", "Ent_bob_abou",
        "En_Production", "TempMoteur_acc", "Lcr_acc", "Uop_acc",
        "Courroie_accu_tendue", "Courroie_accu_detendue",
        "Otr_av", "Rfrd_av", "TempMoteur_av", "Lcr_av", "Uop_av",
        "Cpt_nb_piece", "Cpt_nb_bobine", "Nombre_tours", "Dim_piece",
        "CourantA", "CourantB", "CourantC", "CourantTot",
        "Ent_au", "diActTorque", "diActlVelo",
    ]
    latest = {}
    for var in variables:
        doc = col.find_one({var: {"$exists": True}},
                           sort=[(var + ".SourceTimestamp", pymongo.DESCENDING)])
        if doc and var in doc:
            latest[var] = doc[var]["value"]
    return latest

def get_otr_history(n=HISTORY_POINTS):
    col  = get_mongo()[DATABASE_NAME][COLLECTION_NAME]
    docs = list(col.find({"Otr_acc": {"$exists": True}}, {"Otr_acc": 1})
                   .sort("Otr_acc.SourceTimestamp", pymongo.DESCENDING).limit(n))
    docs.reverse()
    return [(d["Otr_acc"]["SourceTimestamp"], float(d["Otr_acc"]["value"])) for d in docs]

def sig_row(label, value, true_label="True", false_label="False"):
    cls  = "signal-true" if value else "signal-false"
    text = true_label if value else false_label
    return (f'<div class="signal-row">'
            f'<span class="signal-label">{label}</span>'
            f'<span class="{cls}">{text}</span></div>')


# ── Hysteresis filter ──────────────────────────────────────────────────────────
HYSTERESIS_N = 3

def apply_hysteresis(raw_state: str) -> str:
    counts = st.session_state.consecutive_counts
    if raw_state in ("Alert", "Alarm"):
        counts[raw_state] += 1
        other = "Alarm" if raw_state == "Alert" else "Alert"
        counts[other] = 0
        if counts[raw_state] >= HYSTERESIS_N:
            st.session_state.confirmed_state = raw_state
    else:
        counts["Alert"] = 0
        counts["Alarm"] = 0
        st.session_state.confirmed_state = raw_state
    return st.session_state.confirmed_state


# ── Replay helpers ─────────────────────────────────────────────────────────────
REPLAY_BOOL_VARS = {"Ent_bob_cour", "Ent_bob_abou", "En_Production", "Ent_au",
                    "Courroie_accu_tendue", "Courroie_accu_detendue"}
REPLAY_WATCHED = [
    "Otr_acc", "Rfrd_acc", "Ent_bob_cour", "Ent_bob_abou", "En_Production",
    "TempMoteur_acc", "Lcr_acc", "Uop_acc", "Courroie_accu_tendue", "Courroie_accu_detendue",
    "Otr_av", "Rfrd_av", "TempMoteur_av", "Lcr_av", "Uop_av",
    "Cpt_nb_piece", "Cpt_nb_bobine", "Nombre_tours", "Dim_piece",
    "CourantA", "CourantB", "CourantC", "CourantTot", "Ent_au", "diActTorque", "diActlVelo",
]
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def list_csv_files() -> list[str]:
    return sorted(glob.glob(os.path.join(DATA_DIR, "collection_*.csv")))


def load_csv_rows(path: str) -> list[dict]:
    rows = []
    with open(path, newline="") as fh:
        for row in csv_module.DictReader(fh):
            parsed: dict = {}
            ts_str = row.get("timestamp", "")
            if ts_str:
                try:
                    parsed["_ts"] = dateutil_parser.parse(ts_str)
                except Exception:
                    parsed["_ts"] = None
            for col, raw in row.items():
                if col == "timestamp" or raw == "":
                    continue
                if col in REPLAY_BOOL_VARS:
                    parsed[col] = raw.strip().lower() in ("true", "1", "yes")
                else:
                    try:
                        parsed[col] = float(raw)
                    except ValueError:
                        parsed[col] = raw
            rows.append(parsed)
    return rows


def load_mongo_rows() -> list[dict]:
    client = pymongo.MongoClient(MONGO_URI)
    docs = list(client[DATABASE_NAME][COLLECTION_NAME].find().sort("_id", pymongo.ASCENDING))
    client.close()
    rows = []
    for doc in docs:
        parsed: dict = {"_ts": None}
        for var in REPLAY_WATCHED:
            if var in doc:
                parsed[var] = doc[var]["value"]
        if len(parsed) > 1:
            rows.append(parsed)
    return rows


# ── Session state ──────────────────────────────────────────────────────────────
if "state_history" not in st.session_state:
    st.session_state.state_history = []
if "last_state" not in st.session_state:
    st.session_state.last_state = None
if "consecutive_counts" not in st.session_state:
    st.session_state.consecutive_counts = {"Alert": 0, "Alarm": 0}
if "confirmed_state" not in st.session_state:
    st.session_state.confirmed_state = "Healthy"
if "collection_process" not in st.session_state:
    st.session_state.collection_process = None
if "collection_log" not in st.session_state:
    st.session_state.collection_log = []
if "ontology_log" not in st.session_state:
    st.session_state.ontology_log = []
if "replay_running" not in st.session_state:
    st.session_state.replay_running = False
if "replay_rows" not in st.session_state:
    st.session_state.replay_rows = []
if "replay_index" not in st.session_state:
    st.session_state.replay_index = 0
if "replay_results" not in st.session_state:
    st.session_state.replay_results = []
if "replay_prev_values" not in st.session_state:
    st.session_state.replay_prev_values = {}
if "replay_state_counts" not in st.session_state:
    st.session_state.replay_state_counts = {}
if "replay_interval" not in st.session_state:
    st.session_state.replay_interval = 4.0
if "replay_onto" not in st.session_state:
    st.session_state.replay_onto = None
if "auto_update_ontology" not in st.session_state:
    st.session_state.auto_update_ontology = True
if "monitor_active" not in st.session_state:
    st.session_state.monitor_active = True


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Controls")
    st.markdown("<hr style='margin:0.5rem 0;'>", unsafe_allow_html=True)

    st.markdown("**Network**")
    vpn_ok, vpn_msg = check_vpn()
    if vpn_ok:
        st.success(vpn_msg, icon="✅")
    else:
        st.error(vpn_msg, icon="🔴")

    st.markdown("<hr style='margin:0.75rem 0;'>", unsafe_allow_html=True)

    st.markdown("**Data collection**")
    proc = st.session_state.collection_process
    is_running = proc is not None and proc.poll() is None

    if is_running:
        st.success("Collecting — running", icon="⏺️")
        if st.button("Stop collection", use_container_width=True):
            proc.terminate()
            proc.wait(timeout=3)
            st.session_state.collection_process = None
            st.session_state.collection_log.insert(
                0, f"{datetime.now().strftime('%H:%M:%S')} — stopped (wait ~10s before restarting)")
            st.rerun()
    else:
        if proc is not None:
            exit_code = proc.poll()
            if exit_code != 0:
                st.warning("Collection stopped unexpectedly. Check data/collection.log", icon="⚠️")
            st.session_state.collection_log.insert(
                0, f"{datetime.now().strftime('%H:%M:%S')} — finished (exit {exit_code})")
            st.session_state.collection_process = None

        if st.button("Start collection", use_container_width=True,
                     type="primary", disabled=not vpn_ok):
            import sys
            script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "data_collection.py")
            p = subprocess.Popen(
                [sys.executable, script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            st.session_state.collection_process = p
            st.session_state.collection_log.insert(
                0, f"{datetime.now().strftime('%H:%M:%S')} — started")
            st.rerun()

    if st.session_state.collection_log:
        for entry in st.session_state.collection_log[:4]:
            st.caption(entry)

    st.markdown("<hr style='margin:0.75rem 0;'>", unsafe_allow_html=True)

    st.markdown("**Monitor**")
    st.toggle("Monitor active", key="monitor_active")

    if st.session_state.monitor_active:
        st.markdown("**Ontology**")
        st.toggle("Auto-update ontology", key="auto_update_ontology",
                  help="Keep OWL individuals in sync with latest MongoDB data")

    if st.session_state.ontology_log:
        for entry in st.session_state.ontology_log[:4]:
            st.caption(entry)

    st.markdown("<hr style='margin:0.75rem 0;'>", unsafe_allow_html=True)

    st.markdown("**Settings**")
    REFRESH_INTERVAL = st.slider(
        "Refresh interval (s)", min_value=1, max_value=10,
        value=REFRESH_INTERVAL, step=1
    )
    if st.button("Clear state history", use_container_width=True):
        st.session_state.state_history = []
        st.session_state.last_state = None
        st.rerun()

    st.markdown("<hr style='margin:0.75rem 0;'>", unsafe_allow_html=True)
    st.caption("TELMA Fault Detection · PIDR n°30")
    st.caption("CRAN / MPSI · Université de Lorraine")


# ── Page header ────────────────────────────────────────────────────────────────
col_title, col_time = st.columns([3, 1])
with col_title:
    st.markdown("### TELMA — fault detection")
    st.markdown("<p style='color:#888;font-size:13px;margin-top:-10px;'>"
                "AccumulatorMotor · bearing deterioration scenario</p>",
                unsafe_allow_html=True)
with col_time:
    st.markdown(f"<p style='text-align:right;color:#888;font-size:12px;"
                f"padding-top:1rem;font-family:monospace;'>"
                f"{datetime.now().strftime('%H:%M:%S')}</p>",
                unsafe_allow_html=True)

st.markdown("<hr style='border:none;border-top:0.5px solid #e5e5e5;margin:0 0 1rem;'>",
            unsafe_allow_html=True)

tab_monitor, tab_data, tab_replay = st.tabs(["Monitor", "Data explorer", "Replay"])


# ── Monitor tab ─────────────────────────────────────────────────────────────────
with tab_monitor:

    @st.fragment(run_every=REFRESH_INTERVAL)
    def monitor_tab():
        if not st.session_state.monitor_active:
            st.markdown("<div style='text-align:center;color:#888;padding:3rem 0;'>"
                        "Monitor is deactivated. Use the sidebar toggle to activate.</div>",
                        unsafe_allow_html=True)
            return

        values = get_latest_values()
        if not values:
            st.warning("No data in MongoDB. Run simulate_data.py or data_collection.py first.")
            return

        if st.session_state.auto_update_ontology:
            onto = get_ontology()
            try:
                update_data_properties(onto, values)
            except Exception:
                st.cache_resource.clear()
                onto = get_ontology()
                try:
                    update_data_properties(onto, values)
                except Exception:
                    pass

        result = infer_state(values)
        state  = apply_hysteresis(result["state"])
        cfg    = STATE_CONFIG.get(state, STATE_CONFIG[None])

        if state != st.session_state.last_state:
            st.session_state.state_history.insert(0, {
                "time":  datetime.now().strftime("%H:%M:%S"),
                "state": state,
                "otr":   values.get("Otr_acc", 0),
                "color": cfg["color"]
            })
            st.session_state.state_history = st.session_state.state_history[:MAX_STATE_HISTORY]
            st.session_state.last_state = state

        otr_val  = float(values.get("Otr_acc", 0))
        coil_str = "coil changing" if result["is_coil_changing"] else "coil not changing"
        prod_str = "in production" if result.get("in_production", True) else "not in production"

        st.markdown(f"""
        <div class="state-card" style="background:{cfg['bg']};border-color:{cfg['color']}33;">
            <div class="state-label">current health state</div>
            <div class="state-value" style="color:{cfg['color']};">{state}</div>
            <div class="state-sub">Otr_acc = {otr_val:.1f} Nm &nbsp;·&nbsp; {coil_str} &nbsp;·&nbsp; {prod_str}</div>
        </div>
        """, unsafe_allow_html=True)

        m1, m2, m3, m4 = st.columns(4)
        with m1: st.metric("Motor torque",  f"{otr_val:.1f} Nm")
        with m2: st.metric("Motor speed",   f"{float(values.get('Rfrd_acc', 0)):.0f} rpm")
        with m3: st.metric("Temperature",   f"{float(values.get('TempMoteur_acc', 0)):.1f} °C")
        with m4: st.metric("Current",       f"{float(values.get('Lcr_acc', 0)):.2f} A")

        st.markdown("<div style='margin-top:0.75rem;'></div>", unsafe_allow_html=True)
        left, right = st.columns(2)

        with left:
            st.markdown("<div class='panel-title'>Otr_acc over time</div>", unsafe_allow_html=True)
            history = get_otr_history()
            if history:
                times = [h[0] for h in history]
                hvals = [h[1] for h in history]

                def bar_colors_with_hysteresis(vals, n=HYSTERESIS_N):
                    colors    = []
                    alert_run = 0
                    alarm_run = 0
                    confirmed = "Healthy"
                    for v in vals:
                        if v > ALARM_THRESHOLD:
                            alarm_run += 1; alert_run = 0
                            if alarm_run >= n: confirmed = "Alarm"
                        elif v > ALERT_THRESHOLD:
                            alert_run += 1; alarm_run = 0
                            if alert_run >= n: confirmed = "Alert"
                        else:
                            alert_run = 0; alarm_run = 0; confirmed = "Healthy"
                        colors.append(
                            "#F09595" if confirmed == "Alarm" else
                            "#FAC775" if confirmed == "Alert" else "#85B7EB"
                        )
                    return colors

                colors = bar_colors_with_hysteresis(hvals)
                fig = go.Figure()
                fig.add_trace(go.Bar(x=times, y=hvals, marker_color=colors,
                                     showlegend=False,
                                     hovertemplate="%{y:.2f} Nm<extra></extra>"))
                fig.add_hline(y=ALERT_THRESHOLD, line_dash="dot", line_color="#BA7517",
                              line_width=1, annotation_text=f"alert {ALERT_THRESHOLD}",
                              annotation_position="right",
                              annotation_font_size=11, annotation_font_color="#BA7517")
                fig.add_hline(y=ALARM_THRESHOLD, line_dash="dot", line_color="#E24B4A",
                              line_width=1, annotation_text=f"alarm {ALARM_THRESHOLD}",
                              annotation_position="right",
                              annotation_font_size=11, annotation_font_color="#E24B4A")
                fig.update_layout(height=220, margin=dict(l=0, r=60, t=10, b=10),
                                  plot_bgcolor="white", paper_bgcolor="white",
                                  xaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
                                  yaxis=dict(showgrid=True, gridcolor="#f0f0f0",
                                             zeroline=False, tickfont_size=11))
                st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})

            st.markdown("<div class='panel-title' style='margin-top:0.5rem;'>Failure chain</div>",
                        unsafe_allow_html=True)
            if result["deviations"] or result["failure_states"]:
                chain = """
                <div class="chain-item">
                    <div class="chain-dot" style="background:#888780;"></div>
                    <div><div class="chain-text">BearingWearByFrictionAndFatigue</div>
                    <div class="chain-sub">primary cause</div></div>
                </div>
                <div style="margin-left:3px;width:0.5px;height:10px;background:#e5e5e5;margin-bottom:4px;"></div>
                <div class="chain-item">
                    <div class="chain-dot" style="background:#BA7517;"></div>
                    <div><div class="chain-text">BearingDeterioration</div>
                    <div class="chain-sub">failure mode</div></div>
                </div>"""
                for dev in result["deviations"].values():
                    chain += (f'<div style="margin-left:3px;width:0.5px;height:10px;'
                              f'background:#e5e5e5;margin-bottom:4px;"></div>'
                              f'<div class="chain-item">'
                              f'<div class="chain-dot" style="background:#E24B4A;"></div>'
                              f'<div><div class="chain-text">{dev}</div>'
                              f'<div class="chain-sub">deviation</div></div></div>')
                for fs in result["failure_states"]:
                    chain += (f'<div class="chain-item">'
                              f'<div class="chain-dot" style="background:#444441;"></div>'
                              f'<div><div class="chain-text">{fs}</div>'
                              f'<div class="chain-sub">failure state</div></div></div>')
                st.markdown(chain, unsafe_allow_html=True)
            else:
                st.markdown("<p style='font-size:13px;color:#888;'>No active failure chain.</p>",
                            unsafe_allow_html=True)

        with right:
            st.markdown("<div class='panel-title'>Signal status</div>", unsafe_allow_html=True)
            st.markdown(
                sig_row("Ent_bob_cour",      values.get("Ent_bob_cour", False),
                        "True — current position", "False") +
                sig_row("Ent_bob_abou",      values.get("Ent_bob_abou", False),
                        "True — changing position", "False") +
                sig_row("Coil changing",     result["is_coil_changing"], "Yes", "No") +
                sig_row("Courroie tendue",   values.get("Courroie_accu_tendue", False),
                        "Yes — tensioned", "No") +
                sig_row("Courroie détendue", values.get("Courroie_accu_detendue", False),
                        "Yes — slack", "No") +
                sig_row("En_Production",     values.get("En_Production", False),
                        "True — in production", "False — stopped"),
                unsafe_allow_html=True
            )

            st.markdown("<div class='panel-title' style='margin-top:1.25rem;'>State history</div>",
                        unsafe_allow_html=True)
            if st.session_state.state_history:
                hist_html = ""
                for item in st.session_state.state_history[:8]:
                    hist_html += (f'<div class="hist-item">'
                                  f'<div class="hist-dot" style="background:{item["color"]};"></div>'
                                  f'<span class="hist-time">{item["time"]}</span>'
                                  f'<span style="font-weight:500;">{item["state"]}</span>'
                                  f'<span style="color:#888;margin-left:auto;">'
                                  f'Otr={float(item["otr"]):.1f}</span></div>')
                st.markdown(hist_html, unsafe_allow_html=True)
            else:
                st.markdown("<p style='font-size:13px;color:#888;'>No state changes yet.</p>",
                            unsafe_allow_html=True)

        st.markdown(f"<p style='text-align:center;color:#ccc;font-size:11px;margin-top:1.5rem;'>"
                    f"auto-refresh every {REFRESH_INTERVAL}s</p>", unsafe_allow_html=True)

        st.markdown("<hr style='border:none;border-top:0.5px solid #e5e5e5;margin:1rem 0 0.5rem;'>",
                    unsafe_allow_html=True)
        st.markdown("<div class='panel-title'>Advance motor</div>", unsafe_allow_html=True)
        a1, a2, a3, a4, a5 = st.columns(5)
        with a1: st.metric("Torque",      f"{float(values.get('Otr_av', 0)):.0f} Nm")
        with a2: st.metric("Speed",       f"{float(values.get('Rfrd_av', 0)):.0f} rpm")
        with a3: st.metric("Temperature", f"{float(values.get('TempMoteur_av', 0)):.1f} °C")
        with a4: st.metric("Current",     f"{float(values.get('Lcr_av', 0)):.2f} A")
        with a5: st.metric("Voltage",     f"{float(values.get('Uop_av', 0)):.0f} V")

        st.markdown("<div style='margin-top:0.5rem;'></div>", unsafe_allow_html=True)
        p1, p2 = st.columns(2)

        with p1:
            st.markdown("<div class='panel-title'>Production</div>", unsafe_allow_html=True)
            eu_class = "signal-true" if values.get("Ent_au") else "signal-false"
            eu_text  = "ACTIVE" if values.get("Ent_au") else "OK"
            st.markdown(
                f'<div class="signal-row"><span class="signal-label">Pieces produced</span>'
                f'<span style="font-weight:500;">{int(values.get("Cpt_nb_piece", 0))}</span></div>'
                f'<div class="signal-row"><span class="signal-label">Coils used</span>'
                f'<span style="font-weight:500;">{int(values.get("Cpt_nb_bobine", 0))}</span></div>'
                f'<div class="signal-row"><span class="signal-label">Current turns</span>'
                f'<span style="font-weight:500;">{int(values.get("Nombre_tours", 0))}</span></div>'
                f'<div class="signal-row"><span class="signal-label">Piece dimension</span>'
                f'<span style="font-weight:500;">{int(values.get("Dim_piece", 0))}</span></div>'
                f'<div class="signal-row"><span class="signal-label">Emergency stop</span>'
                f'<span class="{eu_class}">{eu_text}</span></div>',
                unsafe_allow_html=True
            )

        with p2:
            st.markdown("<div class='panel-title'>Electrical (powertag)</div>",
                        unsafe_allow_html=True)
            st.markdown(
                f'<div class="signal-row"><span class="signal-label">Phase A</span>'
                f'<span style="font-weight:500;">{float(values.get("CourantA", 0)):.2f} A</span></div>'
                f'<div class="signal-row"><span class="signal-label">Phase B</span>'
                f'<span style="font-weight:500;">{float(values.get("CourantB", 0)):.2f} A</span></div>'
                f'<div class="signal-row"><span class="signal-label">Phase C</span>'
                f'<span style="font-weight:500;">{float(values.get("CourantC", 0)):.2f} A</span></div>'
                f'<div class="signal-row"><span class="signal-label">Total (A+B+C)</span>'
                f'<span style="font-weight:500;">{float(values.get("CourantTot", 0)):.2f} A</span></div>'
                f'<div class="signal-row"><span class="signal-label">Accu voltage</span>'
                f'<span style="font-weight:500;">{float(values.get("Uop_acc", 0)):.0f} V</span></div>',
                unsafe_allow_html=True
            )

    monitor_tab()


# ── Data explorer tab ──────────────────────────────────────────────────────────
with tab_data:
    col = get_mongo()[DATABASE_NAME][COLLECTION_NAME]
    total_docs = col.count_documents({})

    dc1, dc2, dc3 = st.columns(3)
    with dc1: st.metric("Total documents", f"{total_docs:,}")
    with dc2:
        first = col.find_one({}, sort=[("Otr_acc.SourceTimestamp", 1)])
        if first and "Otr_acc" in first:
            st.metric("First reading", str(first["Otr_acc"]["SourceTimestamp"])[:19])
    with dc3:
        last = col.find_one({}, sort=[("Otr_acc.SourceTimestamp", -1)])
        if last and "Otr_acc" in last:
            st.metric("Latest reading", str(last["Otr_acc"]["SourceTimestamp"])[:19])

    st.markdown("<hr style='border:none;border-top:0.5px solid #e5e5e5;margin:0.5rem 0;'>",
                unsafe_allow_html=True)

    fc1, fc2, fc3 = st.columns([1, 1, 2])
    with fc1:
        n_rows = st.selectbox("Show last N readings", [50, 100, 250, 500, 1000], index=1)
    with fc2:
        var_filter = st.selectbox("Filter by variable", ["All"] + [
            "Otr_acc", "Rfrd_acc", "TempMoteur_acc", "Lcr_acc",
            "Otr_av", "Rfrd_av", "CourantA", "CourantB", "CourantC", "CourantTot",
            "En_Production", "Ent_bob_cour", "Ent_bob_abou",
        ])
    with fc3:
        search_state = st.selectbox("Filter by inferred state",
                                    ["All", "Healthy", "Alert", "Alarm", "Faulty", "Stopped"])

    query = {} if var_filter == "All" else {var_filter: {"$exists": True}}
    docs  = list(col.find(query, sort=[("Otr_acc.SourceTimestamp", -1)]).limit(n_rows))
    docs.reverse()

    VARIABLE_NAMES = [
        "Otr_acc", "Rfrd_acc", "Ent_bob_cour", "Ent_bob_abou", "En_Production",
        "TempMoteur_acc", "Lcr_acc", "Uop_acc", "Courroie_accu_tendue", "Courroie_accu_detendue",
        "Otr_av", "Rfrd_av", "TempMoteur_av", "Lcr_av", "Uop_av",
        "Cpt_nb_piece", "Cpt_nb_bobine", "Nombre_tours", "Dim_piece",
        "CourantA", "CourantB", "CourantC", "CourantTot", "Ent_au",
        "diActTorque", "diActlVelo",
    ]

    rows = []
    for doc in docs:
        row = {}
        ts = None
        for var in VARIABLE_NAMES:
            if var in doc:
                row[var] = doc[var]["value"]
                if ts is None:
                    ts = doc[var].get("SourceTimestamp")
        if row:
            row["timestamp"] = str(ts)[:19] if ts else ""
            r = infer_state(row)
            row["state"] = r["state"]
            rows.append(row)

    if rows:
        df = pd.DataFrame(rows)
        cols = ["timestamp", "state"] + [c for c in df.columns if c not in ("timestamp", "state")]
        df   = df[[c for c in cols if c in df.columns]]

        if search_state != "All":
            df = df[df["state"] == search_state]

        def colour_state(val):
            colours = {
                "Healthy": "background-color:#E1F5EE;color:#0F6E56",
                "Alert":   "background-color:#FAEEDA;color:#854F0B",
                "Alarm":   "background-color:#FCEBEB;color:#A32D2D",
                "Faulty":  "background-color:#F1EFE8;color:#444441",
                "Stopped": "background-color:#F1EFE8;color:#888780",
            }
            return colours.get(val, "")

        styled = df.style.map(colour_state, subset=["state"])
        st.dataframe(styled, width='stretch', height=420,
                     column_config={"timestamp": st.column_config.TextColumn("Timestamp", width=160),
                                    "state":     st.column_config.TextColumn("State", width=90)})
        st.caption(f"Showing {len(df)} of {total_docs:,} documents")

        csv_data = df.to_csv(index=False).encode("utf-8")
        st.download_button("Download as CSV", csv_data,
                           file_name=f"telma_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                           mime="text/csv")
    else:
        st.info("No data found with the current filters.")


# ── Replay tab ─────────────────────────────────────────────────────────────────
with tab_replay:

    # Controls — outside the fragment so Start/Stop work even while replay is running
    st.markdown("<div class='panel-title'>Data source</div>", unsafe_allow_html=True)

    csv_files = list_csv_files()
    csv_names = [os.path.basename(f) for f in csv_files]

    rsc1, rsc2 = st.columns([2, 1])
    with rsc1:
        replay_source = st.radio(
            "Source", ["CSV file", "MongoDB"],
            horizontal=True,
            disabled=st.session_state.replay_running,
            key="replay_source_radio",
        )
    with rsc2:
        replay_interval_ui = st.slider(
            "Interval between rows (s)", 0.0, 10.0,
            value=st.session_state.replay_interval,
            step=0.1,
            disabled=st.session_state.replay_running,
            key="replay_interval_slider",
        )

    if replay_source == "CSV file":
        if csv_names:
            selected_csv_name = st.selectbox(
                "CSV file", csv_names,
                disabled=st.session_state.replay_running,
                key="replay_csv_select",
            )
            selected_csv_path = csv_files[csv_names.index(selected_csv_name)]
        else:
            st.warning("No CSV files found in data/")
            selected_csv_path = None
    else:
        selected_csv_path = None

    rb1, rb2, _ = st.columns([1, 1, 4])
    with rb1:
        start_clicked = st.button(
            "▶ Start", type="primary", use_container_width=True,
            disabled=st.session_state.replay_running or
                     (replay_source == "CSV file" and not selected_csv_path),
        )
    with rb2:
        stop_clicked = st.button(
            "⏹ Stop", use_container_width=True,
            disabled=not st.session_state.replay_running,
        )

    if start_clicked:
        with st.spinner("Loading data…"):
            if replay_source == "CSV file":
                loaded = load_csv_rows(selected_csv_path)
            else:
                loaded = load_mongo_rows()
        onto_r, _ = load_ontology()
        st.session_state.replay_rows         = loaded
        st.session_state.replay_index        = 0
        st.session_state.replay_results      = []
        st.session_state.replay_prev_values  = {}
        st.session_state.replay_state_counts = {}
        st.session_state.replay_interval     = replay_interval_ui
        st.session_state.replay_onto         = onto_r
        st.session_state.replay_running      = True
        st.rerun()

    if stop_clicked:
        st.session_state.replay_running = False
        st.rerun()

    st.markdown("<hr style='border:none;border-top:0.5px solid #e5e5e5;margin:0.75rem 0;'>",
                unsafe_allow_html=True)

    # Fragment auto-reruns at the replay interval while running; static when stopped.
    # run_every=None when not running means no background refreshes.
    _run_every = None
    if st.session_state.replay_running:
        _run_every = max(0.1, st.session_state.replay_interval)

    @st.fragment(run_every=_run_every)
    def replay_display():
        # ── Process next row ───────────────────────────────────────────────────
        if st.session_state.replay_running:
            idx    = st.session_state.replay_index
            rows_r = st.session_state.replay_rows
            if idx < len(rows_r):
                row_r       = rows_r[idx]
                row_values  = {k: v for k, v in row_r.items() if k != "_ts"}
                cur         = dict(st.session_state.replay_prev_values)
                cur.update(row_values)
                st.session_state.replay_prev_values = cur

                try:
                    update_data_properties(st.session_state.replay_onto, cur)
                except Exception:
                    pass
                res = infer_state(cur)

                ts_r = row_r.get("_ts")
                st.session_state.replay_results.append({
                    "row_num":          idx + 1,
                    "state":            res["state"],
                    "otr":              float(cur.get("Otr_acc", 0)),
                    "src_ts":           ts_r.strftime("%H:%M:%S") if ts_r else "",
                    "is_coil_changing": res["is_coil_changing"],
                    "deviations":       res["deviations"],
                    "failure_states":   res["failure_states"],
                })
                if len(st.session_state.replay_results) > 500:
                    st.session_state.replay_results = st.session_state.replay_results[-500:]

                sc = st.session_state.replay_state_counts
                sc[res["state"]] = sc.get(res["state"], 0) + 1
                st.session_state.replay_index += 1
            else:
                st.session_state.replay_running = False

        # ── Display ────────────────────────────────────────────────────────────
        total_r   = len(st.session_state.replay_rows)
        current_r = st.session_state.replay_index

        if total_r > 0:
            status_label = (
                f"Running — row {current_r} / {total_r}"
                if st.session_state.replay_running
                else (f"Complete — {current_r} rows processed"
                      if current_r == total_r
                      else f"Paused at row {current_r} / {total_r}")
            )
            st.progress(current_r / total_r, text=status_label)

        results_r = st.session_state.replay_results
        if results_r:
            last_r       = results_r[-1]
            last_state_r = last_r["state"]
            rcfg         = STATE_CONFIG.get(last_state_r, STATE_CONFIG[None])

            rcard, rdist = st.columns([1, 1])

            with rcard:
                src_ts_label = f"src {last_r['src_ts']}" if last_r["src_ts"] else ""
                st.markdown(f"""
                <div class="state-card" style="background:{rcfg['bg']};
                             border-color:{rcfg['color']}33; margin-bottom:0.5rem;">
                    <div class="state-label">replayed state · row {last_r['row_num']}</div>
                    <div class="state-value" style="color:{rcfg['color']};">{last_state_r}</div>
                    <div class="state-sub">
                        Otr_acc = {last_r['otr']:.1f} Nm &nbsp;·&nbsp;
                        CoilChanging = {last_r['is_coil_changing']}
                        {'&nbsp;·&nbsp;' + src_ts_label if src_ts_label else ''}
                    </div>
                </div>""", unsafe_allow_html=True)

                if last_r["deviations"] or last_r["failure_states"]:
                    dev_html = ""
                    for dev in last_r["deviations"].values():
                        dev_html += (f'<div class="signal-row">'
                                     f'<span class="signal-label">Deviation</span>'
                                     f'<span style="color:#E24B4A;font-weight:500;">{dev}</span></div>')
                    for fs in last_r["failure_states"]:
                        dev_html += (f'<div class="signal-row">'
                                     f'<span class="signal-label">Failure</span>'
                                     f'<span style="color:#444441;font-weight:500;">{fs}</span></div>')
                    st.markdown(dev_html, unsafe_allow_html=True)

            with rdist:
                st.markdown("<div class='panel-title'>State distribution</div>",
                            unsafe_allow_html=True)
                sc           = st.session_state.replay_state_counts
                total_so_far = sum(sc.values()) or 1
                dist_html    = ""
                for st_name, st_color in [
                    ("Healthy", "#1D9E75"), ("Alert", "#BA7517"),
                    ("Alarm", "#E24B4A"), ("Faulty", "#444441"), ("Stopped", "#888780"),
                ]:
                    count = sc.get(st_name, 0)
                    pct   = count * 100 // total_so_far
                    dist_html += (
                        f'<div style="margin-bottom:6px;">'
                        f'<div style="display:flex;justify-content:space-between;'
                        f'font-size:12px;margin-bottom:2px;">'
                        f'<span style="color:{st_color};font-weight:500;">{st_name}</span>'
                        f'<span style="color:#888;">{count} ({pct}%)</span></div>'
                        f'<div style="background:#f0f0f0;border-radius:3px;height:6px;">'
                        f'<div style="background:{st_color};width:{pct}%;height:6px;'
                        f'border-radius:3px;"></div></div></div>'
                    )
                st.markdown(dist_html, unsafe_allow_html=True)

            st.markdown("<div class='panel-title' style='margin-top:0.75rem;'>"
                        "Otr_acc — replayed</div>", unsafe_allow_html=True)
            chart_data = results_r[-200:]
            otrs       = [r["otr"] for r in chart_data]
            labels     = [str(r["row_num"]) for r in chart_data]
            colors     = []
            for r in chart_data:
                s = r["state"]
                colors.append(
                    "#F09595" if s == "Alarm" else
                    "#FAC775" if s == "Alert" else
                    "#888780" if s == "Faulty" else
                    "#C8C8C5" if s == "Stopped" else "#85B7EB"
                )

            fig_r = go.Figure()
            fig_r.add_trace(go.Bar(
                x=labels, y=otrs, marker_color=colors, showlegend=False,
                hovertemplate="row %{x}<br>Otr_acc = %{y:.1f} Nm<extra></extra>",
            ))
            fig_r.add_hline(y=ALERT_THRESHOLD, line_dash="dot", line_color="#BA7517",
                            line_width=1, annotation_text=f"alert {ALERT_THRESHOLD}",
                            annotation_position="right",
                            annotation_font_size=11, annotation_font_color="#BA7517")
            fig_r.add_hline(y=ALARM_THRESHOLD, line_dash="dot", line_color="#E24B4A",
                            line_width=1, annotation_text=f"alarm {ALARM_THRESHOLD}",
                            annotation_position="right",
                            annotation_font_size=11, annotation_font_color="#E24B4A")
            fig_r.update_layout(
                height=220, margin=dict(l=0, r=60, t=10, b=10),
                plot_bgcolor="white", paper_bgcolor="white",
                xaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
                yaxis=dict(showgrid=True, gridcolor="#f0f0f0", zeroline=False, tickfont_size=11),
            )
            st.plotly_chart(fig_r, width='stretch', config={"displayModeBar": False})

        elif not st.session_state.replay_running:
            st.info("Select a source and click ▶ Start to begin replay.")

    replay_display()
