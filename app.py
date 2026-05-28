"""
AI 학습 플랫폼 - Flask 백엔드
- 공공데이터(AI관련 평생학습강좌)를 활용
- 사용자 수준 진단 → 맞춤 강좌 추천 → AI 튜터(Ollama) → 학습 기록
"""
import csv
import json
import os
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
def call_ollama(prompt: str) -> str:
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=60,
        )
        if resp.ok:
            return resp.json().get("response", "").strip()
        return f"[Ollama 오류 {resp.status_code}] {resp.text[:200]}"
    except Exception as e:
        return f"[Ollama 연결 실패] {e}\n→ Ollama가 실행 중인지 확인하세요: `ollama serve`"


def build_tutor_prompt(level: str, interest: str, course_title: str = "") -> str:
    course_part = (
        f"\n사용자가 선택한 강좌: {course_title}" if course_title else ""
    )
    return f"""당신은 AI를 처음 배우는 한국 사용자를 도와주는 친절한 'AI 튜터'입니다.
사용자 수준: {level}
관심 분야: {interest}{course_part}

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


def fallback_tutor(level: str, interest: str) -> dict:
    templates = {
        "초급": {
            "easy_explanation": "AI(생성형 AI)는 우리가 글이나 그림으로 부탁하면 답을 만들어주는 도구입니다. ChatGPT는 그 중에서 글로 대화하는 AI예요. 어렵게 생각하지 말고, 친구에게 부탁하듯이 말해보세요.",
            "steps": [
                "ChatGPT 또는 비슷한 AI 서비스에 접속한다",
                "검색창에 궁금한 것을 한 문장으로 적어본다",
                "AI의 답이 어려우면 '쉽게 설명해줘'라고 다시 요청한다",
            ],
            "example_question": "내일 날씨에 맞는 옷차림 알려줘",
            "mission": {
                "title": "AI에게 생활 정보 물어보기",
                "content": "AI에게 '내일 날씨에 맞는 옷차림 알려줘'라고 입력해본다.",
                "success": "AI가 날씨에 맞는 옷차림을 추천해주면 완료",
            },
        },
        "중급": {
            "easy_explanation": "AI에게 단순한 질문 대신 '말투'와 '형식'을 함께 알려주면 결과가 훨씬 좋아집니다. 예를 들어 '친근한 말투로 3개 만들어줘'처럼 조건을 붙여 요청하세요.",
            "steps": [
                "AI에게 만들고 싶은 결과물을 정한다 (예: 홍보 문구)",
                "말투와 개수, 길이 같은 조건을 함께 적는다",
                "마음에 드는 결과를 골라 직접 다듬어 본다",
            ],
            "example_question": "동아리 홍보 문구를 친근한 말투로 3개 만들어줘",
            "mission": {
                "title": "AI에게 글쓰기 도움 받기",
                "content": "AI에게 동아리 홍보 문구를 친근한 말투로 3개 요청하고, 그 중 하나를 골라 직접 수정해본다.",
                "success": "마음에 드는 문장을 골라 수정하면 완료",
            },
        },
        "고급": {
            "easy_explanation": "프롬프트에 '대상, 말투, 형식' 세 가지 조건을 명확히 넣으면 결과 품질이 크게 올라갑니다. 한 번에 좋은 답이 안 나오면 조건을 바꿔가며 반복(이터레이션)하세요.",
            "steps": [
                "프롬프트에 대상(누구를 위한지), 말투, 형식(표/리스트 등)을 명시한다",
                "AI 결과를 보고 부족한 점을 다시 프롬프트에 반영한다",
                "최종 결과물을 실제 사용 맥락에 맞게 다듬는다",
            ],
            "example_question": "대상은 60대 초보자, 말투는 쉬운 설명, 형식은 표로 해서 AI 사용법 교육안을 만들어줘",
            "mission": {
                "title": "조건을 넣어 결과 개선하기",
                "content": "대상·말투·형식 조건을 넣어 AI에게 교육안을 요청하고, 결과를 평가해 한 번 더 개선한다.",
                "success": "조건이 반영된 결과가 나오고 1회 이상 개선되면 완료",
            },
        },
    }
    return templates.get(level, templates["초급"])


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

    prompt = build_tutor_prompt(level, interest, course_title)
    raw = call_ollama(prompt)

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
        parsed = fallback_tutor(level, interest)
        parsed["_source"] = "fallback"
        parsed["_raw"] = raw
    else:
        parsed["_source"] = "ollama"

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
