// ----------------- 탭 전환 -----------------
const tabs = document.querySelectorAll(".tab");
const panels = document.querySelectorAll(".panel");

function showTab(name) {
  tabs.forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  panels.forEach((p) => p.classList.toggle("active", p.id === `panel-${name}`));
  if (name === "status") loadStatus();
  if (name === "recommend") loadRecommend();
}

tabs.forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
document.querySelectorAll("[data-go]").forEach((el) => {
  el.addEventListener("click", (e) => {
    e.preventDefault();
    showTab(el.dataset.go);
  });
});

// ----------------- 초기 메타 로드 -----------------
async function loadMeta() {
  const res = await fetch("/api/meta");
  const data = await res.json();
  document.getElementById("total-courses").textContent = data.total_courses;
  const sel = document.getElementById("sido-select");
  sel.innerHTML = data.sido_list
    .map((s) => `<option value="${s}">${s}</option>`)
    .join("");
}
loadMeta();

// ----------------- 수준 진단 -----------------
const diagForm = document.getElementById("diagnose-form");
diagForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(diagForm).entries());
  const res = await fetch("/api/diagnose", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  const result = await res.json();
  document.getElementById("result-level").textContent = result.level;
  document.getElementById("result-guide").textContent = result.guide;
  document.getElementById("diagnose-result").classList.remove("hidden");
  document.getElementById("diagnose-result").scrollIntoView({ behavior: "smooth" });
});

// ----------------- 강좌 추천 -----------------
async function loadRecommend() {
  const empty = document.getElementById("recommend-empty");
  const list = document.getElementById("recommend-list");
  list.innerHTML = "";

  const res = await fetch("/api/recommend");
  if (!res.ok) {
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");
  const data = await res.json();
  data.results.forEach((c) => {
    const reasons = c.추천이유.length
      ? `<div class="reasons"><b>추천 이유:</b><ul>${c.추천이유.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul></div>`
      : "";
    const card = document.createElement("div");
    card.className = "course-card";
    card.innerHTML = `
      <div>
        <h3 class="title">${escapeHtml(c.강좌명)}</h3>
        <p class="meta">
          <span><b>운영기관:</b> ${escapeHtml(c.운영기관명)}</span>
          <span><b>방법:</b> ${escapeHtml(c.교육방법구분)}</span>
          <span><b>대상:</b> ${escapeHtml(c.교육대상구분)}</span>
        </p>
        <p class="meta"><b>주소:</b> ${escapeHtml(c.교육장도로명주소)}</p>
        <div class="tags">
          <span class="tag level-${escapeHtml(c.강좌난이도)}">${escapeHtml(c.강좌난이도)}</span>
          <span class="tag">${escapeHtml(c.교육방법구분)}</span>
        </div>
        ${reasons}
      </div>
      <div class="score-box">
        <div class="num">${c.추천점수}</div>
        <div class="lbl">추천점수</div>
      </div>
    `;
    list.appendChild(card);
  });
}

// ----------------- AI 튜터 -----------------
let currentMissionTitle = "";

document.getElementById("tutor-load").addEventListener("click", () => loadTutor());
document.getElementById("btn-next").addEventListener("click", () => loadTutor());

async function loadTutor() {
  const btn = document.getElementById("tutor-load");
  btn.disabled = true;
  btn.textContent = "AI 튜터 응답 생성 중...";
  document.getElementById("mission-feedback").classList.add("hidden");

  const res = await fetch("/api/tutor", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  const data = await res.json();

  document.getElementById("tutor-explanation").textContent = data.easy_explanation || "";
  const stepsEl = document.getElementById("tutor-steps");
  stepsEl.innerHTML = (data.steps || []).map((s) => `<li>${escapeHtml(s)}</li>`).join("");
  document.getElementById("tutor-example").textContent = `"${data.example_question || ""}"`;
  document.getElementById("mission-title").textContent = data.mission?.title || "-";
  document.getElementById("mission-content").textContent = data.mission?.content || "";
  document.getElementById("mission-success").textContent = data.mission?.success || "";
  currentMissionTitle = data.mission?.title || "(제목없음)";

  document.getElementById("tutor-content").classList.remove("hidden");

  const srcEl = document.getElementById("tutor-source");
  if (data._source === "ollama") {
    srcEl.textContent = "✨ Ollama LLM 생성";
    srcEl.style.color = "#10b981";
  } else {
    srcEl.textContent = "📋 기본 템플릿 (Ollama 미연결)";
    srcEl.style.color = "#f59e0b";
  }

  btn.disabled = false;
  btn.textContent = "오늘의 학습 받기";
}

document.getElementById("btn-complete").addEventListener("click", async () => {
  await postMission("complete", currentMissionTitle);
  showFeedback(`미션을 완료했습니다! "${currentMissionTitle}"`);
});

document.getElementById("btn-hard").addEventListener("click", async () => {
  await postMission("hard", currentMissionTitle);
  showFeedback("난이도가 너무 높았네요. 다음 미션은 더 쉽게 받아보세요. 🌱");
});

async function postMission(action, title) {
  await fetch("/api/mission", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, title }),
  });
}

function showFeedback(msg) {
  const el = document.getElementById("mission-feedback");
  el.textContent = msg;
  el.classList.remove("hidden");
}

// ----------------- 학습 상태 -----------------
async function loadStatus() {
  const res = await fetch("/api/status");
  const data = await res.json();

  document.getElementById("status-level").textContent = data.user?.level || "-";
  document.getElementById("status-done-count").textContent = `${data.mission_done.length}개`;
  document.getElementById("status-hard-count").textContent = `${data.mission_hard.length}개`;

  document.getElementById("status-recommended").innerHTML = data.recommended.length
    ? data.recommended.map((r) => `<li>${escapeHtml(r.강좌명)} <span class="muted">(${escapeHtml(r.강좌난이도)}, 점수 ${r.추천점수})</span></li>`).join("")
    : "<li class='muted'>아직 추천받은 강좌가 없습니다.</li>";

  document.getElementById("status-done").innerHTML = data.mission_done.length
    ? data.mission_done.map((m) => `<li>✅ ${escapeHtml(m)}</li>`).join("")
    : "<li class='muted'>아직 완료한 미션이 없습니다.</li>";

  document.getElementById("status-hard").innerHTML = data.mission_hard.length
    ? data.mission_hard.map((m) => `<li>🟧 ${escapeHtml(m)}</li>`).join("")
    : "<li class='muted'>어려워한 미션이 없습니다.</li>";

  document.getElementById("status-next").textContent = data.next_guide || "수준 진단을 먼저 완료해주세요.";
}

// ----------------- 초기화 -----------------
document.getElementById("reset-btn").addEventListener("click", async () => {
  if (!confirm("모든 진단 결과와 미션 기록을 초기화할까요?")) return;
  await fetch("/api/reset", { method: "POST" });
  location.reload();
});

// ----------------- 유틸 -----------------
function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
