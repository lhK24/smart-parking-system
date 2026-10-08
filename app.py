
import streamlit as st
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from streamlit_autorefresh import st_autorefresh

st.set_page_config(
    page_title="스마트 주차장",
    page_icon="🚗",
    layout="wide"
)

st.title("🚗 스마트 주차장 관리 시스템")
st.caption("Google Colab 번호판 인식 · Supabase 연동")
st_autorefresh(interval=5000, key="parking_refresh")

# Supabase 연결
try:
    URL = st.secrets["SUPABASE_URL"].rstrip("/")
    KEY = st.secrets["SUPABASE_ANON_KEY"]
except Exception:
    st.error(
        "Streamlit Cloud의 Secrets에 "
        "SUPABASE_URL과 SUPABASE_ANON_KEY를 등록해야 합니다."
    )
    st.stop()

HEADERS = {
    "apikey": KEY,
    "Authorization": f"Bearer {KEY}",
    "Content-Type": "application/json",
}

def get_rows(table, params=None):
    response = requests.get(
        f"{URL}/rest/v1/{table}",
        headers=HEADERS,
        params=params,
        timeout=15
    )
    response.raise_for_status()
    return response.json()

def patch_rows(table, params, values):
    response = requests.patch(
        f"{URL}/rest/v1/{table}",
        headers={
            **HEADERS,
            "Prefer": "return=representation"
        },
        params=params,
        json=values,
        timeout=15
    )
    response.raise_for_status()
    return response.json()

def korean_time(value):
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(
            ZoneInfo("Asia/Seoul")
        ).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return value

# 데이터 조회
try:
    spaces = get_rows(
        "parking_spaces",
        {
            "select": "name,plate",
            "order": "name.asc"
        }
    )

    active = get_rows(
        "parking_visits",
        {
            "select": "id,plate,entered_at,space",
            "exited_at": "is.null",
            "order": "entered_at.asc"
        }
    )

except Exception as e:
    st.error(f"Supabase 연결 오류: {e}")
    st.info("Supabase SQL 테이블과 Streamlit Secrets를 확인하세요.")
    st.stop()

# 주차장 현황
occupied = sum(1 for s in spaces if s["plate"])
total = len(spaces)

c1, c2, c3, c4 = st.columns(4)

c1.metric("전체 주차면", total)
c2.metric("빈 주차면", total - occupied)
c3.metric("사용 중", occupied)
c4.metric("입차 차량", len(active))

st.divider()

st.subheader("🅿️ 실시간 주차 공간")

for i in range(0, len(spaces), 3):
    cols = st.columns(3)

    for col, space in zip(cols, spaces[i:i + 3]):
        with col:
            if space["plate"]:
                st.error(
                    f"🚘 {space['name']}\n\n"
                    f"차량번호: {space['plate']}"
                )
            else:
                st.success(
                    f"🅿️ {space['name']}\n\n빈자리"
                )

st.divider()

tab1, tab2, tab3 = st.tabs([
    "🔎 내 차 찾기",
    "🚘 주차면 배정",
    "📋 입출차 기록"
])

# 내 차 찾기
with tab1:
    st.subheader("차량 위치 조회")

    search_plate = st.text_input(
        "차량번호를 입력하세요",
        placeholder="123가4568"
    )

    if st.button("차량 찾기"):
        target = search_plate.strip().replace(" ", "")

        matches = [
            v for v in active
            if v["plate"] == target
        ]

        if matches:
            car = matches[0]

            st.success(f"차량번호: {car['plate']}")
            st.info(
                f"주차 위치: {car['space'] or '아직 미배정'}"
            )
            st.write(
                "입차 시간:",
                korean_time(car["entered_at"])
            )
        else:
            st.warning("현재 주차 중인 차량이 없습니다.")

# 주차면 배정
with tab2:
    st.subheader("주차면 배정")
    st.caption(
        "초음파 센서 연결 전까지 사용하는 시뮬레이션 기능입니다."
    )

    waiting = [
        v for v in active
        if not v["space"]
    ]

    free_spaces = [
        s["name"] for s in spaces
        if not s["plate"]
    ]

    if waiting and free_spaces:
        with st.form("assign_form"):
            selected_car = st.selectbox(
                "입차 차량",
                waiting,
                format_func=lambda x: x["plate"]
            )

            selected_space = st.selectbox(
                "빈 주차면",
                free_spaces
            )

            submitted = st.form_submit_button(
                "주차면 배정"
            )

        if submitted:
            try:
                updated_space = patch_rows(
                    "parking_spaces",
                    {
                        "name": f"eq.{selected_space}",
                        "plate": "is.null"
                    },
                    {
                        "plate": selected_car["plate"]
                    }
                )

                if not updated_space:
                    st.warning(
                        "이미 사용 중인 주차면입니다. 새로고침하세요."
                    )
                else:
                    updated_visit = patch_rows(
                        "parking_visits",
                        {
                            "id": f"eq.{selected_car['id']}",
                            "space": "is.null",
                            "exited_at": "is.null"
                        },
                        {
                            "space": selected_space
                        }
                    )

                    if not updated_visit:
                        # 두 번째 저장 실패 시 주차면 복구 시도
                        patch_rows(
                            "parking_spaces",
                            {
                                "name": f"eq.{selected_space}",
                                "plate": f"eq.{selected_car['plate']}"
                            },
                            {"plate": None}
                        )
                        st.error("배정 실패. 다시 시도하세요.")
                    else:
                        st.success("주차면 배정 완료!")
                        st.rerun()

            except Exception as e:
                st.error(f"배정 오류: {e}")
    else:
        st.info(
            "배정 대기 차량이 없거나 빈 주차면이 없습니다."
        )

# 입출차 기록
with tab3:
    st.subheader("자동 입출차 기록")

    try:
        visits = get_rows(
            "parking_visits",
            {
                "select": "plate,entered_at,exited_at,space,fee",
                "order": "id.desc",
                "limit": "100"
            }
        )

        history = []

        for v in visits:
            history.append({
                "차량번호": v["plate"],
                "입차 시간": korean_time(v["entered_at"]),
                "출차 시간": korean_time(v["exited_at"]),
                "주차 위치": v["space"] or "-",
                "주차요금(원)": (
                    v["fee"] if v["fee"] is not None else "-"
                ),
                "상태": (
                    "출차 완료"
                    if v["exited_at"]
                    else "주차 중"
                )
            })

        st.dataframe(
            history,
            use_container_width=True,
            hide_index=True
        )

    except Exception as e:
        st.error(f"기록 조회 오류: {e}")

st.divider()
st.caption(
    "캡스톤 시연용 시스템 · 5초마다 자동 갱신 · "
    "실제 결제는 수행하지 않습니다."
)

