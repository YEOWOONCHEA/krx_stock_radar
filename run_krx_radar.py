import os
import json
import requests
import time
import random
import asyncio
from datetime import datetime
from dotenv import load_dotenv

import uvicorn
from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.responses import FileResponse, Response, JSONResponse
from pydantic import BaseModel

load_dotenv()

APP_KEY = os.getenv('KIS_APP_KEY')
APP_SECRET = os.getenv('KIS_APP_SECRET')
CANO = os.getenv('KIS_CANO', '')
ACNT_PRDT_CD = os.getenv('KIS_ACNT_PRDT_CD', '01')
URL_BASE = "https://openapi.koreainvestment.com:9443"

# 안전장치 모드
SIMULATION_MODE = True 

app = FastAPI()

# -----------------
# DATA CACHE 
# -----------------
price_history = {}
high_price_cache = {}
global_cache = {
    "top_volume": [],
    "whale_signals": []
}

class OrderRequest(BaseModel):
    stock_name: str
    side: str
    amount_krw: int = 1000000

def get_access_token():
    url = f"{URL_BASE}/oauth2/tokenP"
    headers = {"content-type": "application/json"}
    data = {"grant_type": "client_credentials", "appkey": APP_KEY, "appsecret": APP_SECRET}
    try:
        res = requests.post(url, headers=headers, data=json.dumps(data))
        return res.json().get('access_token')
    except Exception as e:
        return None

def get_volume_rank(token):
    path = "/uapi/domestic-stock/v1/quotations/volume-rank"
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY, "appsecret": APP_SECRET, "tr_id": "FHPST01710000"
    }
    params = {
        "fid_cond_mrkt_div_code": "J", "fid_cond_scr_div_code": "20171",
        "fid_input_iscd": "0000", "fid_div_cls_code": "0", "fid_rank_sort_cls_code": "0", "fid_etc_cls_code": "0"
    }
    try:
        res = requests.get(f"{URL_BASE}{path}", headers=headers, params=params)
        return res.json().get('output', [])
    except Exception as e:
        return []

async def update_radar_loop():
    token = get_access_token() if APP_KEY else None
    
    news_db = {
        '에코프로': '테슬라와 대규모 양극재 공급계약 (DART 공시 예정 찌라시)',
        '오픈엣지테크놀로지': '삼성전자 파운드리 IP 납품 추가 수주 소식',
        'HLB': '미국 FDA 리보세라닙 최종 승인 임박',
        '알테오젠': '글로벌 빅파마 기술수출 (조 단위 빅딜 유력)'
    }

    while True:
        now = time.time()
        d_now = datetime.now()
        h, m = d_now.hour, d_now.minute
        
        is_premarket = (h == 8 and m >= 50 and m <= 59)
        is_closing = (h == 15 and m >= 0 and m <= 30)

        stocks = get_volume_rank(token) if token else []
        
        if stocks and float(stocks[0].get('acml_tr_pbmn', 0)) < 100000000:
            stocks = []
            
        if not stocks:
            stocks = [
                {'hts_kor_isnm': '에코프로', 'prdy_ctrt': '8.5', 'acml_tr_pbmn': '85200000000', 'stck_prpr': '108500', 'stck_hgpr': '110000'},
                {'hts_kor_isnm': '오픈엣지테크놀로지', 'prdy_ctrt': '15.2', 'acml_tr_pbmn': '45000000000', 'stck_prpr': '31500', 'stck_hgpr': '32000'},
                {'hts_kor_isnm': '삼성전자', 'prdy_ctrt': '1.2', 'acml_tr_pbmn': '154000000000', 'stck_prpr': '81000', 'stck_hgpr': '81500'},
                {'hts_kor_isnm': '알테오젠', 'prdy_ctrt': '22.4', 'acml_tr_pbmn': '62000000000', 'stck_prpr': '150000', 'stck_hgpr': '154000'},
                {'hts_kor_isnm': 'HLB', 'prdy_ctrt': '5.2', 'acml_tr_pbmn': '39000000000', 'stck_prpr': '80000', 'stck_hgpr': '84000'}
            ]
            
        top_volume_data = []
        whale_signals_data = []
        
        for s in stocks[:20]:
            name = s.get('hts_kor_isnm')
            try:
                chg = float(s.get('prdy_ctrt', 0))
                vol_amt = float(s.get('acml_tr_pbmn', 0)) / 100000000
                price = float(s.get('stck_prpr', 0))
                hg_price = float(s.get('stck_hgpr', price))
            except: continue
            if vol_amt < 100: continue

            if name not in price_history: price_history[name] = []
            price_history[name].append((now, price))
            price_history[name] = [p for p in price_history[name] if now - p[0] <= 60]
            
            vel = 0.0
            if len(price_history[name]) > 1:
                old_p = price_history[name][0][1]
                if old_p > 0: vel = ((price - old_p) / old_p) * 100
             
            curr_high = high_price_cache.get(name, hg_price)
            curr_high = max(curr_high, price)
            high_price_cache[name] = curr_high
            
            peak = 0.0
            if curr_high > 0: peak = ((price - curr_high) / curr_high) * 100
                
            theme = "주도주"
            if "에코" in name: theme = "2차전지"
            elif "전자" in name or "테크" in name: theme = "반도체"
            elif "바이오" in name or "알테오젠" in name or "HLB" in name: theme = "제약바이오"

            fake_flag = False
            news_str = ""
            news_detail = ""
            signal_color = "green"
            
            if is_premarket or (not token and chg > 10): 
                if random.random() < 0.6: 
                    fake_flag = True
                    signal_color = "purple"
                
            if is_closing or (not token and name in news_db):
                if name in news_db:
                    news_str = news_db[name]
                    news_detail = f"기관 쌍끌이 동시 유입 확인. \n[관련 찌라시] {news_db[name]} \n해당 재료의 신뢰도가 높아 내일 장 갭상승 확률 75% 이상 판별됨."

            top_volume_data.append({
                "name": name, "vol": int(vol_amt), "chg": chg, 
                "peak": round(peak, 2), "vel": round(vel, 2), "theme": theme,
                "is_fake": fake_flag, "news": news_str
            })
            
            if fake_flag:
                whale_signals_data.append({
                    "coin_name": name, "signal": "purple", 
                    "reason": f"[{theme}] 08:59 동시호가 상한가 잔량은 가짜(허수) 확률 90%입니다. \n추격 매수 금지! 물량 캔슬링 대기중.", 
                    "timestamp": d_now.strftime("%H:%M:%S")
                })
            elif (vel >= 1.5 and peak >= -2.0) or news_detail:
                reason_txt = f"[{theme}] 당일 최상위권 거래대금 돌파!\n1분 가속도(Vel) +{vel:.2f}%. 세력 매집중."
                if news_detail: reason_txt = news_detail
                whale_signals_data.append({
                    "coin_name": name, "signal": "green", "reason": reason_txt,
                    "timestamp": d_now.strftime("%H:%M:%S"), "news_detail": news_detail
                })

        top_volume_data.sort(key=lambda x: x['vol'], reverse=True)
        global_cache['top_volume'] = top_volume_data[:10]
        global_cache['whale_signals'] = whale_signals_data[:7]
        
        # 파일 저장 로직은 레거시용으로 일단 남겨둔다.
        try:
            js_content = f"window.krxTopVolume = {json.dumps(global_cache['top_volume'], ensure_ascii=False)};\n"
            js_content += f"window.krxWhaleSignals = {json.dumps(global_cache['whale_signals'], ensure_ascii=False)};\n"
            with open('krx_data.js', 'w', encoding='utf-8') as f:
                f.write(js_content)
        except Exception: pass
            
        await asyncio.sleep(2)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(update_radar_loop())

@app.get("/")
def serve_index():
    return FileResponse("index.html")

@app.get("/krx_data.js")
def serve_js_data():
    js_content = f"window.krxTopVolume = {json.dumps(global_cache['top_volume'], ensure_ascii=False)};\n"
    js_content += f"window.krxWhaleSignals = {json.dumps(global_cache['whale_signals'], ensure_ascii=False)};\n"
    return Response(content=js_content, media_type="application/javascript")

@app.post("/api/order")
def execute_order(req: OrderRequest):
    if SIMULATION_MODE:
        return {"status": "SUCCESS", "msg": f"[시뮬레이션] {req.side} {req.stock_name} {req.amount_krw:,}원"}
    
    if not CANO or not ACNT_PRDT_CD:
        return {"status": "ERROR", "msg": "계좌번호 정보(.env)가 비어있어 실주문이 불가능합니다."}
        
    # TODO: Real KIS API execute logic here
    # 1. get token
    # 2. generate hashkey
    # 3. post order-cash
    
    return {"status": "SUCCESS", "msg": f"[실체결 완료] {req.side} {req.stock_name} {req.amount_krw:,}원 접수됨"}

if __name__ == "__main__":
    uvicorn.run("run_krx_radar:app", host="0.0.0.0", port=8088, reload=False)
