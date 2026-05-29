"""
AI 학습 플랫폼 - Flask 백엔드
- 공공데이터(AI관련 평생학습강좌)를 활용
- 사용자 수준 진단 → 맞춤 강좌 추천 → AI 튜터(Ollama) → 학습 기록
"""
import csv
import json
import os
import random
import re
from pathlib import Path

import requests
from flask import Flask, jsonify, render_template, request, session

BASE_DIR = Path(__file__).parent
CSV_PATH = BASE_DIR / "courses.csv"

# Ollama 설정 (기본: 로컬 11434, 모델은 환경변수로 변경 가능)
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:latest")

app = Flask(__name__)
app.secret_key = "ai-learning-platform-secret-key-change-me"


# ---------------- 데이터 로드 ----------------
def load_courses():
    courses = []
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            row = {k.strip(): (v or "").strip() for k, v in row.items()}
            row["id"] = i
            courses.append(row)
    return courses


COURSES = load_courses()


def get_sido(address: str) -> str:
    if not address:
        return ""
    return address.split()[0] if address.split() else ""


def get_sigungu(address: str) -> str:
    parts = address.split()
    return parts[1] if len(parts) >= 2 else ""


SIDO_LIST = sorted({get_sido(c["교육장도로명주소"]) for c in COURSES if c["교육장도로명주소"]})


# ---------------- 수준 진단 ----------------
def diagnose_level(payload: dict) -> dict:
    """
    PDF 기준:
    - AI 사용경험: 없음 / 조금있음 / 자주사용
    - 관심분야: 생활정보 / 문서작성 / 콘텐츠제작 / 업무활용 / 데이터·코딩
    - 연령대, 거주지역, 선호학습방식
    """
    score = 0
    experience = payload.get("experience", "없음")
    if experience == "없음":
        score += 0
    elif experience == "조금있음":
        score += 2
    elif experience == "자주사용":
        score += 4

    interest = payload.get("interest", "")
    if interest in ("생활정보",):
        score += 0
    elif interest in ("문서작성", "콘텐츠제작"):
        score += 1
    elif interest in ("업무활용",):
        score += 2
    elif interest in ("데이터·코딩", "데이터/코딩", "데이터코딩"):
        score += 3

    age = payload.get("age", "")
    if age in ("60대이상",):
        score -= 1
    elif age in ("10대",):
        score += 0

    if score <= 1:
        level = "초급"
        guide = (
            "생성형 AI를 처음 배우는 단계이므로 "
            "생활 속 활용이나 기초 강좌부터 시작하는 것이 적합합니다."
        )
    elif score <= 4:
        level = "중급"
        guide = (
            "AI 도구를 어느 정도 다뤄본 단계입니다. "
            "관심분야에 맞춰 콘텐츠 제작, 업무 활용 강좌를 추천합니다."
        )
    else:
        level = "고급"
        guide = (
            "AI를 능숙하게 활용할 수 있는 단계입니다. "
            "프롬프트 엔지니어링, 데이터·코딩 분야 심화 강좌를 추천합니다."
        )

    return {"level": level, "guide": guide, "score": score}


# ---------------- 추천 점수 ----------------
LEVEL_ORDER = {"초급": 0, "중급": 1, "고급": 2}


def age_target_fit(age: str, target: str) -> int:
    """연령/교육대상 적합도 (0~40)"""
    if not target:
        return 20
    t = target.replace(" ", "")
    age = age or ""

    # 어르신/시니어 매칭
    senior_keywords = ["어르신", "시니어", "50세", "60대", "노후"]
    youth_keywords = ["초등", "청소년", "학생", "초 ", "초4", "초3", "학부모"]

    if age in ("60대이상",) and any(k in target for k in senior_keywords):
        return 40
    if age in ("10대",) and any(k in target for k in youth_keywords):
        return 40
    if age in ("20~30대", "40~50대"):
        if "성인" in t or "시민" in t or "지역주민" in t or "제한없음" in t:
            return 40
        if any(k in target for k in senior_keywords + youth_keywords):
            return 10
        return 25
    # 기본
    if "성인" in t or "시민" in t or "지역주민" in t or "제한없음" in t:
        return 30
    return 15


def score_course(user: dict, course: dict) -> tuple[int, list[str]]:
    score = 0
    reasons = []

    # 1) 수준/난이도 일치 (40)
    user_level = user.get("level", "초급")
    course_level = course.get("강좌난이도", "")
    if user_level == course_level:
        score += 40
        reasons.append(f"사용자 수준({user_level})과 강좌 난이도({course_level})가 일치")
    else:
        diff = abs(LEVEL_ORDER.get(user_level, 0) - LEVEL_ORDER.get(course_level, 0))
        if diff == 1:
            score += 15

    # 2) 연령/교육대상 적합 (40)
    age_score = age_target_fit(user.get("age", ""), course.get("교육대상구분", ""))
    score += age_score
    if age_score >= 30:
        reasons.append(f"교육대상({course.get('교육대상구분','')})이 사용자에게 적합")

    # 3) 같은 시도 (20)
    user_sido = user.get("sido", "")
    course_sido = get_sido(course["교육장도로명주소"])
    if user_sido and user_sido == course_sido:
        score += 20
        reasons.append(f"거주 시도({course_sido})와 일치")

    # 4) 같은 시군구 (20)
    user_sigungu = user.get("sigungu", "")
    course_sigungu = get_sigungu(course["교육장도로명주소"])
    if user_sigungu and user_sigungu == course_sigungu:
        score += 20
        reasons.append(f"거주 시군구({course_sigungu})와 일치")

    # 5) 선호 학습방식 일치 (10)
    pref = user.get("method", "상관없음")
    method = course.get("교육방법구분", "")
    if pref != "상관없음" and pref == method:
        score += 10
        reasons.append(f"선호 학습방식({method})과 일치")

    return score, reasons


def recommend(user: dict, top_n: int = 10) -> list[dict]:
    scored = []
    for c in COURSES:
        s, reasons = score_course(user, c)
        scored.append({**c, "추천점수": s, "추천이유": reasons})
    scored.sort(key=lambda x: x["추천점수"], reverse=True)
    return scored[:top_n]


# ---------------- AI 튜터 (Ollama) ----------------
def call_ollama(prompt: str, options: dict | None = None) -> str:
    try:
        body = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}
        if options:
            # 답변 다양성을 위한 옵션(temperature/seed 등)
            body["options"] = options
        resp = requests.post(OLLAMA_URL, json=body, timeout=60)
        if resp.ok:
            return resp.json().get("response", "").strip()
        return f"[Ollama 오류 {resp.status_code}] {resp.text[:200]}"
    except Exception as e:
        return f"[Ollama 연결 실패] {e}\n→ Ollama가 실행 중인지 확인하세요: `ollama serve`"


# 관심 분야별 구체적인 미션 주제 풀 (매번 랜덤으로 하나 골라 다양성 확보)
INTEREST_TOPICS = {
    "생활정보": [
        "요리 레시피 추천받기", "여행 일정 짜기", "건강한 식단 만들기",
        "장보기 목록 정리", "집 정리·청소 팁", "한 달 예산 계획",
        "운동 루틴 추천", "취미 추천받기", "선물 아이디어 얻기",
    ],
    "문서작성": [
        "정중한 이메일 쓰기", "자기소개서 초안 만들기", "회의록 요약하기",
        "보고서 개요 잡기", "공지문 작성", "감사 인사말 쓰기",
        "사과 메시지 다듬기", "이력서 문장 고치기",
    ],
    "콘텐츠제작": [
        "유튜브 영상 제목 짓기", "인스타그램 캡션 쓰기", "블로그 글 아이디어 얻기",
        "썸네일 문구 만들기", "짧은 이야기 쓰기", "홍보 포스터 문구",
        "행사 초대글 작성", "제품 소개 문구 만들기",
    ],
    "업무활용": [
        "엑셀 함수 물어보기", "회의 안건 정리", "업무 우선순위 정하기",
        "고객 응대 메시지 작성", "프레젠테이션 구성 잡기", "일정 관리 팁 얻기",
        "업무 메일 답장 쓰기", "아이디어 브레인스토밍",
    ],
    "데이터·코딩": [
        "파이썬 기초 개념 질문", "데이터 표 정리 요청", "간단한 그래프 설명 듣기",
        "코드 오류 원인 물어보기", "엑셀 데이터 분석 방법", "알고리즘 쉽게 이해하기",
        "정규표현식 만들기", "SQL 기초 질문",
    ],
}


def pick_topic(interest: str, avoid: list[str] | None = None) -> str:
    """관심 분야에 맞는 주제를 랜덤으로 하나 고른다(최근 사용한 건 가능하면 회피)."""
    pool = INTEREST_TOPICS.get(interest) or INTEREST_TOPICS["생활정보"]
    avoid = avoid or []
    candidates = [t for t in pool if t not in avoid] or pool
    return random.choice(candidates)


def build_tutor_prompt(
    level: str, interest: str, topic: str,
    avoid_titles: list[str] | None = None, course_title: str = "",
) -> str:
    course_part = (
        f"\n사용자가 선택한 강좌: {course_title}" if course_title else ""
    )
    avoid_part = ""
    if avoid_titles:
        avoid_part = (
            "\n\n[중요] 아래 미션들과는 주제가 절대 겹치지 않게, "
            "완전히 다른 내용으로 만들어주세요:\n- " + "\n- ".join(avoid_titles)
        )
    return f"""당신은 AI를 처음 배우는 한국 사용자를 도와주는 친절한 'AI 튜터'입니다.
사용자 수준: {level}
관심 분야: {interest}
이번 미션 주제: "{topic}" — 반드시 이 주제를 활용해 구체적인 실습 미션을 만들어주세요.{course_part}{avoid_part}

[작성 규칙]
- 예시 질문과 미션은 위의 "이번 미션 주제"에 맞춰 구체적으로 작성하세요.
- '날씨', '오늘 날씨', '날씨에 맞는 옷차림' 같은 뻔한 예시는 절대 사용하지 마세요.
- 매번 다른 분야·상황의 예시를 들어 신선하게 만들어주세요.

아래 JSON 형식으로만 응답하세요. 코드블록 없이 순수 JSON만 출력하세요.

{{
  "easy_explanation": "수준에 맞춘 쉬운 개념 설명 (3~4문장)",
  "steps": ["따라하기 1단계", "따라하기 2단계", "따라하기 3단계"],
  "example_question": "사용자가 ChatGPT 같은 AI에게 입력해볼 만한 예시 문장",
  "mission": {{
    "title": "오늘의 미션 제목",
    "content": "구체적인 실습 미션 내용",
    "success": "성공 기준"
  }}
}}

반드시 한국어로, 사용자 수준({level})에 맞춰 작성하세요."""


def fallback_tutor(level: str, interest: str, avoid_titles: list[str] | None = None) -> dict:
    """Ollama 미연결 시 사용하는 기본 미션. 수준별로 여러 개를 두고 랜덤 선택해 다양성 확보."""
    avoid_titles = avoid_titles or []
    templates = {
        "초급": [
            {
                "easy_explanation": "AI(생성형 AI)는 우리가 글로 부탁하면 답을 만들어주는 도구입니다. ChatGPT는 글로 대화하는 AI예요. 어렵게 생각하지 말고 친구에게 부탁하듯 말해보세요.",
                "steps": ["AI 서비스에 접속한다", "원하는 요리 한 가지를 정한다", "'○○ 만드는 법 알려줘'라고 입력한다"],
                "example_question": "김치볶음밥 쉽게 만드는 법 알려줘",
                "mission": {"title": "AI에게 요리법 물어보기", "content": "AI에게 먹고 싶은 음식의 레시피를 물어본다.", "success": "AI가 재료와 순서를 알려주면 완료"},
            },
            {
                "easy_explanation": "AI는 정보를 정리해주는 데도 유용합니다. 궁금한 걸 한 문장으로 물어보면 알기 쉽게 답해줍니다.",
                "steps": ["가고 싶은 여행지를 떠올린다", "AI에게 '○○ 2박3일 일정 짜줘'라고 입력한다", "마음에 드는 부분을 골라본다"],
                "example_question": "부산 2박3일 여행 일정 짜줘",
                "mission": {"title": "AI와 여행 계획 세우기", "content": "AI에게 가고 싶은 곳의 여행 일정을 만들어 달라고 해본다.", "success": "AI가 날짜별 일정을 제안하면 완료"},
            },
            {
                "easy_explanation": "AI에게는 일상적인 고민도 물어볼 수 있어요. 추천을 받고 싶을 때 조건을 함께 알려주면 더 좋습니다.",
                "steps": ["요즘 관심 있는 분야를 정한다", "AI에게 '초보자가 시작하기 좋은 취미 추천해줘'라고 입력한다", "추천 중 하나를 골라본다"],
                "example_question": "집에서 혼자 할 수 있는 취미 추천해줘",
                "mission": {"title": "AI에게 취미 추천받기", "content": "AI에게 나에게 맞는 취미를 추천해 달라고 해본다.", "success": "AI가 취미 몇 가지를 추천해주면 완료"},
            },
        ],
        "중급": [
            {
                "easy_explanation": "AI에게 단순 질문 대신 '말투'와 '형식'을 함께 주면 결과가 훨씬 좋아집니다. 예: '친근한 말투로 3개 만들어줘'.",
                "steps": ["만들 결과물을 정한다(예: 홍보 문구)", "말투·개수·길이 조건을 함께 적는다", "마음에 드는 결과를 골라 다듬는다"],
                "example_question": "동아리 홍보 문구를 친근한 말투로 3개 만들어줘",
                "mission": {"title": "조건을 넣어 홍보 문구 만들기", "content": "AI에게 말투와 개수를 정해 홍보 문구를 요청하고 하나를 골라 수정한다.", "success": "마음에 드는 문장을 골라 수정하면 완료"},
            },
            {
                "easy_explanation": "AI는 긴 글을 짧게 요약하는 데 강합니다. 원하는 길이를 함께 알려주면 더 깔끔하게 정리해줍니다.",
                "steps": ["요약할 글이나 회의 내용을 준비한다", "AI에게 '3줄로 요약해줘'라고 요청한다", "핵심이 빠지지 않았는지 확인한다"],
                "example_question": "이 회의 내용을 핵심만 3줄로 요약해줘",
                "mission": {"title": "AI로 내용 요약하기", "content": "긴 글이나 메모를 AI에게 3줄로 요약해 달라고 해본다.", "success": "핵심이 담긴 요약이 나오면 완료"},
            },
            {
                "easy_explanation": "AI에게 역할을 부여하면 답의 톤이 달라집니다. '너는 마케터야'처럼 역할을 주고 물어보세요.",
                "steps": ["AI에게 역할을 부여한다(예: 너는 카피라이터야)", "원하는 결과를 구체적으로 요청한다", "결과를 비교해본다"],
                "example_question": "너는 카피라이터야. 카페 신메뉴 광고 문구 3개 만들어줘",
                "mission": {"title": "AI에게 역할 부여하기", "content": "AI에게 특정 역할을 준 뒤 그 역할에 맞는 결과물을 요청한다.", "success": "역할에 맞는 답이 나오면 완료"},
            },
        ],
        "고급": [
            {
                "easy_explanation": "프롬프트에 '대상·말투·형식' 세 조건을 명확히 넣으면 품질이 크게 오릅니다. 한 번에 안 되면 조건을 바꿔 반복하세요.",
                "steps": ["대상·말투·형식을 명시한다", "결과의 부족한 점을 다시 프롬프트에 반영한다", "실제 맥락에 맞게 다듬는다"],
                "example_question": "대상은 신입사원, 말투는 친근하게, 형식은 표로 업무 매뉴얼을 만들어줘",
                "mission": {"title": "조건을 넣어 결과 개선하기", "content": "대상·말투·형식 조건을 넣어 결과를 받고 한 번 더 개선한다.", "success": "조건이 반영되고 1회 이상 개선되면 완료"},
            },
            {
                "easy_explanation": "AI에게 표나 코드 같은 구조화된 출력도 요청할 수 있습니다. 형식을 정확히 지정하는 게 핵심입니다.",
                "steps": ["원하는 출력 형식을 정한다(표/리스트/코드)", "필요한 항목(열 제목 등)을 명시한다", "결과를 복사해 바로 활용한다"],
                "example_question": "월별 지출을 항목·금액·비고 3개 열의 표로 정리해줘",
                "mission": {"title": "AI로 데이터를 표로 정리하기", "content": "흩어진 정보를 AI에게 표 형식으로 정리해 달라고 요청한다.", "success": "원하는 열 구성의 표가 나오면 완료"},
            },
            {
                "easy_explanation": "여러 안을 비교하게 하면 더 나은 결정을 내릴 수 있습니다. '장단점을 비교해줘'라고 요청해보세요.",
                "steps": ["비교하고 싶은 선택지를 정한다", "AI에게 장단점을 표로 비교해 달라고 한다", "결과를 근거로 결정한다"],
                "example_question": "노션과 엑셀로 일정 관리하는 방법의 장단점을 비교해줘",
                "mission": {"title": "AI로 선택지 비교하기", "content": "두 가지 이상의 선택지를 AI에게 비교 분석해 달라고 요청한다.", "success": "장단점이 정리된 비교가 나오면 완료"},
            },
        ],
    }
    pool = templates.get(level, templates["초급"])
    candidates = [t for t in pool if t["mission"]["title"] not in avoid_titles] or pool
    return dict(random.choice(candidates))


# ---------------- 라우트 ----------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/meta")
def api_meta():
    return jsonify({"sido_list": SIDO_LIST, "total_courses": len(COURSES)})


@app.route("/api/diagnose", methods=["POST"])
def api_diagnose():
    payload = request.get_json(force=True)
    result = diagnose_level(payload)
    user = {**payload, **result}
    session["user"] = user
    session["mission_done"] = session.get("mission_done", [])
    session["mission_hard"] = session.get("mission_hard", [])
    session["recommended"] = []
    session["recent_missions"] = []
    return jsonify(user)


@app.route("/api/recommend")
def api_recommend():
    user = session.get("user")
    if not user:
        return jsonify({"error": "먼저 수준 진단을 완료해주세요."}), 400
    top = recommend(user, top_n=10)
    session["recommended"] = [
        {"강좌명": c["강좌명"], "강좌난이도": c["강좌난이도"], "추천점수": c["추천점수"]}
        for c in top
    ]
    return jsonify({"user": user, "results": top})


@app.route("/api/tutor", methods=["POST"])
def api_tutor():
    payload = request.get_json(force=True)
    user = session.get("user", {})
    level = payload.get("level") or user.get("level", "초급")
    interest = payload.get("interest") or user.get("interest", "생활정보")
    course_title = payload.get("course_title", "")

    # 최근에 받은 미션 제목들(중복 방지용) + 이번 주제 랜덤 선택
    recent = session.get("recent_missions", [])
    topic = pick_topic(interest, avoid=recent)

    prompt = build_tutor_prompt(level, interest, topic, avoid_titles=recent, course_title=course_title)
    # 매번 다른 결과가 나오도록 다양성 옵션 부여(높은 temperature + 랜덤 seed)
    options = {"temperature": 0.9, "top_p": 0.95, "seed": random.randint(1, 1_000_000)}
    raw = call_ollama(prompt, options=options)

    parsed = None
    # JSON 추출 시도
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            parsed = None

    if not parsed or "easy_explanation" not in parsed:
        # Ollama 실패 시 fallback 사용 + 원본 메시지 같이 전달
        parsed = fallback_tutor(level, interest, avoid_titles=recent)
        parsed["_source"] = "fallback"
        parsed["_raw"] = raw
    else:
        parsed["_source"] = "ollama"

    parsed["_topic"] = topic

    # 이번 미션 제목을 최근 목록에 기록(최대 5개 유지)
    title = (parsed.get("mission") or {}).get("title")
    if title:
        recent = [title] + [t for t in recent if t != title]
        session["recent_missions"] = recent[:5]

    return jsonify(parsed)


@app.route("/api/mission", methods=["POST"])
def api_mission():
    payload = request.get_json(force=True)
    action = payload.get("action")
    title = payload.get("title", "(제목없음)")
    if action == "complete":
        done = session.get("mission_done", [])
        done.append(title)
        session["mission_done"] = done
    elif action == "hard":
        hard = session.get("mission_hard", [])
        hard.append(title)
        session["mission_hard"] = hard
    return jsonify(
        {
            "mission_done": session.get("mission_done", []),
            "mission_hard": session.get("mission_hard", []),
        }
    )


@app.route("/api/status")
def api_status():
    user = session.get("user", {})
    next_guide = ""
    if user:
        lvl = user.get("level", "")
        if lvl == "초급":
            next_guide = "생활형 AI 질문 연습 후, 문서 작성 AI 활용으로 이동하면 좋아요."
        elif lvl == "중급":
            next_guide = "콘텐츠 제작·업무 활용 강좌로 폭을 넓혀보세요."
        else:
            next_guide = "프롬프트 엔지니어링 심화 또는 데이터·코딩 강좌를 추천합니다."

    return jsonify(
        {
            "user": user,
            "recommended": session.get("recommended", []),
            "mission_done": session.get("mission_done", []),
            "mission_hard": session.get("mission_hard", []),
            "next_guide": next_guide,
        }
    )


@app.route("/api/reset", methods=["POST"])
def api_reset():
    session.clear()
    return jsonify({"ok": True})


if __name__ == "__main__":
    print(f"[INFO] 강좌 데이터 {len(COURSES)}건 로드 완료")
    print(f"[INFO] Ollama: {OLLAMA_URL} (모델: {OLLAMA_MODEL})")
    port = int(os.environ.get("PORT", 5001))
    print(f"[INFO] http://localhost:{port} 에서 접속하세요.")
    app.run(host="0.0.0.0", port=port, debug=True)
