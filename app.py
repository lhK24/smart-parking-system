
"""Smart Parking dashboard: three sensor bays and separate vehicle records."""

import re
from datetime import datetime, timezone
from math import ceil

import requests
import streamlit as st


# ====================================
# PAGE SETTINGS
# ====================================

st.set_page_config(
    page_title="스마트 주차장",
    page_icon="🚗",
    layout="wide"
)

st.title("🚗 스마트 주차장 관리 시스템")
st.caption(
    "라즈베리파이 자동 번호판 인식 · "
    "주차센서 3칸 · 실시간 입출차 기록"
)


# ====================================
# SETTINGS
# ====================================

SENSOR_SPACES = ("A-1", "A-2", "A-3")

URL = st.secrets["SUPABASE_URL"].strip().rstrip("/")
KEY = st.secrets["SUPABASE_ANON_KEY"].strip()

HEADERS = {
    "apikey": KEY,
    "Authorization": f"Bearer {KEY}",
    "Content-Type": "application/json"
}


# ====================================
# SUPABASE FUNCTIONS
# ====================================

def db_get(table, params):

    response = requests.get(
        f"{URL}/rest/v1/{table}",
        headers=HEADERS,
        params=params,
        timeout=15
    )

    response.raise_for_status()
    return response.json()


def db_update(table, params, data):

    response = requests.patch(
        f"{URL}/rest/v1/{table}",
        headers={
            **HEADERS,
            "Prefer": "return=representation"
        },
        params=params,
        json=data,
        timeout=15
    )

    response.raise_for_status()
    return response.json()


# ====================================
# UTILITY FUNCTIONS
# ====================================

def normalize_plate(value):

    return re.sub(
        r"[^0-9가-힣]",
        "",
        str(value)
    )


def fmt_time(iso):

    if not iso:
        return "-"

    try:
        dt = datetime.fromisoformat(
            str(iso).replace("Z", "+00:00")
        )
        return dt.astimezone().strftime(
            "%Y-%m-%d %H:%M"
        )

    except (ValueError, TypeError):
        return str(iso)


# ====================================
# VEHICLE EXIT
# ====================================

def get_active_vehicle(plate):

    result = db_get(
        "parking_visits",
        {
            "select": "id,plate,entered_at,space",
            "plate": f"eq.{plate}",
            "exited_at": "is.null",
            "limit": "1"
        }
    )

    return result[0] if result else None


def process_exit(plate):

    vehicle = get_active_vehicle(plate)

    if not vehicle:
        return False, "입차 기록이 없는 차량입니다."

    now = datetime.now(timezone.utc)

    entered = datetime.fromisoformat(
        vehicle["entered_at"].replace("Z", "+00:00")
    )

    if entered.tzinfo is None:
        entered = entered.replace(tzinfo=timezone.utc)

    seconds = max(
        0,
        (now - entered).total_seconds()
    )

    fee = max(
        2000,
        ceil(seconds / 3600) * 2000
    )

    updated = db_update(
        "parking_visits",
        {
            "id": f"eq.{vehicle['id']}",
            "exited_at": "is.null"
        },
        {
            "exited_at": now.isoformat(),
            "fee": fee
        }
    )

    if not updated:
        return False, "출차 저장에 실패했습니다."

    space = vehicle.get("space")

    if space:
        db_update(
            "parking_spaces",
            {
                "name": f"eq.{space}",
                "plate": f"eq.{plate}"
            },
            {
                "plate": None
            }
        )

    return True, f"{plate} 출차 완료 · 요금 {fee:,}원"


# ====================================
# MAIN DASHBOARD
# ====================================

st.subheader("📊 주차장 실시간 현황")

if st.button("🔄 입차 기록 새로고침"):
    st.rerun()

try:
    active = db_get(
        "parking_visits",
        {
            "select": "id,plate,entered_at,space",
            "exited_at": "is.null",
            "order": "entered_at.asc"
        }
    )

except Exception as error:
    st.error(f"입차 기록 조회 오류: {error}")
    st.stop()


# ====================================
# SENSOR STATUS: AUTO REFRESH
# ====================================

@st.fragment(run_every="5s")
def show_sensor_dashboard():

    try:
        spaces = db_get(
            "parking_spaces",
            {
                "select": "name,plate,sensor_status",
                "name": "in.(A-1,A-2,A-3)",
                "order": "name.asc"
            }
        )

    except Exception as error:
        st.error(f"주차센서 조회 오류: {error}")
        return

    by_name = {
        space["name"]: space
        for space in spaces
    }

    states = {}

    for name in SENSOR_SPACES:

        sensor_status = (
            by_name.get(name, {})
            .get("sensor_status")
        )

        if sensor_status in ("PARKING", "EMPTY"):
            states[name] = sensor_status
        else:
            states[name] = "미확인"

    occupied = sum(
        value == "PARKING"
        for value in states.values()
    )

    empty = sum(
        value == "EMPTY"
        for value in states.values()
    )

    unknown = len(SENSOR_SPACES) - occupied - empty

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("센서 설치 주차면", 3)
    c2.metric("빈자리", empty)
    c3.metric("주차 중", occupied)
    c4.metric("상태 미확인", unknown)

    st.subheader("🅿️ 주차공간 센서 현황")

    st.caption(
        "A-1, A-2, A-3 · "
        "센서 상태 5초마다 자동 갱신"
    )

    cols = st.columns(3)

    for col, name in zip(cols, SENSOR_SPACES):

        with col:

            state = states[name]

            if state == "PARKING":
                st.error(
                    f"🚘 {name} · PARKING (주차 중)"
                )

            elif state == "EMPTY":
                st.success(
                    f"🅿️ {name} · EMPTY (빈자리)"
                )

            else:
                st.warning(
                    f"❔ {name} · 센서 상태 미확인"
                )


show_sensor_dashboard()

st.caption(
    "차량 번호판은 별도 입차 기록으로 관리합니다. "
    "센서 상태만으로 차량번호를 판단하지 않습니다."
)

st.caption(
    f"현재 입차 기록: {len(active)}대"
)


# ====================================
# ENTRY VEHICLE RECORDS
# ====================================

st.subheader("🚗 입차 차량 현황 (번호판 OCR 기록)")

if active:

    vehicle_rows = []

    for vehicle in active:

        vehicle_rows.append(
            {
                "차량번호": vehicle["plate"],
                "입차시간": fmt_time(
                    vehicle.get("entered_at")
                ),
                "배정 주차면": (
                    vehicle.get("space") or "미배정"
                )
            }
        )

    st.dataframe(
        vehicle_rows,
        use_container_width=True,
        hide_index=True
    )

else:
    st.info("현재 입차 중인 차량 기록이 없습니다.")


# ====================================
# OTHER FUNCTIONS
# ====================================

st.divider()

tab1, tab2, tab3, tab4 = st.tabs(
    [
        "🔎 내 차 찾기",
        "🚗 주차면 배정",
        "📋 입출차 기록",
        "🚙 수동 출차"
    ]
)


# ====================================
# TAB 1: FIND MY CAR
# ====================================

with tab1:

    search = st.text_input(
        "차량번호 입력",
        key="search_input"
    )

    if st.button("차량 조회"):

        plate = normalize_plate(search)

        found = next(
            (
                v for v in active
                if v["plate"] == plate
            ),
            None
        )

        if found:

            st.success(
                f"차량번호: {plate}"
            )

            st.write(
                "입차시간:",
                fmt_time(found.get("entered_at"))
            )

            st.write(
                "배정 주차면:",
                found.get("space") or "미배정"
            )

        else:
            st.warning(
                "입차 중인 차량이 없습니다."
            )


# ====================================
# TAB 2: ASSIGN PARKING SPACE
# ====================================

with tab2:

    st.caption(
        "수동 차량 배정 기능입니다. "
        "센서가 EMPTY이고 차량번호가 "
        "미배정인 칸만 표시합니다."
    )

    waiting = [
        v for v in active
        if not v.get("space")
    ]

    try:
        assignable_spaces = db_get(
            "parking_spaces",
            {
                "select": "name,plate,sensor_status",
                "name": "in.(A-1,A-2,A-3)"
            }
        )

        free = [
            space["name"]
            for space in assignable_spaces
            if (
                not space.get("plate")
                and space.get("sensor_status") == "EMPTY"
            )
        ]

    except Exception as error:
        st.error(f"배정 가능 주차면 조회 오류: {error}")
        free = []

    if waiting and free:

        with st.form("assign_form"):

            vehicle = st.selectbox(
                "차량 선택",
                waiting,
                format_func=lambda v: v["plate"]
            )

            selected_space = st.selectbox(
                "주차면 선택",
                free
            )

            submit = st.form_submit_button(
                "배정하기"
            )

        if submit:

            try:
                updated_space = db_update(
                    "parking_spaces",
                    {
                        "name": f"eq.{selected_space}",
                        "plate": "is.null",
                        "sensor_status": "eq.EMPTY"
                    },
                    {
                        "plate": vehicle["plate"]
                    }
                )

                if not updated_space:

                    st.warning(
                        "이미 사용 중이거나 "
                        "빈자리가 아닌 주차면입니다."
                    )

                else:

                    updated_visit = db_update(
                        "parking_visits",
                        {
                            "id": f"eq.{vehicle['id']}",
                            "space": "is.null"
                        },
                        {
                            "space": selected_space
                        }
                    )

                    if updated_visit:

                        st.success(
                            f"{vehicle['plate']} 차량 "
                            f"{selected_space} 배정 완료"
                        )

                        st.rerun()

                    else:

                        db_update(
                            "parking_spaces",
                            {
                                "name": f"eq.{selected_space}",
                                "plate": f"eq.{vehicle['plate']}"
                            },
                            {
                                "plate": None
                            }
                        )

                        st.error(
                            "배정 기록 업데이트 실패"
                        )

            except Exception as error:

                st.error(
                    f"주차면 배정 오류: {error}"
                )

    else:
        st.info(
            "미배정 차량이나 배정 가능한 "
            "빈 주차면이 없습니다."
        )


# ====================================
# TAB 3: ENTRY / EXIT HISTORY
# ====================================

with tab3:

    try:
        visits = db_get(
            "parking_visits",
            {
                "select": (
                    "plate,entered_at,"
                    "exited_at,space,fee"
                ),
                "order": "id.desc",
                "limit": "100"
            }
        )

        st.dataframe(
            visits,
            use_container_width=True,
            hide_index=True
        )

    except Exception as error:

        st.error(
            f"기록 조회 실패: {error}"
        )


# ====================================
# TAB 4: MANUAL EXIT
# ====================================

with tab4:

    st.warning(
        "수동 출차는 DB 기록만 변경하며 "
        "실제 차단기는 움직이지 않습니다."
    )

    if active:

        with st.form("manual_exit_form"):

            vehicle = st.selectbox(
                "출차할 차량",
                active,
                format_func=lambda v: v["plate"]
            )

            submit_exit = st.form_submit_button(
                "선택 차량 출차 확정"
            )

        if submit_exit:

            try:

                ok, message = process_exit(
                    vehicle["plate"]
                )

                if ok:
                    st.success(message)
                    st.rerun()

                else:
                    st.warning(message)

            except Exception as error:

                st.error(
                    f"출차 처리 오류: {error}"
                )

    else:

        st.info(
            "출차 처리할 차량이 없습니다."
        )


# ====================================
# FOOTER
# ====================================

st.divider()

st.caption(
    "스마트 주차장 캡스톤디자인 · "
    "라즈베리파이 자동 촬영/OCR · "
    "ESP32 주차센서"
)
