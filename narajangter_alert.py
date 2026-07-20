narajangter_alert.py
# -*- coding: utf-8 -*-
"""
나라장터 모듈입찰(임시교사) 공고 이메일 알림 스크립트
=====================================================

[하는 일]
1. 공공데이터포털의 "조달청_나라장터 입찰공고정보서비스" API에서
   최근 며칠치 공사 부문 입찰공고 목록을 가져옵니다.
2. 공고명에 지정한 키워드(예: '모듈', '임시교사')가 포함된 공고를 찾습니다.
3. 이전에 이미 알림을 보낸 공고는 제외하고, 새로 발견된 공고만 이메일로 발송합니다.
4. 발송한 공고 번호는 sent_notices.json 파일에 기록해 중복 발송을 막습니다.

[사전 준비 - 직접 하셔야 하는 것]
1. 공공데이터포털(data.go.kr) 가입 → "조달청_나라장터 입찰공고정보서비스" 활용신청
   → 승인 후 "일반 인증키(Encoding 아님, Decoding 키)" 복사
   → https://www.data.go.kr/data/15129394/openapi.do
2. 이메일 발송용 계정 준비
   - Gmail 사용 시: 구글 계정 → 보안 → 2단계 인증 활성화 → "앱 비밀번호" 생성
   - Naver 사용 시: 네이버 메일 환경설정 → POP3/SMTP 설정에서 비밀번호 사용 여부 확인
3. 아래 CONFIG 부분에 본인의 값을 채워 넣기

[실행 방법]
python 나라장터_모듈입찰_알림.py

[매일 자동 실행 - 매일 오후 2시(14:00) 1회 기준]
- Windows: 작업 스케줄러(Task Scheduler)
  1) "작업 스케줄러" 실행 → "기본 작업 만들기"
  2) 트리거: 매일, 시작 시간 14:00
  3) 동작: 프로그램 시작 → python.exe 경로 지정,
     인수에 "이 스크립트의 전체 경로" 입력
- Mac/Linux: crontab -e 에 아래 한 줄 추가
     0 14 * * * /usr/bin/python3 /경로/나라장터_모듈입찰_알림.py
- 클라우드 서버로 옮기실 경우에도 위 crontab 방식 동일하게 사용 가능
"""

import json
import os
import smtplib
import ssl
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests

# ============================================================
# CONFIG - 여기를 본인 값으로 채워주세요
# ============================================================

# 1) 공공데이터포털에서 발급받은 서비스 키 (Decoding 키 권장)
SERVICE_KEY = "b55bd0376e858e404e7876c8d3f37d25161c85528b216fc881af2adf61f83462"

# 2) 찾고 싶은 키워드 (공고명에 아래 단어 중 하나라도 포함되면 알림)
KEYWORDS = ["모듈", "임시교사"]

# 2-1) 제외할 공사명 (공고명에 아래 단어가 포함되면 배제)
EXCLUDE_KEYWORDS = ["토목공사", "기계공사", "전기공사", "통신공사"]

# 3) 이메일 발송 설정
EMAIL_FROM = "hanaguliguli@gmail.com"
EMAIL_PASSWORD = "zzqejpxvdrbmubvf"        # 절대 일반 로그인 비밀번호 아님
EMAIL_TO = "hnkim@yoo-chang.co.kr"
SMTP_SERVER = "smtp.gmail.com"             # 네이버는 smtp.naver.com
SMTP_PORT = 465

# 4) 몇 일치 공고를 조회할지
#    매일 오후 2시 1회 실행 기준, 주말/공휴일 누락 방지를 위해 3일로 설정
#    (sent_notices.json으로 중복 발송은 자동 방지되므로 넉넉하게 잡아도 안전)
DAYS_BACK = 3

# 5) 중복 발송 방지용 기록 파일 (스크립트와 같은 폴더에 생성됨)
SENT_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sent_notices.json")

# ============================================================
# API 설정 (조달청_나라장터 입찰공고정보서비스 - 공사 부문)
# ============================================================

API_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwk"


def fetch_bid_list():
    """최근 DAYS_BACK일치 공사 입찰공고 목록을 가져옵니다."""
    end_dt = datetime.now()
    begin_dt = end_dt - timedelta(days=DAYS_BACK)

    params = {
        "serviceKey": SERVICE_KEY,
        "numOfRows": "500",
        "pageNo": "1",
        "inqryDiv": "1",  # 1: 공고게시일시 기준 조회
        "inqryBgnDt": begin_dt.strftime("%Y%m%d") + "0000",
        "inqryEndDt": end_dt.strftime("%Y%m%d") + "2359",
        "type": "json",
    }

    response = requests.get(API_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    items = (
        data.get("response", {})
        .get("body", {})
        .get("items", [])
    )
    # API가 단일 건일 때 dict로, 여러 건일 때 list로 줄 수 있어 방어 처리
    if isinstance(items, dict):
        items = [items]
    return items


def filter_by_keyword(items):
    """공고명(bidNtceNm)에 키워드가 포함된 건만 골라냅니다."""
    matched = []
    for item in items:
        title = item.get("bidNtceNm", "")
        if any(keyword in title for keyword in KEYWORDS):
            matched.append(item)
    return matched


def exclude_by_keyword(items):
    """공고명에 제외 키워드가 포함된 건을 제거합니다."""
    filtered = []
    for item in items:
        title = item.get("bidNtceNm", "")
        if not any(keyword in title for keyword in EXCLUDE_KEYWORDS):
            filtered.append(item)
    return filtered


def load_sent_notices():
    if not os.path.exists(SENT_LOG_PATH):
        return set()
    with open(SENT_LOG_PATH, "r", encoding="utf-8") as f:
        return set(json.load(f))


def save_sent_notices(sent_set):
    with open(SENT_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(list(sent_set), f, ensure_ascii=False, indent=2)


def send_email(new_matches):
    """새로 발견된 공고 목록을 이메일로 발송합니다."""
    subject = f"[나라장터 알림] 모듈입찰(임시교사) 관련 신규 공고 {len(new_matches)}건"

    body_lines = []
    for idx, item in enumerate(new_matches, 1):
        body_lines.append(
            f"\n[{idx}번] 모듈입찰 공고 정보\n"
            "=" * 60 + "\n"
            f"공고명    : {item.get('bidNtceNm', '')}\n"
            f"공고번호  : {item.get('bidNtceNo', '')}\n"
            f"발주기관  : {item.get('ntceInsttNm', '')}\n"
            f"공고일자  : {item.get('bidNtceDt', '')}\n"
            f"입찰마감  : {item.get('bidClseDt', '')}\n"
        )
    body = "".join(body_lines) if body_lines else "새 공고가 없습니다."

    msg = MIMEMultipart()
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())


def main():
    print(f"[{datetime.now()}] 나라장터 공고 조회 시작")

    all_items = fetch_bid_list()
    print(f" - 전체 공사 공고 {len(all_items)}건 조회됨")

    matched = filter_by_keyword(all_items)
    print(f" - 키워드({', '.join(KEYWORDS)}) 매칭 {len(matched)}건")

    matched = exclude_by_keyword(matched)
    print(f" - 제외 키워드({', '.join(EXCLUDE_KEYWORDS)}) 제거 후 {len(matched)}건")

    sent_ids = load_sent_notices()
    new_matches = [
        item for item in matched
        if item.get("bidNtceNo") not in sent_ids
    ]
    print(f" - 신규(미발송) 공고 {len(new_matches)}건")

    if new_matches:
        send_email(new_matches)
        print(" - 이메일 발송 완료")
        sent_ids.update(item.get("bidNtceNo") for item in new_matches)
        save_sent_notices(sent_ids)
    else:
        print(" - 새 공고 없음, 이메일 발송 안 함")


if __name__ == "__main__":
    main()
