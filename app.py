
"""Smart Parking dashboard: sensor bays A-1..A-3 and separate visit records."""

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
# PARKING SPACE SETTINGS
# ====================================

SENSOR_SPACES = ("A-1", "A-2", "A-3")

# Marker written by Raspberry Pi sensor sync
SENSOR_MARKER = "SENSOR_OCCUPIED"


# ====================================
# SUPABASE CONNECTION
# ====================================

try:
    URL = st.secrets["SUPABASE_URL"].strip().rstrip("/")
    KEY = st.secrets["SUPABASE_ANON_KEY"].strip()

except Exception:
    st.error("Supabase Secrets 설정을 확인하세요.")
    st.stop()


HEADERS = {
    "apikey": KEY,
    "Authorization": f"Bearer {KEY}",
    "Content-Type": "application/json"
}


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
# VEHICLE LOOKUP
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


# ====================================
# VEHICLE EXIT / PARKING FEE
# ====================================

def process_exit(plate):

    vehicle = get_active_vehicle(plate)

    if not vehicle:
        return False, "입차 기록이 없는 차량입니다."

    now = datetime.now(timezone.utc)

    entered = datetime.fromisoformat(
        vehicle["entered_at"].replace("Z", "+00:00")
    )

    if entered.tzinfo is None:
        entered = entered.replace(
            tzinfo=timezone.utc
        )

    seconds = max(
        0,
        (now - entered).total_seconds()
    )

    # 2,000 KRW per hour
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
        return False, "출차 기록 저장에 실패했습니다."

    # Clear only the exact assigned vehicle plate.
    # Never modify SENSOR_OCCUPIED.
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

    return True, (
        f"{plate} 출차 완료 · 요금 {fee:,}원"
    )


# ====================================
# LIVE PARKING STATUS
# ====================================

st.subheader("📊 주차장 실시간 현황")

if st.button("🔄 현황 새로고침"):
    st.rerun()


try:
    # Only the three actually installed sensors
    spaces = db_get(
        "parking_spaces",
        {
            "select": "name,plate",
            "name": "in.(A-1,A-2,A-3)",
            "order": "name.asc"
        }
    )

    # Vehicle entry records are separate
    active = db_get(
        "parking_visits",
        {
            "select": "id,plate,entered_at,space",
            "exited_at": "is.null",
            "order": "entered_at.asc"
        }
    )

except Exception as error:

    st.error(
        f"데이터베이스 조회 오류: {error}"
    )

    st.stop()


by_name = {
    space["name"]: space
    for space in spaces
}


# ====================================
# SENSOR STATE
# ====================================

def space_state(space):

    if space is None:
        return "미확인"

    plate = space.get("plate")

    # Sensor detected a vehicle
    if plate == SENSOR_MARKER:
        return "PARKING"

    # Current legacy DB behavior
    if plate is None or plate == "":
        return "EMPTY"

    # Real plate is not a sensor measurement
    return "미확인"


states = {
    name: space_state(by_name.get(name))
    for name in SENSOR_SPACES
}

occupied = sum(
    state == "PARKING"
    for state in states.values()
)

empty = sum(
    state == "EMPTY"
    for state in states.values()
)

unknown = sum(
    state == "미확인"
    for state in states.values()
)


# ====================================
# PARKING COUNTS
# ====================================

c1, c2, c3, c4 = st.columns(4)

c1.metric(
    "센서 설치 주차면",
    len(SENSOR_SPACES)
)

c2.metric(
    "빈자리 (추정)",
    empty
)

c3.metric(
    "감지된 사용 중",
    occupied
)

c4.metric(
    "상태 미확인",
    unknown
)

st.caption(
    f"현재 입차 기록: {len(active)}대 · "
    "입차 차량 수와 실제 주차 칸 수는 별개입니다."
)


# ====================================
# PARKING SPACE DISPLAY
# ====================================

st.subheader("🅿️ 주차공간 센서 현황")

st.caption(
    "실제 초음파센서가 설치된 "
    "A-1, A-2, A-3만 표시합니다."
)

columns = st.columns(3)

for col, name in zip(columns, SENSOR_SPACES):

    state = states[name]

    with col:

        if state == "PARKING":

            st.error(
                f"🚘 {name} · PARKING"
            )

        elif state == "EMPTY":

            st.success(
                f"🅿️ {name} · EMPTY"
            )

        else:

            st.warning(
                f"❔ {name} · 센서 상태 미확인"
            )

            current_plate = (
                by_name.get(name, {}).get("plate")
            )

            if current_plate not in (
                None,
                "",
                SENSOR_MARKER
            ):

                st.caption(
                    "기존 차량번호 배정은 "
                    "센서 판정이 아닙니다."
                )


st.info(
    "현재 데이터베이스에는 센서 전용 상태 "
    "컬럼이 없습니다. 차량번호가 배정된 칸은 "
    "'센서 상태 미확인'으로 표시합니다. "
    "실제 센서값과 차량번호를 완전히 분리하려면 "
    "Supabase에 sensor_status 컬럼을 추가하고 "
    "라즈베리파이 동기화 코드를 변경해야 합니다."
)


# ====================================
# ENTRY VEHICLE RECORDS
# ====================================

st.subheader(
    "🚗 입차 차량 현황 (번호판 OCR 기록)"
)

if active:

    vehicle_rows = []

    for vehicle in active:

        vehicle_rows.append(
            {
                "차량번호": vehicle["plate"],
                "입차시간": fmt_time(
                    vehicle.get("entered_at")
                ),
                "수동 배정 주차면": (
                    vehicle.get("space")
                    or "미배정"
                )
            }
        )

    st.dataframe(
        vehicle_rows,
        use_container_width=True,
        hide_index=True
    )

else:

    st.info(
        "현재 입차 중인 차량 기록이 없습니다."
    )


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
# TAB 1 - FIND MY CAR
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
                vehicle
                for vehicle in active
                if vehicle["plate"] == plate
            ),
            None
        )

        if found:

            st.success(
                f"차량번호: {plate}"
            )

            st.write(
                "입차시간:",
                fmt_time(
                    found.get("entered_at")
                )
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
# TAB 2 - ASSIGN SPACE
# ====================================

with tab2:

    st.caption(
        "이 기능은 수동 차량 배정입니다. "
        "초음파센서가 차량번호를 인식하는 "
        "기능은 아닙니다."
    )

    waiting = [
        vehicle
        for vehicle in active
        if not vehicle.get("space")
    ]

    free = [
        name
        for name in SENSOR_SPACES
        if (
            by_name.get(name)
            and not by_name[name].get("plate")
        )
    ]

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
                        "plate": "is.null"
                    },
                    {
                        "plate": vehicle["plate"]
                    }
                )

                if not updated_space:

                    st.warning(
                        "이미 사용 중인 주차면입니다."
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

                        # Roll back space assignment
                        db_update(
                            "parking_spaces",
                            {
                                "name": f"eq.{selected_space}",
                                "plate": (
                                    f"eq.{vehicle['plate']}"
                                )
                            },
                            {
                                "plate": None
                            }
                        )

                        st.error(
                            "입차 기록 업데이트에 실패하여 "
                            "배정을 취소했습니다."
                        )

            except Exception as error:

                st.error(
                    f"주차면 배정 오류: {error}"
                )

    else:

        st.info(
            "미배정 차량이나 배정 가능한 "
            "주차면이 없습니다."
        )


# ====================================
# TAB 3 - ENTRY / EXIT HISTORY
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
# TAB 4 - MANUAL EXIT
# ====================================

with tab4:

    st.warning(
        "수동 출차는 실제 차단기를 움직이지 "
        "않으며 DB 기록만 변경합니다."
    )

    if active:

        with st.form("manual_exit_form"):

            vehicle = st.selectbox(
                "출차할 차량",
                active,
                format_func=lambda v: v["plate"]
            )

            submit_exit = (
                st.form_submit_button(
                    "선택 차량 출차 확정"
                )
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
