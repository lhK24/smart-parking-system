import streamlit as st
import requests
import streamlit.components.v1 as components
from urllib.parse import urlparse
from datetime import datetime, timezone
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title='스마트 주차장', page_icon='🚗', layout='wide')
st.title('🚗 스마트 주차장 · 실시간 현황')
st.caption('핸드폰 카메라 → Google Colab OCR → Supabase → Streamlit · 5초마다 갱신')

st.subheader('📷 실시간 번호판 카메라 (이 사이트 안에서 보기)')
cam_url = st.secrets.get('GRADIO_URL', '').strip().rstrip('/')
parsed = urlparse(cam_url)
if parsed.scheme == 'https' and parsed.netloc.endswith('.gradio.live'):
    st.link_button('카메라 전체 화면으로 열기 (핸드폰 추천)', cam_url)
    components.iframe(cam_url, height=650, scrolling=True)
    st.caption('휴대폰 브라우저에서 카메라 접근이 차단되면 위 전체 화면 링크로 열어주세요.')
else:
    st.warning('카메라 연결 대기 중: Colab에서 Gradio 카메라를 실행한 후 Streamlit Secrets에 GRADIO_URL을 저장해야 이 자리에 카메라가 표시됩니다.')
    st.caption('카메라를 켜려면 Colab이 실행 중이어야 합니다. 모바일에서 임베드가 안 되면 위 전체 화면 링크를 사용하세요.')
st_autorefresh(interval=5000, key='refresh')
try:
    URL = st.secrets['SUPABASE_URL'].rstrip('/')
    KEY = st.secrets['SUPABASE_ANON_KEY']
except Exception:
    st.error('Streamlit Cloud Secrets에 SUPABASE_URL과 SUPABASE_ANON_KEY를 등록하세요.')
    st.stop()
HEADERS={'apikey':KEY,'Authorization':f'Bearer {KEY}'}
if any(ord(c)>127 for c in KEY) or not KEY.startswith(('eyJ','sb_publishable_')):
    st.error('SUPABASE_ANON_KEY에 실제 Supabase anon/public 키를 입력하세요. 예시 한글 문구를 넣으면 안 됩니다.')
    st.stop()
def fetch(table, params):
    r=requests.get(f'{URL}/rest/v1/{table}',headers=HEADERS,params=params,timeout=12)
    r.raise_for_status()
    return r.json()
def update(table, match, data):
    r=requests.patch(f'{URL}/rest/v1/{table}',headers={**HEADERS,'Content-Type':'application/json','Prefer':'return=representation'},params=match,json=data,timeout=12)
    r.raise_for_status()
    return r.json()
try:
    spaces=fetch('parking_spaces',{'select':'name,plate','order':'name.asc'})
    active=fetch('parking_visits',{'select':'id,plate,entered_at,space','exited_at':'is.null','order':'entered_at.asc'})
except Exception as e:
    st.error(f'DB 연결 실패: {e}')
    st.stop()
occupied=sum(bool(s['plate']) for s in spaces)
a,b,c,d=st.columns(4)
a.metric('전체 주차면',len(spaces)); b.metric('빈자리',len(spaces)-occupied)
c.metric('사용 중',occupied); d.metric('입차 차량',len(active))
st.subheader('주차 공간 현황')
for i in range(0,len(spaces),3):
    cols=st.columns(3)
    for col,s in zip(cols,spaces[i:i+3]):
        with col:
            if s['plate']: st.error(f"🚘 {s['name']} · {s['plate']}")
            else: st.success(f"🅿️ {s['name']} · 빈자리")
t1,t2,t3=st.tabs(['내 차 찾기','주차면 배정(센서 시뮬레이션)','입출차 기록'])
with t1:
    q=st.text_input('차량번호 입력')
    if st.button('조회'):
        match=[v for v in active if v['plate']==q.strip().replace(' ','')]
        if match: st.success(f"주차 위치: {match[0]['space'] or '미배정'} / 입차: {match[0]['entered_at']}")
        else: st.warning('입차 중인 차량이 없습니다.')
with t2:
    waiting=[v for v in active if not v['space']]
    free=[s['name'] for s in spaces if not s['plate']]
    if waiting and free:
        with st.form('assign'):
            v=st.selectbox('차량',waiting,format_func=lambda x:x['plate'])
            space=st.selectbox('주차면',free)
            submit=st.form_submit_button('배정')
        if submit:
            try:
                # Demo only: two REST writes are not atomic; avoid simultaneous assignments.
                update('parking_spaces',{'name':f'eq.{space}','plate':'is.null'},{'plate':v['plate']})
                update('parking_visits',{'id':f"eq.{v['id']}",'space':'is.null'},{'space':space})
                st.success('배정 완료'); st.rerun()
            except Exception as e: st.error(str(e))
    else: st.info('대기 차량 또는 빈 주차면이 없습니다.')
with t3:
    try:
        visits=fetch('parking_visits',{'select':'plate,entered_at,exited_at,space,fee','order':'id.desc','limit':'100'})
        st.dataframe(visits,use_container_width=True,hide_index=True)
    except Exception as e: st.error(str(e))
st.caption('데모 전용: 실제 차량번호·개인정보를 입력하지 마세요. 실제 결제는 수행하지 않습니다.')

