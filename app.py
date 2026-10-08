import streamlit as st
import sqlite3
from datetime import datetime
from pathlib import Path

st.set_page_config(page_title='스마트 주차 관리 시스템', page_icon='🚗', layout='wide')
DB = Path(__file__).with_name('parking.db')
SPACES = [f'{row}-{n}' for row in 'ABC' for n in range(1, 4)]
RATE_PER_HOUR = 2000

def connect():
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def initialize():
    with connect() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS spaces (name TEXT PRIMARY KEY, plate TEXT)')
        conn.execute('CREATE TABLE IF NOT EXISTS visits (id INTEGER PRIMARY KEY AUTOINCREMENT, plate TEXT NOT NULL, entered TEXT NOT NULL, exited TEXT, space TEXT, fee INTEGER)')
        for name in SPACES:
            conn.execute('INSERT OR IGNORE INTO spaces (name, plate) VALUES (?, NULL)', (name,))

def active_visit(conn, plate):
    return conn.execute('SELECT * FROM visits WHERE plate=? AND exited IS NULL ORDER BY id DESC LIMIT 1', (plate,)).fetchone()

def fee(entered, ended=None):
    start = datetime.fromisoformat(entered)
    minutes = max(0, ((ended or datetime.now()) - start).total_seconds() / 60)
    return int((int((minutes + 59) // 60)) * RATE_PER_HOUR) if minutes > 0 else 0

initialize()
st.title('🚗 스마트 주차 관리 시스템')
st.caption('캡스톤디자인 · 비전 AI + IoT 기반 주차장 모형 | 현재는 하드웨어 없이 테스트하는 시뮬레이션 버전')
with connect() as conn:
    spaces = conn.execute('SELECT * FROM spaces ORDER BY name').fetchall()
    occupied = sum(bool(s['plate']) for s in spaces)
    active = conn.execute('SELECT COUNT(*) FROM visits WHERE exited IS NULL').fetchone()[0]

m1,m2,m3,m4 = st.columns(4)
m1.metric('전체 주차면', len(SPACES))
m2.metric('빈자리', len(SPACES)-occupied)
m3.metric('사용 중', occupied)
m4.metric('입차 차량', active)

st.subheader('주차 공간 현황')
for i in range(0, len(spaces), 3):
    cols = st.columns(3)
    for col, s in zip(cols, spaces[i:i+3]):
        with col:
            if s['plate']:
                st.error(f"🚘 {s['name']} · 주차 중\n\n{s['plate']}")
            else:
                st.success(f"🅿️ {s['name']} · 빈자리")

entry_tab, parking_tab, lookup_tab, exit_tab, history_tab = st.tabs(['입차 등록','주차면 배정','내 차 찾기','출차 정산','관리 기록'])
with entry_tab:
    st.write('카메라 번호판 인식을 대신하는 테스트 입력입니다.')
    with st.form('entry'):
        plate = st.text_input('차량번호', placeholder='123가4567').strip()
        submit = st.form_submit_button('입차 등록')
    if submit:
        if not plate:
            st.warning('차량번호를 입력하세요.')
        else:
            with connect() as conn:
                if active_visit(conn, plate):
                    st.warning('이미 입차한 차량입니다.')
                else:
                    conn.execute('INSERT INTO visits (plate, entered) VALUES (?,?)', (plate, datetime.now().isoformat(timespec='seconds')))
                    st.success(f'{plate} 입차 등록 완료')
                    st.rerun()

with parking_tab:
    with connect() as conn:
        waiting = conn.execute('SELECT plate FROM visits WHERE exited IS NULL AND space IS NULL ORDER BY entered').fetchall()
        free = conn.execute('SELECT name FROM spaces WHERE plate IS NULL ORDER BY name').fetchall()
    if not waiting:
        st.info('주차면을 배정할 대기 차량이 없습니다.')
    elif not free:
        st.warning('빈 주차면이 없습니다.')
    else:
        with st.form('assign'):
            p = st.selectbox('입차 차량', [r['plate'] for r in waiting])
            space = st.selectbox('빈 주차면', [r['name'] for r in free])
            assign = st.form_submit_button('주차면 배정 (센서 감지 시뮬레이션)')
        if assign:
            with connect() as conn:
                conn.execute('UPDATE spaces SET plate=? WHERE name=? AND plate IS NULL', (p,space))
                conn.execute('UPDATE visits SET space=? WHERE plate=? AND exited IS NULL AND space IS NULL', (space,p))
            st.rerun()

with lookup_tab:
    search = st.text_input('조회할 차량번호', key='lookup')
    if st.button('내 차 조회'):
        with connect() as conn:
            v = active_visit(conn, search.strip())
        if v:
            st.success(f"차량: {v['plate']} | 위치: {v['space'] or '주차 위치 미배정'}")
            st.write(f"입차: {v['entered'].replace('T',' ')}")
            st.write(f"현재 예상 요금: {fee(v['entered']):,}원 (시간당 {RATE_PER_HOUR:,}원, 올림 계산)")
        else:
            st.warning('주차 중인 차량을 찾을 수 없습니다.')

with exit_tab:
    with connect() as conn:
        cars = conn.execute('SELECT plate FROM visits WHERE exited IS NULL ORDER BY entered').fetchall()
    if cars:
        with st.form('exit'):
            p = st.selectbox('출차 차량', [r['plate'] for r in cars])
            leave = st.form_submit_button('출차 및 요금 계산')
        if leave:
            now = datetime.now()
            with connect() as conn:
                v = active_visit(conn,p)
                amount = fee(v['entered'],now)
                conn.execute('UPDATE visits SET exited=?, fee=? WHERE id=?', (now.isoformat(timespec='seconds'),amount,v['id']))
                conn.execute('UPDATE spaces SET plate=NULL WHERE plate=?',(p,))
            st.success(f'{p} 출차 완료 · 요금 {amount:,}원 (실제 결제는 진행되지 않습니다)')
    else:
        st.info('현재 입차한 차량이 없습니다.')

with history_tab:
    with connect() as conn:
        rows = conn.execute('SELECT plate AS 차량번호, entered AS 입차시각, exited AS 출차시각, space AS 주차면, fee AS 요금 FROM visits ORDER BY id DESC LIMIT 100').fetchall()
    st.dataframe([dict(r) for r in rows], use_container_width=True, hide_index=True)
    st.caption('시연용 화면입니다. 개인정보가 포함된 실제 차량번호는 입력하지 마세요.')

st.divider()
st.caption('향후 연동: ESP32 초음파 센서 → 주차면 점유 이벤트 / Raspberry Pi 카메라 → 번호판 인식 이벤트. 이 버전에는 실제 API·인증·결제 기능이 없습니다.')
