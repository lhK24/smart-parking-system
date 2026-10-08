import os
import re
import time
import queue
import sqlite3
import threading
from datetime import datetime
from math import ceil
from pathlib import Path

import av
import cv2
import numpy as np
import streamlit as st
from streamlit_webrtc import webrtc_streamer, WebRtcMode

st.set_page_config(page_title="스마트 주차 관리", page_icon="🚗", layout="wide")
DB = Path(__file__).with_name("parking.db")
SPACES = [f"{row}-{n}" for row in "ABC" for n in range(1, 4)]
RATE_PER_HOUR = 2000
PLATE_PATTERN = re.compile(r"(?:\d{2,3}[가-힣]\d{4})")


def connect():
    con = sqlite3.connect(DB, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=20000")
    return con


def init_db():
    with connect() as con:
        con.execute("CREATE TABLE IF NOT EXISTS spaces (name TEXT PRIMARY KEY, plate TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS visits (id INTEGER PRIMARY KEY AUTOINCREMENT, plate TEXT NOT NULL, entered TEXT NOT NULL, exited TEXT, space TEXT, fee INTEGER)")
        for space in SPACES:
            con.execute("INSERT OR IGNORE INTO spaces(name,plate) VALUES(?,NULL)", (space,))


def active_visit(con, plate):
    return con.execute("SELECT * FROM visits WHERE plate=? AND exited IS NULL ORDER BY id DESC LIMIT 1", (plate,)).fetchone()


def charge(entered, ended):
    return ceil(max(0, (ended - datetime.fromisoformat(entered)).total_seconds()) / 3600) * RATE_PER_HOUR


def process_plate(plate, mode):
    now = datetime.now()
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        visit = active_visit(con, plate)
        if mode == "입구":
            if visit:
                return "info", f"{plate}: 이미 입차 등록된 차량"
            con.execute("INSERT INTO visits(plate,entered) VALUES(?,?)", (plate, now.isoformat(timespec="seconds")))
            return "success", f"{plate}: 자동 입차 등록 완료"
        if not visit:
            return "warning", f"{plate}: 입차 기록이 없어 출차 불가"
        amount = charge(visit["entered"], now)
        con.execute("UPDATE visits SET exited=?, fee=? WHERE id=?", (now.isoformat(timespec="seconds"), amount, visit["id"]))
        con.execute("UPDATE spaces SET plate=NULL WHERE plate=?", (plate,))
        return "success", f"{plate}: 자동 출차 처리 · 모의 요금 {amount:,}원 (결제 미진행)"


def assign(plate, space):
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        visit = active_visit(con, plate)
        if not visit or visit["space"]:
            return "warning", "배정 가능한 입차 차량이 아닙니다."
        result = con.execute("UPDATE spaces SET plate=? WHERE name=? AND plate IS NULL", (plate, space))
        if result.rowcount != 1:
            return "warning", "이미 사용 중인 자리입니다."
        con.execute("UPDATE visits SET space=? WHERE id=?", (space, visit["id"]))
        return "success", f"{plate} → {space} 배정 완료"


def normalize_plate(text):
    cleaned = re.sub(r"\s|[-·.]", "", text)
    match = PLATE_PATTERN.search(cleaned)
    return match.group(0) if match else None


@st.cache_resource(show_spinner="한국어 번호판 OCR 모델 준비 중 (첫 실행은 오래 걸릴 수 있습니다)...")
def get_reader():
    import easyocr
    return easyocr.Reader(["ko", "en"], gpu=False, verbose=False)


class VideoProcessor:
    def __init__(self):
        self.events = queue.Queue()
        self.lock = threading.Lock()
        self.last_scan = 0.0
        self.last_candidate = ""
        self.candidate_count = 0
        self.last_emitted = {}
        self.reader = None

    def recv(self, frame):
        img = frame.to_ndarray(format="bgr24")
        now = time.monotonic()
        if now - self.last_scan < 1.5:
            return frame
        if not self.lock.acquire(blocking=False):
            return frame
        self.last_scan = now
        try:
            if self.reader is None:
                self.reader = get_reader()
            h, w = img.shape[:2]
            scale = min(1.0, 960 / max(w, h))
            small = cv2.resize(img, None, fx=scale, fy=scale) if scale < 1 else img
            # EasyOCR returns text fragments. Try each fragment and adjacent fragments.
            results = self.reader.readtext(small, detail=0, paragraph=False)
            candidates = list(results) + ["".join(results)]
            plate = next((p for text in candidates if (p := normalize_plate(text))), None)
            if plate:
                if plate == self.last_candidate:
                    self.candidate_count += 1
                else:
                    self.last_candidate, self.candidate_count = plate, 1
                if self.candidate_count >= 2 and now - self.last_emitted.get(plate, -1e9) >= 30:
                    self.last_emitted[plate] = now
                    self.events.put(plate)
            else:
                self.last_candidate, self.candidate_count = "", 0
        except Exception as exc:
            self.events.put(("error", str(exc)[:200]))
        finally:
            self.lock.release()
        return av.VideoFrame.from_ndarray(img, format="bgr24")


init_db()
st.title("🚗 스마트 주차 관리 시스템")
st.caption("휴대폰 실시간 카메라 · 한국어 번호판 OCR · 입출차 시뮬레이션")
st.warning("시연용입니다. 실제 차량번호 대신 허가받은 모형 번호판으로 테스트하세요. 실제 결제 및 차단기 제어는 없습니다.")

if "log" not in st.session_state:
    st.session_state.log = []

mode = st.radio("카메라 위치 선택", ["입구", "출구"], horizontal=True)
st.info("입구/출구 모드를 변경할 때는 먼저 카메라를 STOP하고 변경한 뒤 다시 START하세요. 카메라가 번호판을 2회 연속 읽으면 자동 처리합니다.")

ctx = webrtc_streamer(
    key=f"plate-camera-{mode}",
    mode=WebRtcMode.SENDRECV,
    video_processor_factory=VideoProcessor,
    media_stream_constraints={"video": {"facingMode": "environment"}, "audio": False},
    rtc_configuration={"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]},
    async_processing=True,
)

@st.fragment(run_every="2s")
def camera_events():
    if ctx.video_processor:
        processed = 0
        while processed < 10:
            try:
                item = ctx.video_processor.events.get_nowait()
            except queue.Empty:
                break
            processed += 1
            if isinstance(item, tuple):
                st.session_state.log.insert(0, ("error", "OCR 오류: " + item[1]))
            else:
                try:
                    kind, message = process_plate(item, mode)
                except Exception as exc:
                    kind, message = "error", f"DB 처리 오류: {exc}"
                st.session_state.log.insert(0, (kind, message))
    for kind, message in st.session_state.log[:4]:
        getattr(st, kind)(message)
    if ctx.state.playing:
        st.caption("카메라 인식 중 · 아래 주차 현황은 약 2초마다 갱신됩니다.")

camera_events()

st.subheader("🧪 카메라 없이도 동작 확인")
with st.form("manual_test"):
    test_plate = st.text_input("모의 번호판", placeholder="123가4567")
    simulate = st.form_submit_button(f"가상 {mode} 인식 이벤트 보내기")
if simulate:
    normalized = normalize_plate(test_plate)
    if not normalized:
        st.warning("예: 123가4567 형식으로 입력하세요.")
    else:
        kind, message = process_plate(normalized, mode)
        st.session_state.log.insert(0, (kind, message))
        st.rerun()

@st.fragment(run_every="2s")
def dashboard():
    with connect() as con:
        spaces = con.execute("SELECT * FROM spaces ORDER BY name").fetchall()
        active = con.execute("SELECT COUNT(*) FROM visits WHERE exited IS NULL").fetchone()[0]
        waiting = [r[0] for r in con.execute("SELECT plate FROM visits WHERE exited IS NULL AND space IS NULL ORDER BY id")]
    occupied = sum(bool(s["plate"]) for s in spaces)
    cols = st.columns(4)
    for col, label, value in zip(cols, ["전체 주차면", "빈자리", "사용 중", "입차 차량"], [9, 9-occupied, occupied, active]):
        col.metric(label, value)
    st.subheader("🅿️ 주차 공간")
    if waiting:
        selected = st.selectbox("배정할 차량", waiting, key="waiting_select")
    else:
        selected = None
        st.caption("주차면 배정 대기 차량이 없습니다.")
    for i in range(0, 9, 3):
        columns = st.columns(3)
        for col, space in zip(columns, spaces[i:i+3]):
            with col:
                if space["plate"]:
                    st.error(f"🚘 {space['name']} · {space['plate']}")
                elif st.button(f"🟢 {space['name']} · 빈자리 (배정)", key=f"assign_{space['name']}", disabled=selected is None, use_container_width=True):
                    kind, message = assign(selected, space["name"])
                    st.session_state.log.insert(0, (kind, message))
                    st.rerun()

dashboard()

lookup_tab, history_tab = st.tabs(["🔍 내 차 찾기", "📋 관리 기록"])
with lookup_tab:
    search = st.text_input("차량번호 조회")
    if st.button("조회"):
        with connect() as con:
            visit = active_visit(con, normalize_plate(search) or "")
        if visit:
            st.success(f"{visit['plate']} · 위치: {visit['space'] or '미배정'}")
            st.write("입차 시각:", visit["entered"].replace("T", " "))
            st.write("예상 요금:", f"{charge(visit['entered'], datetime.now()):,}원")
        else:
            st.warning("주차 중인 차량을 찾을 수 없습니다.")
with history_tab:
    with connect() as con:
        rows = con.execute("SELECT plate AS 차량번호, entered AS 입차시각, exited AS 출차시각, space AS 주차면, fee AS 요금 FROM visits ORDER BY id DESC LIMIT 100").fetchall()
    st.dataframe([dict(r) for r in rows], use_container_width=True, hide_index=True)

st.caption("주의: Streamlit Community Cloud 로컬 SQLite 파일은 재시작 시 사라질 수 있습니다. WebRTC는 네트워크 환경에 따라 TURN 서버가 필요할 수 있습니다.")
