
import streamlit as st
import sqlite3
from datetime import datetime
from pathlib import Path
from math import ceil

st.set_page_config(
    page_title="스마트 주차 관리 시스템",
    page_icon="🚗",
    layout="wide"
)

DB = Path(__file__).with_name("parking.db")
SPACES = [f"{row}-{n}" for row in "ABC" for n in range(1, 4)]
RATE_PER_HOUR = 2000


# ==========================
# 데이터베이스
# ==========================

def connect():
    conn = sqlite3.connect(DB, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=20000")
    return conn


def initialize():
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS spaces (
                name TEXT PRIMARY KEY,
                plate TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plate TEXT NOT NULL,
                entered TEXT NOT NULL,
                exited TEXT,
                space TEXT,
                fee INTEGER
            )
        """)

        for name in SPACES:
            conn.execute(
                "INSERT OR IGNORE INTO spaces (name, plate) VALUES (?, NULL)",
                (name,)
            )


def active_visit(conn, plate):
    return conn.execute("""
        SELECT * FROM visits
        WHERE plate = ? AND exited IS NULL
        ORDER BY id DESC LIMIT 1
    """, (plate,)).fetchone()


def calculate_fee(entered, ended=None):
    start = datetime.fromisoformat(entered)
    end = ended or datetime.now()
    seconds = max(0, (end - start).total_seconds())
    return ceil(seconds / 3600) * RATE_PER_HOUR


def register_entry(plate):
    plate = plate.strip().replace(" ", "")

    if not plate:
        return False, "차량번호를 입력하세요."

    with connect() as conn:
        if active_visit(conn, plate):
            return False, "이미 입차한 차량입니다."

        conn.execute("""
            INSERT INTO visits (plate, entered)
            VALUES (?, ?)
        """, (plate, datetime.now().isoformat(timespec="seconds")))

    return True, f"{plate} 차량 입차 등록 완료!"


def assign_space(plate, space):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")

        visit = active_visit(conn, plate)

        if not visit:
            return False, "입차한 차량이 없습니다."

        if visit["space"]:
            return False, "이미 주차 공간에 배정된 차량입니다."

        result = conn.execute("""
            UPDATE spaces
            SET plate = ?
            WHERE name = ? AND plate IS NULL
        """, (plate, space))

        if result.rowcount != 1:
            return False, "이미 사용 중인 주차 공간입니다."

        conn.execute("""
            UPDATE visits
            SET space = ?
            WHERE id = ?
        """, (space, visit["id"]))

    return True, f"{plate} 차량이 {space}에 주차되었습니다."


def exit_car(plate):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")

        visit = active_visit(conn, plate)

        if not visit:
            return False, "입차 기록이 없습니다."

        now = datetime.now()
        amount = calculate_fee(visit["entered"], now)

        conn.execute("""
            UPDATE visits
            SET exited = ?, fee = ?
            WHERE id = ?
        """, (
            now.isoformat(timespec="seconds"),
            amount,
            visit["id"]
        ))

        conn.execute(
            "UPDATE spaces SET plate = NULL WHERE plate = ?",
            (plate,)
        )

    return True, f"{plate} 출차 완료! 주차 요금: {amount:,}원"


# ==========================
# 초기화 및 알림
# ==========================

initialize()

if "notice" not in st.session_state:
    st.session_state.notice = None


def show_notice():
    if st.session_state.notice:
        kind, message = st.session_state.notice

        if kind == "success":
            st.success(message)
        else:
            st.warning(message)


def save_notice(success, message):
    st.session_state.notice = (
        "success" if success else "warning",
        message
    )
    st.rerun()


# ==========================
# 메인 화면
# ==========================

st.title("🚗 스마트 주차 관리 시스템")

st.caption(
    "캡스톤디자인 | 비전 AI + IoT 기반 스마트 주차장 "
    "| 하드웨어 연결 전 시뮬레이션"
)

show_notice()

with connect() as conn:
    spaces = conn.execute(
        "SELECT * FROM spaces ORDER BY name"
    ).fetchall()

    occupied = sum(1 for s in spaces if s["plate"])

    active = conn.execute("""
        SELECT COUNT(*) FROM visits
        WHERE exited IS NULL
    """).fetchone()[0]

    waiting = conn.execute("""
        SELECT plate FROM visits
        WHERE exited IS NULL AND space IS NULL
        ORDER BY id
    """).fetchall()

m1, m2, m3, m4 = st.columns(4)

m1.metric("전체 주차면", len(SPACES))
m2.metric("빈자리", len(SPACES) - occupied)
m3.metric("사용 중", occupied)
m4.metric("입차 차량", active)

st.divider()

st.subheader("🅿️ 실시간 주차 공간 현황")

st.info(
    "빈자리를 클릭하면 대기 차량을 배정하고, "
    "사용 중인 자리를 클릭하면 출차할 수 있습니다."
)

waiting_plates = [r["plate"] for r in waiting]

if waiting_plates:
    selected_plate = st.selectbox(
        "주차할 차량 선택",
        waiting_plates,
        key="selected_plate"
    )
else:
    selected_plate = None
    st.caption("현재 주차면 배정을 기다리는 차량이 없습니다.")

for i in range(0, len(spaces), 3):
    cols = st.columns(3)

    for col, s in zip(cols, spaces[i:i + 3]):
        with col:
            name = s["name"]
            plate = s["plate"]

            if plate:
                if st.button(
                    f"🔴 {name}\n\n🚘 {plate}\n\n출차 처리",
                    key=f"space_{name}",
                    use_container_width=True,
                    type="secondary"
                ):
                    success, message = exit_car(plate)
                    save_notice(success, message)

            else:
                if st.button(
                    f"🟢 {name}\n\n빈자리\n\n주차하기",
                    key=f"space_{name}",
                    use_container_width=True,
                    type="primary" if selected_plate else "secondary",
                    disabled=selected_plate is None
                ):
                    success, message = assign_space(
                        selected_plate, name
                    )
                    save_notice(success, message)

st.divider()

# ==========================
# 기능별 탭
# ==========================

entry_tab, parking_tab, lookup_tab, exit_tab, history_tab = st.tabs([
    "🚘 입차 등록",
    "🅿️ 주차면 배정",
    "🔍 내 차 찾기",
    "💳 출차 정산",
    "📋 관리 기록"
])


# 입차 등록
with entry_tab:
    st.subheader("차량 입차 등록")

    st.write("번호판 AI 인식을 대신하는 테스트 입력입니다.")

    with st.form("entry_form", clear_on_submit=True):
        plate = st.text_input(
            "차량번호",
            placeholder="예: 123가4567"
        )

        submitted = st.form_submit_button(
            "🚗 입차 등록",
            use_container_width=True
        )

    if submitted:
        success, message = register_entry(plate)
        save_notice(success, message)


# 주차면 배정
with parking_tab:
    st.subheader("주차면 수동 배정")

    with connect() as conn:
        waiting_cars = conn.execute("""
            SELECT plate FROM visits
            WHERE exited IS NULL AND space IS NULL
            ORDER BY id
        """).fetchall()

        free_spaces = conn.execute("""
            SELECT name FROM spaces
            WHERE plate IS NULL
            ORDER BY name
        """).fetchall()

    if not waiting_cars:
        st.info("배정을 기다리는 차량이 없습니다.")

    elif not free_spaces:
        st.warning("빈 주차 공간이 없습니다.")

    else:
        with st.form("assign_form"):
            p = st.selectbox(
                "입차 차량",
                [r["plate"] for r in waiting_cars]
            )

            space = st.selectbox(
                "주차 공간",
                [r["name"] for r in free_spaces]
            )

            assign = st.form_submit_button("주차면 배정")

        if assign:
            success, message = assign_space(p, space)
            save_notice(success, message)


# 내 차 찾기
with lookup_tab:
    st.subheader("🔍 내 차 위치 조회")

    search = st.text_input(
        "조회할 차량번호",
        placeholder="123가4567",
        key="lookup"
    )

    if st.button("내 차 조회"):
        with connect() as conn:
            visit = active_visit(
                conn, search.strip().replace(" ", "")
            )

        if visit:
            st.success(f"차량번호: {visit['plate']}")
            st.info(
                f"주차 위치: "
                f"{visit['space'] or '아직 주차면 미배정'}"
            )

            st.write(
                f"입차 시간: {visit['entered'].replace('T', ' ')}"
            )

            st.metric(
                "현재 예상 요금",
                f"{calculate_fee(visit['entered']):,}원"
            )

        else:
            st.warning("주차 중인 차량을 찾을 수 없습니다.")


# 출차 정산
with exit_tab:
    st.subheader("💳 출차 및 요금 계산")

    with connect() as conn:
        cars = conn.execute("""
            SELECT plate FROM visits
            WHERE exited IS NULL
            ORDER BY id
        """).fetchall()

    if cars:
        with st.form("exit_form"):
            p = st.selectbox(
                "출차할 차량",
                [r["plate"] for r in cars]
            )

            leave = st.form_submit_button(
                "출차 및 요금 계산"
            )

        if leave:
            success, message = exit_car(p)
            save_notice(success, message)

    else:
        st.info("현재 입차한 차량이 없습니다.")


# 관리 기록
with history_tab:
    st.subheader("📋 차량 입출차 기록")

    with connect() as conn:
        rows = conn.execute("""
            SELECT
                plate AS 차량번호,
                entered AS 입차시각,
                exited AS 출차시각,
                space AS 주차면,
                fee AS 요금
            FROM visits
            ORDER BY id DESC
            LIMIT 100
        """).fetchall()

    st.dataframe(
        [dict(r) for r in rows],
        use_container_width=True,
        hide_index=True
    )

st.divider()

st.caption(
    "캡스톤디자인 스마트 주차 관리 시스템 | "
    "ESP32 센서 및 Raspberry Pi 번호판 인식 연동 예정"
)
