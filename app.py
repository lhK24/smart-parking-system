
import streamlit as st
import requests
import easyocr
import numpy as np
import re
import hashlib

from PIL import Image, ImageOps
from io import BytesIO
from datetime import datetime, timezone
from math import ceil


# ==========================================
# 1. 기본 설정
# ==========================================

st.set_page_config(
    page_title="스마트 주차장",
    page_icon="🚗",
    layout="wide"
)

st.title("🚗 스마트 주차장 관리 시스템")
st.caption("카메라 번호판 인식 · 입출차 관리 · 주차 공간 현황")


# ==========================================
# 2. Supabase 연결
# ==========================================

try:
    URL = st.secrets["SUPABASE_URL"].strip().rstrip("/")
    KEY = st.secrets["SUPABASE_ANON_KEY"].strip()
except Exception:
    st.error("Streamlit Secrets에서 Supabase 설정을 확인하세요.")
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


def db_insert(table, data):
    response = requests.post(
        f"{URL}/rest/v1/{table}",
        headers={**HEADERS, "Prefer": "return=representation"},
        json=data,
        timeout=15
    )
    response.raise_for_status()
    return response.json()


def db_update(table, params, data):
    response = requests.patch(
        f"{URL}/rest/v1/{table}",
        headers={**HEADERS, "Prefer": "return=representation"},
        params=params,
        json=data,
        timeout=15
    )
    response.raise_for_status()
    return response.json()


# ==========================================
# 3. 한글 번호판 OCR
# ==========================================

@st.cache_resource(show_spinner=False)
def load_ocr():
    return easyocr.Reader(["ko", "en"], gpu=False)


def normalize_plate(text):
    return re.sub(
        r"[^0-9가-힣]",
        "",
        text
    )


def valid_plate(text):
    return bool(
        re.fullmatch(r"\d{2,3}[가-힣]\d{4}", text)
    )


def recognize_plate(photo_bytes):

    image = Image.open(
        BytesIO(photo_bytes)
    ).convert("RGB")

    image = ImageOps.exif_transpose(image)

    # 큰 사진을 줄여 서버 부하 완화
    if image.width > 1200:
        new_height = round(
            image.height * 1200 / image.width
        )
        image = image.resize(
            (1200, new_height)
        )

    reader = load_ocr()

    results = reader.readtext(
        np.array(image),
        detail=0,
        paragraph=False,
        batch_size=1,
        workers=0,
        canvas_size=1280
    )

    # 개별 인식 문자열부터 검사
    candidates = [
        normalize_plate(str(item))
        for item in results
    ]

    for candidate in candidates:
        match = re.search(
            r"\d{2,3}[가-힣]\d{4}",
            candidate
        )
        if match:
            return match.group(), results

    # 번호판이 여러 조각으로 읽힌 경우
    combined = normalize_plate(
        "".join(str(item) for item in results)
    )

    match = re.search(
        r"\d{2,3}[가-힣]\d{4}",
        combined
    )

    if match:
        return match.group(), results

    return "", results


# ==========================================
# 4. 입차 / 출차 처리
# ==========================================

def get_active_vehicle(plate):
    vehicles = db_get(
        "parking_visits",
        {
            "select": "id,plate,entered_at,space",
            "plate": f"eq.{plate}",
            "exited_at": "is.null",
            "limit": "1"
        }
    )

    return vehicles[0] if vehicles else None


def process_entry(plate):

    existing = get_active_vehicle(plate)

    if existing:
        return False, "이미 입차 중인 차량입니다."

    now = datetime.now(timezone.utc).isoformat()

    result = db_insert(
        "parking_visits",
        {
            "plate": plate,
            "entered_at": now,
            "space": None
        }
    )

    if not result:
        return False, "입차 기록이 저장되지 않았습니다."

    return True, f"{plate} 차량 입차 완료"


def process_exit(plate):

    vehicle = get_active_vehicle(plate)

    if not vehicle:
        return False, "현재 입차 중인 차량이 없습니다."

    now = datetime.now(timezone.utc)

    entered_at = datetime.fromisoformat(
        vehicle["entered_at"].replace("Z", "+00:00")
    )

    if entered_at.tzinfo is None:
        entered_at = entered_at.replace(tzinfo=timezone.utc)

    elapsed_seconds = max(
        0,
        (now - entered_at).total_seconds()
    )

    # 1시간당 2,000원, 올림 계산
    fee = max(
        2000,
        ceil(elapsed_seconds / 3600) * 2000
    )

    result = db_update(
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

    if not result:
        return False, "출차 기록 갱신에 실패했습니다."

    # 배정된 주차면 해제
    space = vehicle.get("space")

    if space:
        cleared = db_update(
            "parking_spaces",
            {
                "name": f"eq.{space}",
                "plate": f"eq.{plate}"
            },
            {
                "plate": None
            }
        )

        if not cleared:
            return (
                False,
                "출차 기록은 저장됐지만 주차면 해제를 확인하지 못했습니다."
            )

    return True, f"{plate} 출차 완료 · 요금 {fee:,}원"


# ==========================================
# 5. 카메라 및 번호판 인식
# ==========================================

st.subheader("📷 차량 번호판 자동 인식")

camera_mode = st.radio(
    "카메라 위치 선택",
    ["입구", "출구"],
    horizontal=True
)

st.info(
    "카메라로 번호판을 촬영한 뒤 "
    "'번호판 인식하기'를 눌러주세요."
)

photo = st.camera_input(
    "차량 번호판 촬영",
    key="parking_camera"
)

if "recognized_plate" not in st.session_state:
    st.session_state.recognized_plate = ""

if "photo_hash" not in st.session_state:
    st.session_state.photo_hash = ""

if "processed_hashes" not in st.session_state:
    st.session_state.processed_hashes = []


if photo is not None:

    photo_bytes = photo.getvalue()

    current_hash = hashlib.sha256(
        photo_bytes
    ).hexdigest()

    # 새 사진이면 이전 OCR 결과 삭제
    if st.session_state.photo_hash != current_hash:
        st.session_state.photo_hash = current_hash
        st.session_state.recognized_plate = ""

    st.image(
        photo_bytes,
        caption="촬영된 번호판",
        use_container_width=True
    )

    if st.button(
        "🔍 번호판 인식하기",
        type="primary"
    ):

        try:
            with st.spinner(
                "한국 번호판 인식 중..."
            ):
                plate, raw_results = recognize_plate(
                    photo_bytes
                )

            if plate:
                st.session_state.recognized_plate = plate
                st.success(f"번호판 인식: {plate}")
            else:
                st.session_state.recognized_plate = ""
                st.warning(
                    "번호판을 정확하게 읽지 못했습니다. "
                    "아래 입력칸에서 직접 수정할 수 있습니다."
                )

            with st.expander("OCR 분석 결과"):
                st.write(raw_results)

        except Exception as e:
            st.error(f"번호판 인식 오류: {e}")

    st.divider()

    st.write("**인식된 번호판 확인**")

    plate_text = st.text_input(
        "차량번호",
        value=st.session_state.recognized_plate,
        placeholder="예: 123가4567",
        key=f"plate_input_{current_hash}"
    )

    final_plate = normalize_plate(plate_text)

    if final_plate and not valid_plate(final_plate):
        st.warning(
            "일반 번호판 형식으로 입력해 주세요. "
            "예: 12가3456 또는 123가4567"
        )

    action = "입차" if camera_mode == "입구" else "출차"

    if st.button(
        f"✅ {action} 확정",
        disabled=not valid_plate(final_plate)
    ):

        process_key = current_hash + ":" + action

        if process_key in st.session_state.processed_hashes:
            st.warning(
                "이 사진은 이미 처리했습니다. "
                "새 사진을 촬영해 주세요."
            )
        else:
            try:
                if camera_mode == "입구":
                    success, message = process_entry(
                        final_plate
                    )
                else:
                    success, message = process_exit(
                        final_plate
                    )

                if success:
                    st.session_state.processed_hashes.append(
                        process_key
                    )
                    st.success(message)
                else:
                    st.warning(message)

            except Exception as e:
                st.error(f"입출차 처리 오류: {e}")


# ==========================================
# 6. 주차장 데이터
# ==========================================

st.divider()
st.subheader("📊 실시간 주차 현황")

if st.button("🔄 새로고침"):
    st.rerun()

try:
    spaces = db_get(
        "parking_spaces",
        {
            "select": "name,plate",
            "order": "name.asc"
        }
    )

    active = db_get(
        "parking_visits",
        {
            "select": "id,plate,entered_at,space",
            "exited_at": "is.null",
            "order": "entered_at.asc"
        }
    )

except Exception as e:
    st.error(f"주차장 데이터 조회 오류: {e}")
    st.stop()

occupied = sum(
    bool(s["plate"])
    for s in spaces
)

col1, col2, col3, col4 = st.columns(4)

col1.metric("전체 주차면", len(spaces))
col2.metric("빈자리", len(spaces) - occupied)
col3.metric("사용 중", occupied)
col4.metric("입차 차량", len(active))


# ==========================================
# 7. 주차면 표시
# ==========================================

st.subheader("🅿️ 주차 공간 현황")

for i in range(0, len(spaces), 3):

    cols = st.columns(3)

    for col, space in zip(cols, spaces[i:i + 3]):

        with col:
            if space["plate"]:
                st.error(
                    f"🚘 {space['name']} · {space['plate']}"
                )
            else:
                st.success(
                    f"🅿️ {space['name']} · 빈자리"
                )


# ==========================================
# 8. 차량 조회 / 공간 배정 / 기록
# ==========================================

tab1, tab2, tab3 = st.tabs([
    "🔎 내 차 찾기",
    "🚗 주차면 배정",
    "📋 입출차 기록"
])


with tab1:

    query = st.text_input(
        "찾을 차량번호",
        key="search_plate"
    )

    if st.button("조회"):

        target = normalize_plate(query)

        matches = [
            v for v in active
            if v["plate"] == target
        ]

        if matches:
            v = matches[0]

            st.success(
                f"주차 위치: {v['space'] or '미배정'}"
            )
            st.write(
                f"입차 시간: {v['entered_at']}"
            )
        else:
            st.warning("해당 차량을 찾지 못했습니다.")


with tab2:

    waiting = [
        v for v in active
        if not v["space"]
    ]

    free = [
        s["name"] for s in spaces
        if not s["plate"]
    ]

    if waiting and free:

        with st.form("assign_form"):

            vehicle = st.selectbox(
                "차량",
                waiting,
                format_func=lambda v: v["plate"]
            )

            chosen_space = st.selectbox(
                "주차면",
                free
            )

            submitted = st.form_submit_button(
                "배정하기"
            )

        if submitted:

            try:
                updated_space = db_update(
                    "parking_spaces",
                    {
                        "name": f"eq.{chosen_space}",
                        "plate": "is.null"
                    },
                    {
                        "plate": vehicle["plate"]
                    }
                )

                if not updated_space:
                    st.error("이미 사용 중인 주차면입니다.")

                else:
                    updated_visit = db_update(
                        "parking_visits",
                        {
                            "id": f"eq.{vehicle['id']}",
                            "space": "is.null"
                        },
                        {
                            "space": chosen_space
                        }
                    )

                    if updated_visit:
                        st.success("주차면 배정 완료")
                        st.rerun()
                    else:
                        st.error(
                            "입차 기록 배정에 실패했습니다. "
                            "주차면 데이터 확인이 필요합니다."
                        )

            except Exception as e:
                st.error(f"배정 오류: {e}")

    else:
        st.info(
            "대기 차량 또는 빈 주차면이 없습니다."
        )


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

    except Exception as e:
        st.error(str(e))


st.divider()

st.caption(
    "캡스톤 시연용 시스템입니다. "
    "실제 차량번호 대신 시험용 번호를 사용하세요."
)
