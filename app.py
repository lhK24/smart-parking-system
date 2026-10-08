import sqlite3
from datetime import datetime
from math import ceil
from pathlib import Path
import streamlit as st

st.set_page_config(page_title='스마트 주차 관리 시스템', page_icon='🚗', layout='wide')
DB = Path(__file__).with_name('parking.db')
SPACES = [f'{r}-{n}' for r in 'ABC' for n in range(1, 4)]
RATE_PER_HOUR = 2000


def connect():
    conn = sqlite3.connect(DB, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=20000')
    return conn


def initialize():
    with connect() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS spaces (name TEXT PRIMARY KEY, plate TEXT)')
        conn.execute('CREATE TABLE IF NOT EXISTS visits (id INTEGER PRIMARY KEY AUTOINCREMENT, plate TEXT NOT NULL, entered TEXT NOT NULL, exited TEXT, space TEXT, fee INTEGER)')
        for name in SPACES:
            conn.execute('INSERT OR IGNORE INTO spaces (name, plate) VALUES (?, NULL)', (name,))


def normalize(plate):
    return ''.join(plate.split()).upper()


def active_visit(conn, plate):
    return conn.execute('SELECT * FROM visits WHERE plate=? AND exited IS NULL ORDER BY id DESC LIMIT 1', (plate,)).fetchone()


def fee(entered, ended=None):
    elapsed = max(0, ((ended or datetime.now()) - datetime.fromisoformat(entered)).total_seconds())
    return ceil(elapsed / 3600) * RATE_PER_HOUR


def enter(plate):
    plate = normalize(plate)
    if not plate:
        return False, '차량번호를 입력하세요.'
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if active_visit(conn, plate):
            return False, f'{plate} 차량은 이미 입차 상태입니다.'
        conn.execute('INSERT INTO visits (plate, entered) VALUES (?, ?)', (plate, datetime.now().isoformat(timespec='seconds')))
    return True, f'📷 {plate} 인식 완료 → 자동 입차 등록! (차단기 열림 시뮬레이션)'


def park(plate, space):
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        visit = active_visit(conn, plate)
        if not visit or visit['space']:
            return False, '배정 가능한 입차 차량이 아닙니다.'
        updated = conn.execute('UPDATE spaces SET plate=? WHERE name=? AND plate IS NULL', (plate, space))
        if updated.rowcount != 1:
            return False, '이미 사용 중인 주차면입니다.'
        conn.execute('UPDATE visits SET space=? WHERE id=?', (space, visit['id']))
    return True, f'📡 센서 감지 시뮬레이션: {plate} → {space} 주차 완료'


def leave(plate):
    plate = normalize(plate)
    if not plate:
        return False, '차량번호를 입력하세요.'
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        visit = active_visit(conn, plate)
        if not visit:
            return False, f'{plate} 차량의 입차 기록이 없습니다.'
        now = datetime.now()
        amount = fee(visit['entered'], now)
        conn.execute('UPDATE visits SET exited=?, fee=? WHERE id=?', (now.isoformat(timespec='seconds'), amount, visit['id']))
        conn.execute('UPDATE spaces SET plate=NULL WHERE plate=?', (plate,))
    return True, f'📷 {plate} 출구 인식 완료 → 요금 {amount:,}원 자동 계산 · 모의 출차 완료 (실제 결제 없음)'


def notice(ok, message):
    st.session_state['notice'] = ('success' if ok else 'warning', message)
    st.rerun()


initialize()
st.title('🚗 스마트 주차 관리 시스템')
st.caption('캡스톤디자인 · 카메라/센서 없는 자동 입출차 시뮬레이션 | 시간당 2,000원 (1시간 단위 올림)')
if 'notice' in st.session_state:
    kind, message = st.session_state['notice']
    (st.success if kind == 'success' else st.warning)(message)

with connect() as conn:
    spaces = conn.execute('SELECT * FROM spaces ORDER BY name').fetchall()
    occupied = sum(bool(s['plate']) for s in spaces)
    active = conn.execute('SELECT COUNT(*) FROM visits WHERE exited IS NULL').fetchone()[0]
    waiting = [r['plate'] for r in conn.execute('SELECT plate FROM visits WHERE exited IS NULL AND space IS NULL ORDER BY id').fetchall()]

c1, c2, c3, c4 = st.columns(4)
c1.metric('전체 주차면', len(SPACES))
c2.metric('빈자리', len(SPACES) - occupied)
c3.metric('사용 중', occupied)
c4.metric('입차 차량', active)

st.subheader('📷 가상 카메라 자동 인식')
left, right = st.columns(2)
with left:
    with st.form('camera_entry', clear_on_submit=True):
        entry_plate = st.text_input('입구 카메라 인식 차량번호', placeholder='123가4567')
        entry_submit = st.form_submit_button('📷 가상 입구 카메라 인식 → 자동 입차', use_container_width=True)
    if entry_submit:
        notice(*enter(entry_plate))
with right:
    with st.form('camera_exit', clear_on_submit=True):
        exit_plate = st.text_input('출구 카메라 인식 차량번호', placeholder='123가4567')
        exit_submit = st.form_submit_button('📷 가상 출구 카메라 인식 → 자동 정산·출차', use_container_width=True)
    if exit_submit:
        notice(*leave(exit_plate))

st.divider()
st.subheader('🅿️ 주차 공간 현황 · 센서 시뮬레이션')
st.caption('입차한 차량을 선택한 뒤 빈 주차면 버튼을 누르면 초음파 센서가 감지한 것으로 처리합니다.')
selected = st.selectbox('주차면에 배정할 차량', waiting, index=0, placeholder='배정 대기 차량 없음') if waiting else None
if not waiting:
    st.info('배정 대기 차량이 없습니다. 위에서 가상 입구 카메라를 먼저 실행하세요.')
for i in range(0, len(spaces), 3):
    cols = st.columns(3)
    for col, space in zip(cols, spaces[i:i + 3]):
        with col:
            if space['plate']:
                st.error(f"🚘 {space['name']} · 주차 중\n\n{space['plate']}")
            else:
                if st.button(f"🟢 {space['name']} · 빈자리 (센서 감지)", key=f"park_{space['name']}", disabled=selected is None, use_container_width=True):
                    notice(*park(selected, space['name']))

lookup_tab, history_tab = st.tabs(['🔍 내 차 찾기', '📋 입출차 기록'])
with lookup_tab:
    search = st.text_input('조회할 차량번호', key='lookup', placeholder='123가4567')
    if st.button('내 차 조회'):
        with connect() as conn:
            visit = active_visit(conn, normalize(search))
        if visit:
            st.success(f"{visit['plate']} · 위치: {visit['space'] or '아직 주차면 미배정'}")
            st.write(f"입차 시간: {visit['entered'].replace('T', ' ')}")
            st.metric('현재 예상 요금', f"{fee(visit['entered']):,}원")
        else:
            st.warning('현재 입차 상태인 차량을 찾을 수 없습니다.')
with history_tab:
    with connect() as conn:
        rows = conn.execute('SELECT plate AS 차량번호, entered AS 입차시각, exited AS 출차시각, space AS 주차면, fee AS 요금 FROM visits ORDER BY id DESC LIMIT 100').fetchall()
    st.dataframe([dict(row) for row in rows], use_container_width=True, hide_index=True)
    st.caption('실제 차량번호 대신 테스트용 번호를 사용하세요.')

st.divider()
st.caption('실제 카메라 인식, ESP32 센서 통신, 차단기 제어, 결제는 아직 연결되지 않았습니다. Streamlit Cloud 재시작 시 SQLite 데이터가 초기화될 수 있습니다.')
