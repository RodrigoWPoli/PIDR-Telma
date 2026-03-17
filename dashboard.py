"""
dashboard.py
Streamlit real-time fault detection dashboard for the TELMA platform.

Usage:
    pip install streamlit plotly
    streamlit run dashboard.py
"""

import time
import socket
import threading
import subprocess
import pymongo
import streamlit as st
import plotly.graph_objects as go
from datetime import datetime
from update_ontology import infer_state, load_ontology, update_data_properties


# ── VPN check ─────────────────────────────────────────────────────────────────
def check_vpn() -> tuple[bool, str]:
    """
    Tests connectivity to the TELMA PLC OPC-UA server.
    Returns (is_connected, status_message).
    Uses a TCP socket — no ping required.
    """
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


# ── Session state ──────────────────────────────────────────────────────────────
if "state_history" not in st.session_state:
    st.session_state.state_history = []
if "last_state" not in st.session_state:
    st.session_state.last_state = None
if "collection_process" not in st.session_state:
    st.session_state.collection_process = None
if "collection_log" not in st.session_state:
    st.session_state.collection_log = []
if "ontology_log" not in st.session_state:
    st.session_state.ontology_log = []
if "initialized" not in st.session_state:
    st.session_state.initialized = True
    st.rerun()


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Controls")
    st.markdown("<hr style='margin:0.5rem 0;'>", unsafe_allow_html=True)

    # ── VPN status ────────────────────────────────────────────────────────────
    st.markdown("**Network**")
    vpn_ok, vpn_msg = check_vpn()
    if vpn_ok:
        st.success(vpn_msg, icon="✅")
    else:
        st.error(vpn_msg, icon="🔴")

    st.markdown("<hr style='margin:0.75rem 0;'>", unsafe_allow_html=True)

    # ── Data collection ───────────────────────────────────────────────────────
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
            import os, sys
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

    # Collection log
    if st.session_state.collection_log:
        for entry in st.session_state.collection_log[:4]:
            st.caption(entry)

    st.markdown("<hr style='margin:0.75rem 0;'>", unsafe_allow_html=True)

    # ── Ontology update ───────────────────────────────────────────────────────
    st.markdown("**Ontology**")

    if st.button("Update ontology now", use_container_width=True):
        try:
            onto_inst = get_ontology()
            vals = get_latest_values()
            if vals:
                update_data_properties(onto_inst, vals)
                ts = datetime.now().strftime("%H:%M:%S")
                otr = float(vals.get("Otr_acc", 0))
                st.session_state.ontology_log.insert(
                    0, f"{ts} — updated (Otr_acc={otr:.1f})")
                st.success("Ontology updated", icon="✅")
            else:
                st.warning("No data in MongoDB")
        except Exception as e:
            st.error(f"Error: {e}")

    if st.session_state.ontology_log:
        for entry in st.session_state.ontology_log[:4]:
            st.caption(entry)

    st.markdown("<hr style='margin:0.75rem 0;'>", unsafe_allow_html=True)

    # ── Settings ──────────────────────────────────────────────────────────────
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


# ── Render ─────────────────────────────────────────────────────────────────────
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

# Fetch & infer
values = get_latest_values()
if not values:
    st.warning("No data in MongoDB. Run simulate_data.py or data_collection.py first.")
    time.sleep(REFRESH_INTERVAL)
    st.rerun()

onto = get_ontology()
update_data_properties(onto, values)
result = infer_state(values)
state  = result["state"]
cfg    = STATE_CONFIG.get(state, STATE_CONFIG[None])

# Track state changes
if state != st.session_state.last_state:
    st.session_state.state_history.insert(0, {
        "time":  datetime.now().strftime("%H:%M:%S"),
        "state": state,
        "otr":   values.get("Otr_acc", 0),
        "color": cfg["color"]
    })
    st.session_state.state_history = st.session_state.state_history[:MAX_STATE_HISTORY]
    st.session_state.last_state = state

# State card
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

# Metrics
m1, m2, m3, m4 = st.columns(4)
with m1: st.metric("Motor torque",  f"{otr_val:.1f} Nm")
with m2: st.metric("Motor speed",   f"{float(values.get('Rfrd_acc', 0)):.0f} rpm")
with m3: st.metric("Temperature",   f"{float(values.get('TempMoteur_acc', 0)):.1f} °C")
with m4: st.metric("Current",       f"{float(values.get('Lcr_acc', 0)):.2f} A")

st.markdown("<div style='margin-top:0.75rem;'></div>", unsafe_allow_html=True)

left, right = st.columns(2)

with left:
    # Torque chart
    st.markdown("<div class='panel-title'>Otr_acc over time</div>", unsafe_allow_html=True)
    history = get_otr_history()
    if history:
        times  = [h[0] for h in history]
        hvals  = [h[1] for h in history]
        colors = ["#F09595" if v > ALARM_THRESHOLD else "#FAC775" if v > ALERT_THRESHOLD
                  else "#85B7EB" for v in hvals]
        fig = go.Figure()
        fig.add_trace(go.Bar(x=times, y=hvals, marker_color=colors,
                             showlegend=False, hovertemplate="%{y:.2f} Nm<extra></extra>"))
        fig.add_hline(y=ALERT_THRESHOLD, line_dash="dot", line_color="#BA7517", line_width=1,
                      annotation_text=f"alert {ALERT_THRESHOLD}", annotation_position="right",
                      annotation_font_size=11, annotation_font_color="#BA7517")
        fig.add_hline(y=ALARM_THRESHOLD, line_dash="dot", line_color="#E24B4A", line_width=1,
                      annotation_text=f"alarm {ALARM_THRESHOLD}", annotation_position="right",
                      annotation_font_size=11, annotation_font_color="#E24B4A")
        fig.update_layout(height=220, margin=dict(l=0, r=60, t=10, b=10),
                          plot_bgcolor="white", paper_bgcolor="white",
                          xaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
                          yaxis=dict(showgrid=True, gridcolor="#f0f0f0",
                                     zeroline=False, tickfont_size=11))
        st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})

    # Failure chain
    st.markdown("<div class='panel-title' style='margin-top:0.5rem;'>Failure chain</div>",
                unsafe_allow_html=True)
    if result["deviations"] or result["failure_states"]:
        chain = ("""
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
        </div>""")
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
    # Signal status
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

    # State history
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

# Auto-refresh
st.markdown(f"<p style='text-align:center;color:#ccc;font-size:11px;margin-top:1.5rem;'>"
            f"auto-refresh every {REFRESH_INTERVAL}s</p>", unsafe_allow_html=True)

# ── Advance motor ──────────────────────────────────────────────────────────────
st.markdown("<hr style='border:none;border-top:0.5px solid #e5e5e5;margin:1rem 0 0.5rem;'>",
            unsafe_allow_html=True)
st.markdown("<div class='panel-title'>Advance motor</div>", unsafe_allow_html=True)
a1, a2, a3, a4, a5 = st.columns(5)
with a1: st.metric("Torque",      f"{float(values.get('Otr_av', 0)):.0f} Nm")
with a2: st.metric("Speed",       f"{float(values.get('Rfrd_av', 0)):.0f} rpm")
with a3: st.metric("Temperature", f"{float(values.get('TempMoteur_av', 0)):.1f} \u00b0C")
with a4: st.metric("Current",     f"{float(values.get('Lcr_av', 0)):.2f} A")
with a5: st.metric("Voltage",     f"{float(values.get('Uop_av', 0)):.0f} V")

# ── Production & electrical ────────────────────────────────────────────────────
st.markdown("<div style='margin-top:0.5rem;'></div>", unsafe_allow_html=True)
p1, p2 = st.columns(2)

with p1:
    st.markdown("<div class='panel-title'>Production</div>", unsafe_allow_html=True)
    eu_class = "signal-true" if values.get("Ent_au") else "signal-false"
    eu_text  = "ACTIVE" if values.get("Ent_au") else "OK"
    prod_html = (
        f'<div class="signal-row"><span class="signal-label">Pieces produced</span>'
        f'<span style="font-weight:500;">{int(values.get("Cpt_nb_piece", 0))}</span></div>'
        f'<div class="signal-row"><span class="signal-label">Coils used</span>'
        f'<span style="font-weight:500;">{int(values.get("Cpt_nb_bobine", 0))}</span></div>'
        f'<div class="signal-row"><span class="signal-label">Current turns</span>'
        f'<span style="font-weight:500;">{int(values.get("Nombre_tours", 0))}</span></div>'
        f'<div class="signal-row"><span class="signal-label">Piece dimension</span>'
        f'<span style="font-weight:500;">{int(values.get("Dim_piece", 0))}</span></div>'
        f'<div class="signal-row"><span class="signal-label">Emergency stop</span>'
        f'<span class="{eu_class}">{eu_text}</span></div>'
    )
    st.markdown(prod_html, unsafe_allow_html=True)

with p2:
    st.markdown("<div class='panel-title'>Electrical (powertag)</div>",
                unsafe_allow_html=True)
    elec_html = (
        f'<div class="signal-row"><span class="signal-label">Phase A</span>'
        f'<span style="font-weight:500;">{float(values.get("CourantA", 0)):.2f} A</span></div>'
        f'<div class="signal-row"><span class="signal-label">Phase B</span>'
        f'<span style="font-weight:500;">{float(values.get("CourantB", 0)):.2f} A</span></div>'
        f'<div class="signal-row"><span class="signal-label">Phase C</span>'
        f'<span style="font-weight:500;">{float(values.get("CourantC", 0)):.2f} A</span></div>'
        f'<div class="signal-row"><span class="signal-label">Total (A+B+C)</span>'
        f'<span style="font-weight:500;">{float(values.get("CourantTot", 0)):.2f} A</span></div>'
        f'<div class="signal-row"><span class="signal-label">Accu voltage</span>'
        f'<span style="font-weight:500;">{float(values.get("Uop_acc", 0)):.0f} V</span></div>'
    )
    st.markdown(elec_html, unsafe_allow_html=True)

time.sleep(REFRESH_INTERVAL)
st.rerun()