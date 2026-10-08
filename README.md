# 스마트 주차 관리 시스템 (Streamlit)

## 실행
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Community Cloud 배포
1. GitHub에 `app.py`, `requirements.txt`를 올립니다.
2. https://share.streamlit.io/ 에서 New app을 선택합니다.
3. GitHub 저장소와 `app.py`를 선택하고 Deploy를 누릅니다.

주의: Streamlit Community Cloud의 로컬 SQLite 파일은 앱 재시작/재배포 시 유지되지 않을 수 있습니다. 실제 운영에는 외부 영구 DB를 사용하세요. 차량번호·출입기록이 공개될 수 있으므로 실제 데이터를 사용하기 전에 인증과 접근제어를 구현하세요. 현재는 데모이며 번호판 인식, 센서 API, 결제 기능은 포함하지 않습니다.
