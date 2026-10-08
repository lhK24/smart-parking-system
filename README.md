# 스마트 주차장 — 휴대폰 카메라 실시간 프레임 인식

- `streamlit-webrtc`와 `av`를 사용하지 않습니다. 휴대폰 브라우저의 `getUserMedia`로 카메라를 열고 2.2초 간격으로 JPEG 프레임을 Streamlit 커스텀 컴포넌트로 전달합니다.
- GitHub 저장소에 `app.py`, `requirements.txt`, **`frontend/index.html`**을 동일한 구조로 업로드하세요.
- Streamlit Cloud는 HTTPS를 사용하므로 브라우저에서 카메라 권한을 허용하세요.
- 브라우저/iframe의 카메라 권한 정책 때문에 일부 환경에서 카메라가 거부될 수 있습니다. 그 경우 별도 HTTPS 카메라 수집 페이지 및 API 서버 방식이 필요합니다.
- EasyOCR 첫 실행 시 모델 다운로드가 필요합니다. 모델은 CPU에서 실행되므로 프레임 처리 속도가 느릴 수 있습니다.
- YOLO 번호판 영역 검출을 포함하지 않은 OCR 프로토타입입니다. 자동 인식 정확도는 보장되지 않습니다.
- Streamlit Cloud의 SQLite 파일은 영구 저장이 아닙니다. 실제 운영에는 외부 DB/API, 인증, 재시도/중복 방지, 결제 연동이 필요합니다.
