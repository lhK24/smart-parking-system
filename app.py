import base64
import io
import re
import sqlite3
import time
from datetime import datetime
from math import ceil
from pathlib import Path

import numpy as np
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image

st.set_page_config(page_title="스마트 주차장", page_icon="🚗", layout="wide")
ROOT = Path(__file__).parent
DB = ROOT / "parking.db"
SPACES = [f"{row}-{n}" for row in "ABC" for n in range(1, 4)]
RATE = 2000
camera = components.declare_component("phone_camera", path=str(ROOT / "frontend"))


def db():
    c = sqlite3.connect(DB, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=20000")
    return c


def init():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS spaces (name TEXT PRIMARY KEY, plate TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS visits (id INTEGER PRIMARY KEY AUTOINCREMENT, plate TEXT NOT NULL, entered TEXT NOT NULL, exited TEXT, space TEXT, fee INTEGER)")
        for s in SPACES:
            c.execute("INSERT OR IGNORE INTO spaces VALUES (?,NULL)", (s,))


def active(c, plate):
    return c.execute("SELECT * FROM visits WHERE plate=? AND exited IS NULL ORDER BY id DESC LIMIT 1", (plate,)).fetchone()


def normalize(text):
    return re.sub(r"\s+", "", str(text)).upper()


def plates_from_text(text):
    # OCR이 글자를 띄어 읽는 경우도 허용한다.
    cleaned = re.sub(r"[^0-9가-힣]", "", normalize(text))
    return re.findall(r"(?<!\d)\d{2,3}[가-힣]\d{4}(?!\d)", cleaned)


def enter(plate):
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        if active(c, plate):
            return "이미 입차된 차량입니다."
        c.execute("INSERT INTO visits (plate,entered) VALUES (?,?)", (plate, datetime.now().isoformat(timespec='seconds')))
    return f"{plate} 자동 입차 등록 완료"


def leave(plate):
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        v = active(c, plate)
        if not v:
            return "입차 기록이 없는 차량입니다."
        now = datetime.now()
        hours = ceil(max(0, (now - datetime.fromisoformat(v['entered'])).total_seconds()) / 3600)
        amount = hours * RATE
        c.execute("UPDATE visits SET exited=?,fee=? WHERE id=?", (now.isoformat(timespec='seconds'), amount, v['id']))
        c.execute("UPDATE spaces SET plate=NULL WHERE plate=?", (plate,))
    return f"{plate} 자동 출차 완료 · 요금 {amount:,}원 (모의 정산)"


@st.cache_resource(show_spinner="번호판 문자 인식 모델 준비 중...")
def reader():
    import easyocr
    return easyocr.Reader(['ko', 'en'], gpu=False, verbose=False)


def recognize(image):
    import cv2
    rgb = np.asarray(image.convert('RGB'))
    h, w = rgb.shape[:2]
    # 화면 중앙의 번호판을 크게 비추면 주변 글자 간섭이 줄어든다.
    crops = [("전체", rgb)]
    if w >= 240 and h >= 160:
        crops.insert(0, ("중앙", rgb[int(h*.23):int(h*.77), int(w*.08):int(w*.92)]))

    seen = []
    raw_texts = []
    for region, crop in crops:
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        # 작은 번호판을 키우고 대비를 보정해 OCR에 전달
        variants = [
            ("원본", crop),
            ("대비보정", cv2.cvtColor(cv2.resize(enhanced, None, fx=2, fy=2), cv2.COLOR_GRAY2RGB)),
        ]
        for label, variant in variants:
            results = reader().readtext(variant, detail=1, paragraph=False)
            texts = [str(item[1]) for item in results]
            raw_texts.extend([f"{region}/{label}: {t}" for t in texts])
            # 전체 문장과 분리된 OCR 조각을 모두 검사
            candidates = plates_from_text(''.join(texts))
            for t in texts:
                candidates.extend(plates_from_text(t))
            for plate in candidates:
                if plate not in seen:
                    seen.append(plate)
            if seen:
                return seen[0], raw_texts[:15]
    return None, raw_texts[:15]


init()
st.title("🚗 스마트 주차 관리 시스템")
st.caption("휴대폰 브라우저 카메라 프레임 전송 방식 · WebRTC/STUN/TURN 불필요 · 실험용")
if 'last_notice' in st.session_state:
    st.info(st.session_state.last_notice)

with db() as c:
    spaces = c.execute("SELECT * FROM spaces ORDER BY name").fetchall()
    count = c.execute("SELECT COUNT(*) FROM visits WHERE exited IS NULL").fetchone()[0]
occupied = sum(bool(s['plate']) for s in spaces)
for col, (label, val) in zip(st.columns(4), [('전체 주차면',9),('빈자리',9-occupied),('사용 중',occupied),('입차 차량',count)]):
    col.metric(label,val)

camera_tab, parking_tab, lookup_tab, history_tab = st.tabs(['📱 실시간 휴대폰 카메라','🅿️ 주차면','🔎 내 차 찾기','📋 기록'])
with camera_tab:
    mode = st.radio('카메라 위치', ['입구 (자동 입차)', '출구 (자동 출차)'], horizontal=True)
    st.caption('번호판을 화면 중앙에 크게, 가로 방향으로 비춰주세요. 약 2초마다 프레임을 분석합니다.')
    frame = camera(key='live_camera', default=None)
    if frame and isinstance(frame,dict) and 'frame' in frame:
        seq = frame.get('seq')
        # 동일 프레임 중복 처리 방지
        if st.session_state.get('processed_seq') != seq:
            st.session_state.processed_seq = seq
            try:
                raw = base64.b64decode(frame['frame'].split(',',1)[1])
                img = Image.open(io.BytesIO(raw))
                plate, debug_texts = recognize(img)
                st.session_state.ocr_debug = debug_texts
                if plate:
                    st.session_state.last_detected = plate
                    # 서로 다른 프레임에서 같은 번호판을 2회 읽은 뒤 처리
                    prev = st.session_state.get('candidate_plate')
                    count = st.session_state.get('candidate_count', 0) + 1 if prev == plate else 1
                    st.session_state.candidate_plate = plate
                    st.session_state.candidate_count = count
                    if count >= 2:
                        token = (mode, plate)
                        last = st.session_state.get('last_event')
                        if not last or last[0] != token or time.monotonic() - last[1] > 30:
                            st.session_state.last_notice = enter(plate) if mode.startswith('입구') else leave(plate)
                            st.session_state.last_event = (token, time.monotonic())
                else:
                    st.session_state.last_detected = '번호판 형식 미검출 (아래 OCR 원본 결과 확인)'
                    st.session_state.candidate_plate = None
                    st.session_state.candidate_count = 0
            except Exception as e:
                st.session_state.last_detected = f'프레임 분석 오류: {e}'
    st.write('최근 인식:', st.session_state.get('last_detected','아직 없음'))
    with st.expander('🔎 OCR 진단 결과 (인식 안 될 때 확인)', expanded=True):
        raw = st.session_state.get('ocr_debug', [])
        st.write(' / '.join(raw) if raw else 'OCR이 읽은 글자가 아직 없습니다. 카메라 시작 후 기다려주세요.')
        st.caption('여기에 글자가 나오면 카메라 프레임은 서버에 전달되고 있는 것입니다. 실제 번호판이 아닌 테스트용 모형을 사용하세요.')
    st.divider()
    st.write('**카메라 인식이 어려울 때 수동 테스트**')
    with st.form('manual'):
        plate = st.text_input('테스트 차량번호', placeholder='123가4567')
        submitted = st.form_submit_button('현재 모드로 처리')
    if submitted:
        matches = plates_from_text(plate)
        if matches:
            st.session_state.last_notice = enter(matches[0]) if mode.startswith('입구') else leave(matches[0])
            st.rerun()
        else:
            st.warning('차량번호 형식을 확인해 주세요. 예: 123가4567')

with parking_tab:
    with db() as c:
        waiting = [r['plate'] for r in c.execute('SELECT plate FROM visits WHERE exited IS NULL AND space IS NULL ORDER BY id')]
        spaces = c.execute('SELECT * FROM spaces ORDER BY name').fetchall()
    selected = st.selectbox('주차 대기 차량',waiting) if waiting else None
    if not waiting:
        st.caption('대기 차량 없음. 입구 카메라로 먼저 등록하세요.')
    for i in range(0,9,3):
        for col,s in zip(st.columns(3),spaces[i:i+3]):
            with col:
                if s['plate']:
                    st.error(f"🚘 {s['name']} · {s['plate']}")
                elif st.button(f"🟢 {s['name']} · 빈자리",key=f"space_{s['name']}",disabled=not selected,use_container_width=True):
                    with db() as c:
                        c.execute('BEGIN IMMEDIATE')
                        r=c.execute('UPDATE spaces SET plate=? WHERE name=? AND plate IS NULL',(selected,s['name']))
                        if r.rowcount:
                            c.execute('UPDATE visits SET space=? WHERE plate=? AND exited IS NULL AND space IS NULL',(s['name'],selected))
                    st.rerun()

with lookup_tab:
    query=st.text_input('차량번호 조회')
    if st.button('검색'):
        with db() as c:
            v=active(c,normalize(query))
        if v:
            st.success(f"{v['plate']} · 위치: {v['space'] or '미배정'} · 입차: {v['entered']}")
        else:
            st.warning('입차 중인 차량을 찾지 못했습니다.')

with history_tab:
    with db() as c:
        records=c.execute('SELECT plate AS 차량번호, entered AS 입차, exited AS 출차, space AS 주차면, fee AS 요금 FROM visits ORDER BY id DESC LIMIT 100').fetchall()
    st.dataframe([dict(r) for r in records],use_container_width=True,hide_index=True)
    st.caption('SQLite는 Streamlit Cloud 재시작 시 초기화될 수 있습니다. 실제 번호판 대신 테스트용 번호판을 사용하세요.')
