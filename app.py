
import streamlit as st
import requests
from datetime import datetime

# =====================================
# 1. 기본 설정
# =====================================

st.set_page_config(
    page_title="스마트 주차장",
    page_icon="🚗",
    layout="wide"
)

st.title("🚗 스마트 주차장 · 실시간 현황")
st.caption("휴대폰 카메라 · Supabase · 스마트 주차 관리")


# =====================================
# 2. Supabase 연결
# =====================================

try:
    URL = st.secrets["SUPABASE_URL"].strip().rstrip("/")
    KEY = st.secrets["SUPABASE_ANON_KEY"].strip()

    if not URL.startswith("https://") or not KEY:
        raise ValueError("Supabase URL 또는 API 키가 올바르지 않습니다.")

except Exception:
    st.error(
        "Streamlit Secrets에 SUPABASE_URL과 "
        "SUPABASE_ANON_KEY를 등록하세요."
    )
    st.stop()

HEADERS = {
    "apikey": KEY,
    "Authorization": f"Bearer {KEY}",
}


def fetch(table, params):
    response = requests.get(
        f"{URL}/rest/v1/{table}",
        headers=HEADERS,
        params=params,
        timeout=12
    )
    response.raise_for_status()
    return response.json()


def update(table, match, data):
    response = requests.patch(
        f"{URL}/rest/v1/{table}",
        headers={
            **HEADERS,
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        },
        params=match,
        json=data,
        timeout=12
    )
    response.raise_for_status()
    return response.json()


# =====================================
# 3. 사이트 내부 카메라
# =====================================

st.subheader("📷 스마트 주차장 카메라")

st.info(
    "Colab 없이 이 사이트에서 휴대폰 카메라를 "
    "직접 사용할 수 있습니다."
)

camera_location = st.radio(
    "카메라 위치",
    ["입구", "출구"],
    horizontal=True
)

photo = st.camera_input(
    "차량 번호판 촬영",
    key="parking_camera"
)

if photo is not None:
    st.image(
        photo,
        caption=f"{camera_location} 카메라 촬영 사진",
        use_container_width=True
    )

    st.success("✅ 카메라 촬영 성공")

    st.warning(
        "현재는 사진 촬영 테스트 단계입니다. "
        "번호판 자동 인식 및 자동 입출차 기능은 "
        "아직 연결되지 않았습니다."
    )


# =====================================
# 4. 주차장 데이터 조회
# =====================================

try:
    spaces = fetch(
        "parking_spaces",
        {
            "select": "name,plate",
            "order": "name.asc"
        }
    )

    active = fetch(
        "parking_visits",
        {
            "select": "id,plate,entered_at,space",
            "exited_at": "is.null",
            "order": "entered_at.asc"
        }
    )

except Exception as e:
    st.error(f"데이터베이스 연결 실패: {e}")
    st.stop()


# =====================================
# 5. 실시간 주차 현황
# =====================================

st.divider()
st.subheader("📊 주차장 현황")

occupied = sum(
    bool(space["plate"])
    for space in spaces
)

total = len(spaces)
free_count = total - occupied

col1, col2, col3, col4 = st.columns(4)

col1.metric("전체 주차면", total)
col2.metric("빈자리", free_count)
col3.metric("사용 중", occupied)
col4.metric("입차 차량", len(active))

if st.button("🔄 주차 현황 새로고침"):
    st.rerun()


# =====================================
# 6. 주차 공간 표시
# =====================================

st.subheader("🅿️ 주차 공간 현황")

for i in range(0, len(spaces), 3):

    columns = st.columns(3)

    for col, space in zip(
        columns,
        spaces[i:i + 3]
    ):

        with col:

            name = space["name"]
            plate = space["plate"]

            if plate:
                st.error(
                    f"🚘 {name} · {plate}"
                )
            else:
                st.success(
                    f"🅿️ {name} · 빈자리"
                )


# =====================================
# 7. 관리 메뉴
# =====================================

tab1, tab2, tab3 = st.tabs([
    "🔎 내 차 찾기",
    "🚗 주차면 배정",
    "📋 입출차 기록"
])


# =====================================
# 8. 차량 위치 조회
# =====================================

with tab1:

    st.subheader("내 차량 위치 조회")

    plate_input = st.text_input(
        "차량번호 입력",
        placeholder="예: 123가4567"
    )

    if st.button("차량 조회"):

        search_plate = (
            plate_input.strip().replace(" ", "")
        )

        matches = [
            visit
            for visit in active
            if visit["plate"] == search_plate
        ]

        if matches:

            vehicle = matches[0]

            location = (
                vehicle["space"]
                or "미배정"
            )

            st.success(
                f"🚗 차량번호: {search_plate}"
            )

            st.info(
                f"주차 위치: {location}"
            )

            st.write(
                f"입차 시간: {vehicle['entered_at']}"
            )

        else:
            st.warning(
                "현재 주차 중인 차량이 없습니다."
            )


# =====================================
# 9. 주차 공간 수동 배정
# =====================================

with tab2:

    st.subheader("주차면 배정")

    st.caption(
        "현재는 센서 연결 전이므로 "
        "시연용 수동 배정 기능입니다."
    )

    waiting = [
        visit
        for visit in active
        if not visit["space"]
    ]

    free_spaces = [
        space["name"]
        for space in spaces
        if not space["plate"]
    ]

    if waiting and free_spaces:

        with st.form("assign_form"):

            vehicle = st.selectbox(
                "배정할 차량",
                waiting,
                format_func=lambda x: x["plate"]
            )

            selected_space = st.selectbox(
                "주차 공간",
                free_spaces
            )

            submitted = st.form_submit_button(
                "주차 공간 배정"
            )

        if submitted:

            try:

                result = update(
                    "parking_spaces",
                    {
                        "name": f"eq.{selected_space}",
                        "plate": "is.null"
                    },
                    {
                        "plate": vehicle["plate"]
                    }
                )

                if not result:
                    st.error(
                        "주차 공간이 이미 사용 중이거나 "
                        "변경 권한이 없습니다."
                    )
                    st.stop()

                result2 = update(
                    "parking_visits",
                    {
                        "id": f"eq.{vehicle['id']}",
                        "space": "is.null"
                    },
                    {
                        "space": selected_space
                    }
                )

                if result2:

                    st.success(
                        f"{vehicle['plate']} 차량을 "
                        f"{selected_space}에 배정했습니다."
                    )

                    st.rerun()

                else:
                    # 두 테이블의 변경은 원자적이지 않음.
                    # 일관성을 위해 관리자 확인이 필요함.
                    st.error(
                        "입차 기록 갱신에 실패했습니다. "
                        "주차 공간 데이터 확인이 필요합니다."
                    )

            except Exception as e:

                st.error(
                    f"배정 처리 오류: {e}"
                )

    else:

        st.info(
            "배정 대기 차량이 없거나 "
            "빈 주차 공간이 없습니다."
        )


# =====================================
# 10. 입출차 기록
# =====================================

with tab3:

    st.subheader("차량 입출차 기록")

    try:

        visits = fetch(
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

        if visits:

            st.dataframe(
                visits,
                use_container_width=True,
                hide_index=True
            )

        else:

            st.info(
                "아직 입출차 기록이 없습니다."
            )

    except Exception as e:

        st.error(
            f"기록 조회 실패: {e}"
        )


# =====================================
# 11. 하단 안내
# =====================================

st.divider()

st.caption(
    "스마트 주차장 캡스톤디자인 · "
    "카메라 촬영 및 주차 현황 확인"
)

st.caption(
    "현재 번호판 자동 인식과 자동 입출차는 "
    "구현 전입니다. 실제 차량번호 대신 "
    "시연용 데이터를 사용하세요."
)
