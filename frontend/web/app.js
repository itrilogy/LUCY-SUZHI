// 溯知 · SuZhi 控制台：SSE、研讨对话、配置中心、任务恢复

let currentEventSource = null;
let currentTaskId = null;
let allCitations = {};
let systemConfig = null;
let taskListCache = [];
let resumeTaskId = null;
let lastExpertName = "";
let personaMeta = {};
let seminarWatermark = "";
let muteSpeak = false;
const ROLE_COLORS = ["#00D2FF", "#7CDBA5", "#82A0C4", "#4FC3C7", "#E8A33D", "#9ad8c4"];

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initActionButtons();
  initSettingsModal();
  initTasksModal();
  initAboutModal();
  initKnowledgeModal();
  resetDialogue();
  initAutoRestore();
});

function apiHeaders(jsonBody) {
  const headers = {};
  if (jsonBody) headers["Content-Type"] = "application/json";
  const tok = localStorage.getItem("suzhi_api_token") || "";
  if (tok) headers["X-SuZhi-Token"] = tok;
  return headers;
}

function withTokenQuery(url) {
  const tok = localStorage.getItem("suzhi_api_token") || "";
  if (!tok) return url;
  return url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(tok);
}

async function apiFetch(url, opts = {}) {
  const headers = { ...apiHeaders(Boolean(opts.body)), ...(opts.headers || {}) };
  return fetch(url, { ...opts, headers });
}

async function readError(res, fallback) {
  try {
    const data = await res.json();
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) return data.detail.map((d) => d.msg || d).join("; ");
  } catch (_e) {}
  return fallback || res.statusText || "请求失败";
}

function escapeHtml(text) {
  if (!text) return "";
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function sanitizeHtml(html) {
  const tpl = document.createElement("template");
  tpl.innerHTML = html;
  const forbidden = new Set(["SCRIPT", "IFRAME", "OBJECT", "EMBED", "LINK", "META", "BASE", "FORM", "SVG"]);
  const walk = (node) => {
    [...node.childNodes].forEach((child) => {
      if (child.nodeType !== 1) return;
      if (forbidden.has(child.tagName)) {
        child.remove();
        return;
      }
      [...child.attributes].forEach((attr) => {
        const name = attr.name.toLowerCase();
        const value = attr.value || "";
        if (name.startsWith("on") || name === "srcdoc" || name === "style") {
          child.removeAttribute(attr.name);
        }
        if ((name === "href" || name === "src" || name === "xlink:href") && /^\s*javascript:/i.test(value)) {
          child.removeAttribute(attr.name);
        }
      });
      walk(child);
    });
  };
  walk(tpl.content);
  return tpl.innerHTML;
}

function registerPersona(name, description) {
  if (!name) return;
  if (!personaMeta[name]) {
    const idx = Object.keys(personaMeta).length % ROLE_COLORS.length;
    personaMeta[name] = {
      color: ROLE_COLORS[idx],
      initial: name.trim().slice(0, 1) || "视",
      description: description || "",
    };
  }
}

function resetDialogue(hostLine) {
  personaMeta = {};
  lastExpertName = "";
  seminarWatermark = "";
  muteSpeak = false;
  const thread = document.getElementById("dialogueThread");
  if (thread) thread.replaceChildren();
  if (hostLine === false) return;
  speakHost(
    hostLine ||
      "我是主持人。课题定下之后，我会请来各位视角嘉宾对谈：检索、分歧与成章的节奏由我报幕，专业判断交给他们。"
  );
}

function ingestSeminar(items) {
  if (!items || !items.length) return;
  for (const u of items) {
    if (u.ts && seminarWatermark && u.ts <= seminarWatermark) continue;
    speak({
      kind: u.kind,
      name: u.name,
      roleLabel: u.role_label || u.roleLabel || "",
      text: u.text,
      color: u.color,
    });
    if (u.ts) seminarWatermark = u.ts;
  }
}

function speak({ kind, name, roleLabel, text, color }) {
  if (muteSpeak) return;
  const thread = document.getElementById("dialogueThread");
  if (!thread || !text) return;
  const card = document.createElement("article");
  card.className = `dialogue-card ${kind || "expert"}`;
  const avatar = document.createElement("div");
  avatar.className = "dialogue-avatar";
  avatar.textContent = (name || "主").trim().slice(0, 1);
  if (color) avatar.style.background = color;
  const bubble = document.createElement("div");
  bubble.className = "dialogue-bubble";
  const meta = document.createElement("div");
  meta.className = "dialogue-meta";
  const nameEl = document.createElement("span");
  nameEl.className = "dialogue-name";
  nameEl.textContent = name || "主持人";
  const roleEl = document.createElement("span");
  roleEl.className = "dialogue-role";
  roleEl.textContent = roleLabel || "";
  meta.appendChild(nameEl);
  if (roleLabel) meta.appendChild(roleEl);
  const body = document.createElement("div");
  body.className = "dialogue-text";
  body.textContent = text;
  bubble.appendChild(meta);
  bubble.appendChild(body);
  card.appendChild(avatar);
  card.appendChild(bubble);
  thread.appendChild(card);
  thread.scrollTop = thread.scrollHeight;
}

function speakHost(text) {
  speak({ kind: "host", name: "主持人", roleLabel: "调度", text, color: "#F1C40F" });
}

function speakExpert(name, text) {
  registerPersona(name);
  const meta = personaMeta[name] || {};
  lastExpertName = name;
  speak({ kind: "expert", name, roleLabel: "视角", text, color: meta.color });
}

function speakReviewer(text) {
  speak({ kind: "reviewer", name: "审稿人", roleLabel: "红蓝对抗", text, color: "#E8A33D" });
}

function speakScribe(text) {
  speak({ kind: "scribe", name: "书记员", roleLabel: "成章", text, color: "#7CDBA5" });
}

// ── Tab 切换 ──
function initTabs() {
  const tabBtns = document.querySelectorAll(".tab-btn");
  tabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      tabBtns.forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));

      btn.classList.add("active");
      const targetId = btn.getAttribute("data-target");
      const targetPane = document.getElementById(targetId);
      if (targetPane) targetPane.classList.add("active");
    });
  });
}

// ── 按钮事件绑定 ──
function initActionButtons() {
  const startBtn = document.getElementById("startBtn");
  const stopBtn = document.getElementById("stopBtn");
  const exportTypstBtn = document.getElementById("exportTypstBtn");
  const exportSlidesBtn = document.getElementById("exportSlidesBtn");
  const exportHtmlBtn = document.getElementById("exportHtmlBtn");
  const copyMdBtn = document.getElementById("copyMdBtn");
  const newTaskBtn = document.getElementById("newTaskBtn");

  if (startBtn) startBtn.addEventListener("click", startResearchTask);
  if (stopBtn) stopBtn.addEventListener("click", stopCurrentTask);
  if (exportTypstBtn) exportTypstBtn.addEventListener("click", exportTypstPaper);
  if (exportSlidesBtn) exportSlidesBtn.addEventListener("click", exportSlidesMarp);
  if (exportHtmlBtn) exportHtmlBtn.addEventListener("click", exportHtmlReport);
  if (copyMdBtn) copyMdBtn.addEventListener("click", copyMarkdownToClipboard);
  if (newTaskBtn) newTaskBtn.addEventListener("click", resetToNewTask);
}

function appendLog(message, _type = "info") {
  speakHost(message);
}

function updateStatus(text, isBusy = false) {
  const headerStatus = document.getElementById("headerStatus");
  if (!headerStatus) return;
  const indicator = headerStatus.querySelector(".status-indicator");
  const textEl = headerStatus.querySelector(".status-text");

  if (textEl) textEl.textContent = text;
  if (indicator) {
    if (isBusy) {
      indicator.classList.add("busy");
    } else {
      indicator.classList.remove("busy");
    }
  }
}

function setTimelineStep(stepNum, status = "active", descText = "") {
  const step = document.querySelector(`.timeline-step[data-step="${stepNum}"]`);
  if (!step) return;

  step.classList.remove("active", "completed");
  if (status) {
    step.classList.add(status);
  }

  const descEl = document.getElementById(`step${stepNum}Desc`);
  if (descEl && descText) {
    descEl.textContent = descText;
  }
}

function resetTimeline() {
  for (let i = 1; i <= 5; i++) {
    setTimelineStep(i, "", "待开始");
  }
  updateProgressAndTokens(0, 0, "待启动");
}

function updateProgressAndTokens(pct, tokens, statusHint = "") {
  const bar = document.getElementById("overallProgressBar");
  const pctText = document.getElementById("progressPctText");
  const tokenDisplay = document.getElementById("tokenCountDisplay");
  const remainText = document.getElementById("estimatedRemainingText");

  if (bar && pct !== null && pct !== undefined) {
    bar.style.width = `${Math.min(100, Math.max(0, pct))}%`;
  }
  if (pctText && pct !== null && pct !== undefined) {
    pctText.textContent = `进度: ${Math.round(pct)}%`;
  }
  if (tokenDisplay && tokens !== null && tokens !== undefined) {
    tokenDisplay.textContent = Number(tokens).toLocaleString();
  }
  if (remainText && statusHint) {
    remainText.textContent = statusHint;
  }
}

// ── 快速新建研究（重置视图）──
function resetToNewTask() {
  if (currentEventSource) {
    currentEventSource.close();
    currentEventSource = null;
  }
  currentTaskId = null;
  localStorage.removeItem("storm_last_task_id");

  const topicInput = document.getElementById("topicInput");
  if (topicInput) topicInput.value = "";
  
  const startBtn = document.getElementById("startBtn");
  const stopBtn = document.getElementById("stopBtn");
  if (startBtn) startBtn.disabled = false;
  if (stopBtn) stopBtn.disabled = true;
  updateStatus("就绪", false);

  resetTimeline();
  resetDialogue();
  resumeTaskId = null;

  const renderContainer = document.getElementById("articleRender");
  if (renderContainer) {
    renderContainer.replaceChildren();
    const empty = document.createElement("div");
    empty.className = "empty-state";
    const img = document.createElement("img");
    img.className = "empty-mark";
    img.src = "/static/brand/suzhi-mark.svg";
    img.width = 64;
    img.height = 64;
    img.alt = "";
    const h3 = document.createElement("h3");
    h3.textContent = "尚未生成研究成果";
    const p = document.createElement("p");
    p.textContent = "在左侧输入研究主题并启动深度研究。研讨现场的对谈会与正文并排展开。";
    empty.append(img, h3, p);
    renderContainer.appendChild(empty);
  }
  const citContainer = document.getElementById("citationsList");
  if (citContainer) citContainer.innerHTML = '<div class="empty-state">暂无参考文献</div>';
  const citCount = document.getElementById("citationCount");
  if (citCount) citCount.textContent = "0";
  const rawMd = document.getElementById("rawMarkdown");
  if (rawMd) rawMd.value = "";
}

// ── 启动研究任务 ──
async function startResearchTask() {
  const topicInput = document.getElementById("topicInput");
  const topic = topicInput ? topicInput.value.trim() : "";
  if (!topic) {
    alert("请输入研究课题名称！");
    return;
  }

  const deepResearchToggle = document.getElementById("deepResearchToggle");
  const deepResearch = deepResearchToggle ? deepResearchToggle.checked : true;
  const depthSelect = document.getElementById("depthSelect");
  const maxDepth = depthSelect ? parseInt(depthSelect.value) : 2;
  const perspectivesInput = document.getElementById("perspectivesInput");
  const perspectives = perspectivesInput ? parseInt(perspectivesInput.value) : 3;
  const localDocsInput = document.getElementById("localDocsInput");
  const localDocsDir = localDocsInput && localDocsInput.value.trim() ? localDocsInput.value.trim() : null;

  const startBtn = document.getElementById("startBtn");
  const stopBtn = document.getElementById("stopBtn");

  if (startBtn) startBtn.disabled = true;
  if (stopBtn) stopBtn.disabled = false;
  updateStatus("研究进行中...", true);

  resetDialogue(false);
  resetTimeline();

  try {
    const payload = {
      topic: topic,
      deep_research: deepResearch,
      max_depth: maxDepth,
      perspectives: perspectives,
      local_docs_dir: localDocsDir,
    };
    if (resumeTaskId) payload.resume_task_id = resumeTaskId;
    const resuming = Boolean(resumeTaskId);
    resumeTaskId = null;

    const res = await apiFetch("/api/v1/research/start", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    if (!res.ok) throw new Error(await readError(res, "服务异常"));

    const data = await res.json();
    currentTaskId = data.task_id;
    localStorage.setItem("storm_last_task_id", currentTaskId);
    speakHost(resuming ? `从断点继续，场次编号 ${currentTaskId}。` : `本场研讨编号 ${currentTaskId}。`);

    loadTaskList(true);
    connectEventStream(currentTaskId);
  } catch (err) {
    speakHost(`没能开场：${err.message}`);
    if (startBtn) startBtn.disabled = false;
    if (stopBtn) stopBtn.disabled = true;
    updateStatus("发生错误", false);
  }
}

// ── 建立 SSE 实时事件流（带自动重连）──
let sseReconnectTimer = null;
function connectEventStream(taskId, retryCount = 0) {
  if (currentEventSource) {
    currentEventSource.close();
    currentEventSource = null;
  }
  if (sseReconnectTimer) {
    clearTimeout(sseReconnectTimer);
    sseReconnectTimer = null;
  }

  currentEventSource = new EventSource(withTokenQuery(`/api/v1/research/stream/${taskId}`));

  currentEventSource.onmessage = (event) => {
    retryCount = 0; // 收到数据重置重试计数
    try {
      const payload = JSON.parse(event.data);
      handleServerEvent(payload);
    } catch (e) {}
  };

  currentEventSource.onerror = (err) => {
    if (currentEventSource) {
      currentEventSource.close();
      currentEventSource = null;
    }
    // 指数退避重连（最多 5 次）
    if (retryCount < 5) {
      const delay = Math.min(1000 * Math.pow(1.5, retryCount), 5000);
      console.warn(`SSE stream closed. Reconnecting in ${delay}ms (Attempt ${retryCount + 1}/5)...`);
      sseReconnectTimer = setTimeout(() => {
        connectEventStream(taskId, retryCount + 1);
      }, delay);
    }
  };
}

// ── 处理来自后端的阶段性流式事件 ──
function handleServerEvent(event) {
  const stage = event.stage;
  const data = event.data || {};
  const tokens = event.tokens_used;
  const pct = event.progress_pct;

  if (pct !== undefined && pct !== null) {
    let hint = "进行中...";
    if (pct >= 100) hint = "已完成";
    else if (pct >= 70) hint = "正文生成中";
    else if (pct >= 20) hint = "知识策展中";
    updateProgressAndTokens(pct, tokens, hint);
  } else if (tokens !== undefined) {
    updateProgressAndTokens(null, tokens);
  }

  const fromServer = Array.isArray(event.seminar) && event.seminar.length > 0;
  if (stage !== "STAGE_SNAPSHOT" && fromServer) {
    ingestSeminar(event.seminar);
    muteSpeak = true;
  } else {
    muteSpeak = false;
  }

  try {
  switch (stage) {
    case "STAGE_SNAPSHOT":
      handleStageSnapshot(data);
      break;

    case "DISCOVERY_START":
      setTimelineStep(1, "active", "提取专家视角中...");
      speakHost("先请几位视角嘉宾入座。我去对一下各自的专长。");
      break;

    case "DISCOVERY_COMPLETE":
      setTimelineStep(1, "completed", `生成 ${data.personas ? data.personas.length : 0} 个视角`);
      if (data.personas && data.personas.length) {
        speakHost(`请来 ${data.personas.length} 位嘉宾。请各位先自报家门。`);
        data.personas.forEach((p) => {
          registerPersona(p.name, p.description);
          speakExpert(p.name, p.description || "从本视角跟进这一课题。");
        });
      } else {
        speakHost("视角名单还没拟好，我用默认席位继续。");
      }
      break;

    case "CURATION_START":
      setTimelineStep(2, "active", "检索与事实提炼中...");
      speakHost("进入策展。请各位带着问题去找证据，有分歧就摊在桌上。");
      break;

    case "DEEP_RESEARCH_TREE_ACTIVE":
      speakHost("这一场走深度探索树：增益不够就停，够了再往下问。");
      break;

    case "DEEP_EXPLORATION_NODE_START":
      if (data.perspective) {
        speakExpert(
          data.perspective,
          `我从第 ${data.depth ?? "?"} 层追问：${data.query || "继续检索。"}`
        );
      } else {
        speakHost(`下钻一层（深度 ${data.depth}）：${data.query || ""}`);
      }
      break;

    case "SEARCH_ISSUED":
      speakHost(`检索发出：「${data.query || ""}」`);
      break;

    case "SEARCH_HITS":
      if (data.samples && data.samples.length > 0) {
        const sampleTitles = data.samples.map((s) => s.title).filter(Boolean).join("；");
        speakHost(`这一轮命中 ${data.count} 篇。例如：${sampleTitles}`);
      }
      break;

    case "FACTS_EXTRACTED": {
      const facts = (data.facts || []).filter(Boolean).join("；");
      const gain = Number(data.gain_score || 0).toFixed(2);
      const speaker = lastExpertName || data.perspective;
      const line = `我记下这些事实（增益 ${gain}）：${facts || "这一轮没有新的可靠陈述。"}`;
      if (speaker) speakExpert(speaker, line);
      else speakHost(line);
      break;
    }

    case "DECISION_BRANCH":
      speakHost(
        `增益 ${(data.gain || 0).toFixed(2)}，还值得往下问：${(data.derived_queries || []).join("；") || "派生问题待拟。"}`
      );
      break;

    case "DECISION_SATURATE":
      speakHost(`${data.reason || "这一支先到此。"}（增益 ${(data.gain || 0).toFixed(2)}）`);
      break;

    case "CURATION_COMPLETE":
      setTimelineStep(2, "completed", `沉淀 ${data.fact_count} 条事实`);
      speakHost(`策展告一段落，事实池里现有 ${data.fact_count} 条。下面请书记员排大纲。`);
      break;

    case "OUTLINE_START":
      setTimelineStep(3, "active", "编排学术大纲...");
      speakScribe("我来把刚才的证据收成章节骨架。");
      break;

    case "OUTLINE_COMPLETE":
      setTimelineStep(3, "completed", "大纲已确立");
      if (data.section_titles && data.section_titles.length > 0) {
        speakScribe(`大纲 ${data.section_titles.length} 章：${data.section_titles.join(" → ")}`);
      } else {
        speakScribe("大纲已经立住。");
      }
      break;

    case "WRITING_START":
      setTimelineStep(4, "active", "章节并行起草中...");
      speakHost("请书记员按章起草。图谱若有口径冲突，一并写进对照。");
      break;

    case "FACT_GRAPH_EXTRACTING":
      speakHost("正在核对跨信源关系与分歧。");
      break;

    case "FACT_GRAPH_COMPLETE":
      speakHost(
        `图谱抽出 ${data.triples_count || 0} 条关系，口径差异 ${data.conflicts_count || 0} 处。`
      );
      if (data.sample_triples && data.sample_triples.length > 0) {
        speakHost(`例如：${data.sample_triples.join("；")}`);
      }
      break;

    case "SECTION_WRITING_START":
      speakScribe(`正在写《${data.section || "未名章节"}》。`);
      break;

    case "SECTION_WRITTEN":
      speakScribe(
        `《${data.section || "未名章节"}》初稿 ${data.char_count || 0} 字${data.has_diagram ? "，附机制图" : ""}。`
      );
      break;

    case "WRITING_COMPLETE":
      setTimelineStep(4, "completed", `完成正文 (${data.article_len} 字)`);
      speakScribe(`初稿合成，约 ${data.article_len} 字。请审稿人过目。`);
      break;

    case "REVIEW_START":
      speakReviewer("我按学术规范做红蓝对抗：引用、断言、结构，一处一处看。");
      break;

    case "REVIEW_COMPLETE":
      speakReviewer(
        `综合 ${data.score} / 100。${data.passed ? "这一稿可以过。" : "还不到线，我建议局部修订。"}`
      );
      if (data.suggestions && data.suggestions.length > 0) {
        speakReviewer(`意见：${data.suggestions.join("；")}`);
      }
      break;

    case "REFLEXION_ACTIVE":
      speakReviewer("按刚才的意见打补丁，只动有问题的段落。");
      break;

    case "REFLEXION_PATCH_APPLIED":
      speakScribe(`补丁已打上，正文现约 ${data.new_len || 0} 字。`);
      break;

    case "POLISH_START":
      setTimelineStep(5, "active", "结构一致性润色...");
      speakHost("最后对标题与排版收一遍，准备成章。");
      break;

    case "COMPLETED":
    case "DONE":
      setTimelineStep(1, "completed", "视角已确立");
      setTimelineStep(2, "completed", "知识策展完成");
      setTimelineStep(3, "completed", "大纲已完成");
      setTimelineStep(4, "completed", "正文起草完成");
      setTimelineStep(5, "completed", "研究全流程完成");
      speakHost("本场结束。右侧是成稿，引用仍可回溯到各位刚才举过的证据。");
      updateStatus("已就绪", false);
      const sBtn = document.getElementById("startBtn");
      const eBtn = document.getElementById("stopBtn");
      if (sBtn) sBtn.disabled = false;
      if (eBtn) eBtn.disabled = true;
      if (currentEventSource) currentEventSource.close();
      fetchArticleData(currentTaskId);
      loadTaskList(true);
      break;

    case "STOPPED":
      speakHost(data.message || "这一场先停在这里。可在任务列表里续开。");
      updateStatus("已中断", false);
      const sBtn2 = document.getElementById("startBtn");
      const eBtn2 = document.getElementById("stopBtn");
      if (sBtn2) sBtn2.disabled = false;
      if (eBtn2) eBtn2.disabled = true;
      if (currentEventSource) currentEventSource.close();
      loadTaskList(true);
      break;

    case "ERROR":
      speakHost(`这一场出了差错：${data.error || "未知错误"}`);
      updateStatus("发生错误", false);
      const sBtn3 = document.getElementById("startBtn");
      const eBtn3 = document.getElementById("stopBtn");
      if (sBtn3) sBtn3.disabled = false;
      if (eBtn3) eBtn3.disabled = true;
      if (currentEventSource) currentEventSource.close();
      loadTaskList(true);
      break;
  }
  } finally {
    muteSpeak = false;
  }
}

// ── 处理重连时的快照回放 ──
function handleStageSnapshot(data) {
  const topicInput = document.getElementById("topicInput");
  if (data.topic && topicInput && !topicInput.value) {
    topicInput.value = data.topic;
  }
  if (data.personas) {
    data.personas.forEach((p) => registerPersona(p.name, p.description));
  }
  if (Array.isArray(data.seminar_log) && data.seminar_log.length) {
    resetDialogue(false);
    ingestSeminar(data.seminar_log);
  } else {
    speakHost(`接上一次的场次（阶段 ${data.stage}，已有事实 ${data.fact_count || 0} 条）。`);
  }

  const stage = data.stage;
  const stageOrder = ["INIT", "DISCOVERY", "CURATION", "OUTLINE", "WRITING", "COMPLETED"];
  const curIdx = stageOrder.indexOf(stage);

  if (curIdx >= 1) setTimelineStep(1, "completed", `已提取 ${data.personas ? data.personas.length : 0} 视角`);
  if (curIdx >= 2) setTimelineStep(2, "completed", `已沉淀 ${data.fact_count} 条事实`);
  if (curIdx >= 3) setTimelineStep(3, "completed", "大纲已确立");
  if (curIdx >= 4) setTimelineStep(4, "completed", "正文已起草");
  if (curIdx >= 5) setTimelineStep(5, "completed", "研究完成");

  if (data.has_draft) {
    fetchArticleData(currentTaskId);
  }
}

// ── 获取完整长文与引用（集成 Mermaid 矢量图表渲染）──
async function fetchArticleData(taskId) {
  try {
    const res = await apiFetch(`/api/v1/research/article/${taskId}`);
    if (!res.ok) return;

    const data = await res.json();
    const articleMd = data.article || "";
    allCitations = data.citations || {};

    const renderContainer = document.getElementById("articleRender");
    if (renderContainer) {
      await renderMarkdownAndMermaid(articleMd, renderContainer);
    }

    const rawMd = document.getElementById("rawMarkdown");
    if (rawMd) rawMd.value = articleMd;
    renderCitationsList(allCitations);
  } catch (e) {
    console.error("Failed to fetch article:", e);
  }
}

async function renderMarkdownAndMermaid(articleMd, renderContainer) {
  if (!renderContainer) return;
  const parseMd = (md) => {
    if (typeof marked === "undefined") return null;
    if (typeof marked.parse === "function") return marked.parse(md);
    if (marked.marked && typeof marked.marked.parse === "function") return marked.marked.parse(md);
    if (typeof marked === "function") return marked(md);
    return null;
  };
  const parsed = parseMd(articleMd || "");
  if (parsed == null) {
    renderContainer.textContent = articleMd;
    return;
  }

  renderContainer.innerHTML = sanitizeHtml(parsed);

  renderContainer.querySelectorAll("pre code.language-mermaid").forEach((code) => {
    const wrap = document.createElement("div");
    wrap.className = "mermaid-wrapper";
    const mermaidNode = document.createElement("div");
    mermaidNode.className = "mermaid";
    mermaidNode.textContent = code.textContent || "";
    wrap.appendChild(mermaidNode);
    if (code.parentElement) code.parentElement.replaceWith(wrap);
  });

  renderContainer.innerHTML = sanitizeHtml(
    renderContainer.innerHTML.replace(/\[(\d+)\](?!\()/g, (_m, n) => {
      return `<sup class="citation-ref-wrapper"><a href="#ref-${n}" class="citation-ref-badge" data-cite="${n}">[${n}]</a></sup>`;
    })
  );
  renderContainer.querySelectorAll("a.citation-ref-badge").forEach((a) => {
    a.addEventListener("click", (e) => {
      highlightCitation(a.getAttribute("data-cite"), e);
    });
  });

  if (typeof mermaid !== "undefined") {
    try {
      mermaid.initialize({
        startOnLoad: false,
        theme: "dark",
        securityLevel: "strict",
        themeVariables: {
          darkMode: true,
          background: "#0C1F18",
          primaryColor: "#0D5E42",
          primaryTextColor: "#F5F7FA",
          primaryBorderColor: "#00D2FF",
          lineColor: "#A8B8B2",
          secondaryColor: "#123028",
          tertiaryColor: "#071510"
        }
      });
      await mermaid.run({
        nodes: renderContainer.querySelectorAll(".mermaid")
      });
    } catch (e) {
      console.warn("Mermaid SVG render failed, keeping text fallback:", e);
    }
  }
}

// ── 参考文献卡片点击定位与高亮联动 ──
function highlightCitation(idx, e) {
  if (e) e.preventDefault();
  // 切换到参考文献 Tab
  const citTabBtn = document.querySelector('.tab-btn[data-target="citationsTab"]');
  if (citTabBtn) citTabBtn.click();

  setTimeout(() => {
    const card = document.getElementById(`ref-${idx}`);
    if (card) {
      card.scrollIntoView({ behavior: "smooth", block: "center" });
      card.classList.add("highlight-pulse");
      setTimeout(() => {
        card.classList.remove("highlight-pulse");
      }, 2500);
    }
  }, 100);
}

function renderCitationsList(citations) {
  const container = document.getElementById("citationsList");
  const countSpan = document.getElementById("citationCount");
  if (!container) return;
  const keys = Object.keys(citations);
  if (countSpan) countSpan.textContent = keys.length;

  if (keys.length === 0) {
    container.replaceChildren();
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "暂无参考文献";
    container.appendChild(empty);
    return;
  }

  container.replaceChildren();
  keys.sort((a, b) => parseInt(a, 10) - parseInt(b, 10)).forEach((key) => {
    const item = citations[key] || {};
    const card = document.createElement("div");
    card.className = "citation-card";
    card.id = `ref-${key}`;
    const header = document.createElement("div");
    header.className = "citation-header";
    const idx = document.createElement("span");
    idx.className = "citation-index";
    idx.textContent = `[${key}]`;
    const title = document.createElement("span");
    title.className = "citation-title";
    title.textContent = item.title || "未命名来源";
    header.append(idx, title);
    if (item.source_quality || item.engine) {
      const meta = document.createElement("span");
      meta.className = "citation-quality";
      const q = Number(item.source_quality || 0);
      const label = q >= 1.15 ? "学术" : q >= 1.0 ? "综合" : "一般";
      meta.textContent = item.engine ? `${label} · ${item.engine}` : label;
      header.appendChild(meta);
    }
    const urlRow = document.createElement("div");
    urlRow.className = "citation-url";
    const link = document.createElement("a");
    link.href = item.url || "#";
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = item.url || "";
    urlRow.appendChild(link);
    const snip = document.createElement("div");
    snip.className = "citation-snippets";
    snip.textContent = (item.snippets || []).join("\n\n") || "暂无摘录";
    card.append(header, urlRow, snip);
    container.appendChild(card);
  });
}

// ── 手动中断任务 ──
async function stopCurrentTask() {
  if (!currentTaskId) return;
  try {
    const res = await apiFetch(`/api/v1/research/stop/${currentTaskId}`, { method: "POST" });
    if (res.ok) {
      appendLog("⚠️ 已向服务端发送任务终止指令...", "warn");
    }
  } catch (e) {
    console.error("Stop task error:", e);
  }
  if (currentEventSource) {
    currentEventSource.close();
  }
  updateStatus("已中断", false);
  const sBtn = document.getElementById("startBtn");
  const eBtn = document.getElementById("stopBtn");
  if (sBtn) sBtn.disabled = false;
  if (eBtn) eBtn.disabled = true;
  loadTaskList(true);
}

// ── 导出功能（支持自动物理下载）──
function triggerBrowserDownload(url, filename) {
  const a = document.createElement("a");
  a.href = withTokenQuery(url);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

async function exportTypstPaper() {
  if (!currentTaskId) {
    alert("请先选择或完成一次研究任务！");
    return;
  }
  try {
    const res = await apiFetch(`/api/v1/export/typst/${currentTaskId}`, { method: "POST" });
    if (!res.ok) throw new Error("导出失败");
    const data = await res.json();
    if (data.pdf_download_url) {
      triggerBrowserDownload(data.pdf_download_url, `${currentTaskId}_paper.pdf`);
      speakHost("已导出 Typst PDF。");
    } else if (data.download_url) {
      triggerBrowserDownload(data.download_url, `${currentTaskId}_paper.typ`);
      speakHost("本机未安装 Typst CLI，已下载 .typ 源文件。");
    }
  } catch (e) {
    alert(`导出失败: ${e.message}`);
  }
}

async function exportSlidesMarp() {
  if (!currentTaskId) {
    alert("请先选择或完成一次研究任务！");
    return;
  }
  try {
    const res = await apiFetch(`/api/v1/export/slides/${currentTaskId}`, { method: "POST" });
    if (!res.ok) throw new Error("导出失败");
    const data = await res.json();
    if (data.download_url) {
      triggerBrowserDownload(data.download_url, `${currentTaskId}_slides.marp.md`);
      appendLog(`📥 已自动触发 Marp 幻灯片下载: ${currentTaskId}_slides.marp.md`, "success");
    }
  } catch (e) {
    alert(`导出失败: ${e.message}`);
  }
}

async function exportHtmlReport() {
  if (!currentTaskId) {
    alert("请先选择或完成一次研究任务！");
    return;
  }
  try {
    const res = await apiFetch(`/api/v1/export/html/${currentTaskId}`, { method: "POST" });
    if (!res.ok) throw new Error("导出失败");
    const data = await res.json();
    if (data.download_url) {
      triggerBrowserDownload(data.download_url, `${currentTaskId}_report_standalone.html`);
      appendLog(`📥 已自动触发独立 HTML 研报下载: ${currentTaskId}_report_standalone.html`, "success");
    }
  } catch (e) {
    alert(`导出失败: ${e.message}`);
  }
}

function copyMarkdownToClipboard() {
  const rawTextEl = document.getElementById("rawMarkdown");
  const rawText = rawTextEl ? rawTextEl.value : "";
  if (!rawText) {
    alert("暂无内容可复制！");
    return;
  }
  navigator.clipboard.writeText(rawText).then(() => {
    alert("✅ Markdown 正文已成功复制到剪贴板！");
  });
}

// ── 📁 任务管理中心与自动恢复机制 ──

function initTasksModal() {
  const openBtn = document.getElementById("openTasksBtn");
  const closeBtn = document.getElementById("closeTasksBtn");
  const refreshBtn = document.getElementById("refreshTasksBtn");
  const modal = document.getElementById("tasksModal");

  if (openBtn) {
    openBtn.addEventListener("click", () => {
      loadTaskList();
      if (modal) modal.classList.add("active");
    });
  }

  const closeModal = () => {
    if (modal) modal.classList.remove("active");
  };
  if (closeBtn) closeBtn.addEventListener("click", closeModal);
  if (refreshBtn) refreshBtn.addEventListener("click", () => loadTaskList());
  const compareBtn = document.getElementById("compareTasksBtn");
  if (compareBtn) compareBtn.addEventListener("click", runTaskCompare);
}

function fillCompareSelects(tasks) {
  const left = document.getElementById("compareLeft");
  const right = document.getElementById("compareRight");
  if (!left || !right) return;
  const makeOpts = (el, preferSecond) => {
    const prev = el.value;
    el.replaceChildren();
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "选择任务";
    el.appendChild(blank);
    tasks.forEach((t) => {
      const opt = document.createElement("option");
      opt.value = t.task_id;
      opt.textContent = `${t.topic} (${t.task_id})`;
      el.appendChild(opt);
    });
    if (prev && tasks.some((t) => t.task_id === prev)) el.value = prev;
    else if (preferSecond && tasks[1]) el.value = tasks[1].task_id;
    else if (tasks[0]) el.value = tasks[0].task_id;
  };
  makeOpts(left, false);
  makeOpts(right, true);
}

async function runTaskCompare() {
  const left = document.getElementById("compareLeft");
  const right = document.getElementById("compareRight");
  const out = document.getElementById("compareDiff");
  if (!left || !right || !out) return;
  if (!left.value || !right.value || left.value === right.value) {
    out.hidden = false;
    out.classList.add("visible");
    out.textContent = "请选择两个不同的任务。";
    return;
  }
  try {
    const res = await apiFetch(
      `/api/v1/research/compare?left=${encodeURIComponent(left.value)}&right=${encodeURIComponent(right.value)}`
    );
    if (!res.ok) throw new Error(await readError(res, "对比失败"));
    const data = await res.json();
    const header = [
      data.same_topic ? "同一主题" : "不同主题",
      `${data.left.topic} [${data.left.task_id}] ${data.left.article_len} 字 / ${data.left.fact_count} 事实`,
      `${data.right.topic} [${data.right.task_id}] ${data.right.article_len} 字 / ${data.right.fact_count} 事实`,
      `差异块 ${data.hunks || 0}`,
      "",
    ].join("\n");
    out.hidden = false;
    out.classList.add("visible");
    out.textContent = header + (data.diff || "（正文相同或尚无正文）");
  } catch (e) {
    out.hidden = false;
    out.classList.add("visible");
    out.textContent = e.message;
  }
}

async function loadTaskList(silent = false) {
  try {
    const res = await apiFetch("/api/v1/tasks?limit=50");
    if (!res.ok) return;
    const data = await res.json();
    taskListCache = data.tasks || [];

    const badge = document.getElementById("taskBadgeCount");
    if (badge) badge.textContent = taskListCache.length;

    fillCompareSelects(taskListCache);
    if (!silent) {
      renderTaskList(taskListCache);
    }
  } catch (e) {
    console.error("Failed to load tasks:", e);
  }
}

function renderTaskList(tasks) {
  const container = document.getElementById("tasksContainer");
  if (!container) return;

  if (tasks.length === 0) {
    container.innerHTML = `<div class="empty-state">暂无历史研究任务。在主页启动深度研究即可在此管理。</div>`;
    return;
  }

  let html = "";
  tasks.forEach(t => {
    const isActive = t.task_id === currentTaskId;
    const stageBadge = getStageBadge(t.display_stage);
    const dateStr = t.updated_at ? new Date(t.updated_at).toLocaleString() : "未知时间";

    html += `
      <div class="task-card ${isActive ? 'active' : ''}" onclick="selectTask('${t.task_id}')">
        <div class="task-info">
          <div class="task-title-row">
            <span class="task-title">${escapeHtml(t.topic)}</span>
            ${stageBadge}
          </div>
          <div class="task-meta">
            <span>🆔 ${t.task_id}</span>
            <span>🕒 ${dateStr}</span>
            <span>📚 事实数: ${t.fact_count}</span>
            <span>📄 字数: ${t.article_len || 0}</span>
          </div>
        </div>
        <div class="task-actions" onclick="event.stopPropagation()">
          ${(!t.is_running && t.display_stage && !["COMPLETED", "DONE"].includes(t.display_stage))
            ? `<button class="btn btn-sm btn-outline" type="button" onclick="resumeTask('${escapeHtml(t.task_id)}')">继续</button>`
            : ""}
          <button class="btn-delete" title="删除任务" onclick="deleteTask('${escapeHtml(t.task_id)}')">删除</button>
        </div>
      </div>
    `;
  });
  container.innerHTML = html;
}

function getStageBadge(stage) {
  switch (stage) {
    case "RUNNING":
      return '<span class="task-badge running">🟢 运行中</span>';
    case "COMPLETED":
    case "DONE":
      return '<span class="task-badge completed">✅ 已完成</span>';
    case "STOPPED":
      return '<span class="task-badge stopped">⏸️ 已中断</span>';
    case "ERROR":
      return '<span class="task-badge error">❌ 异常</span>';
    default:
      return `<span class="task-badge stopped">⚪ ${stage}</span>`;
  }
}

function resumeTask(taskId) {
  const task = taskListCache.find((t) => t.task_id === taskId);
  resumeTaskId = taskId;
  currentTaskId = taskId;
  const topicInput = document.getElementById("topicInput");
  if (task && topicInput) topicInput.value = task.topic;
  const modal = document.getElementById("tasksModal");
  if (modal) modal.classList.remove("active");
  startResearchTask();
}

async function selectTask(taskId) {
  const modal = document.getElementById("tasksModal");
  if (modal) modal.classList.remove("active");

  currentTaskId = taskId;
  localStorage.setItem("storm_last_task_id", taskId);

  const task = taskListCache.find(t => t.task_id === taskId);
  if (task) {
    const topicInput = document.getElementById("topicInput");
    if (topicInput) topicInput.value = task.topic;
  }

  resetDialogue(false);

  const startBtn = document.getElementById("startBtn");
  const stopBtn = document.getElementById("stopBtn");

  // 若正在运行，重连 SSE
  if (task && task.is_running) {
    updateStatus("研究进行中...", true);
    if (startBtn) startBtn.disabled = true;
    if (stopBtn) stopBtn.disabled = false;
    connectEventStream(taskId);
  } else {
    // 若已完成或停止，加载文章数据并连一次 snapshot
    updateStatus("已就绪", false);
    if (startBtn) startBtn.disabled = false;
    if (stopBtn) stopBtn.disabled = true;
    connectEventStream(taskId);
    fetchArticleData(taskId);
  }
  loadTaskList(true);
}

async function deleteTask(taskId) {
  if (!confirm(`确定要彻底删除任务 [${taskId}] 及其所有成果文件吗？`)) return;
  try {
    const res = await apiFetch(`/api/v1/tasks/${taskId}`, { method: "DELETE" });
    if (res.ok) {
      if (currentTaskId === taskId) {
        resetToNewTask();
      }
      loadTaskList();
    }
  } catch (e) {
    alert(`删除失败: ${e.message}`);
  }
}

// ── 页面加载时自动恢复上一次任务 ──
async function initAutoRestore() {
  await loadTaskList(true);

  const lastTaskId = localStorage.getItem("storm_last_task_id");
  if (lastTaskId && taskListCache.some(t => t.task_id === lastTaskId)) {
    selectTask(lastTaskId);
  } else if (taskListCache.length > 0) {
    // 默认展示最新一条任务
    selectTask(taskListCache[0].task_id);
  }
}

// ── ⚙️ 系统设置与 ConfigHub 联动 ──
function initSettingsModal() {
  const openBtn = document.getElementById("openSettingsBtn");
  const closeBtn = document.getElementById("closeSettingsBtn");
  const cancelBtn = document.getElementById("cancelSettingsBtn");
  const saveBtn = document.getElementById("saveSettingsBtn");
  const modal = document.getElementById("settingsModal");
  const toggleKeyBtn = document.getElementById("toggleKeyVisibility");
  const keyInput = document.getElementById("llmApiKeyInput");
  const activeLlmSelect = document.getElementById("activeLlmSelect");
  const activeSearchSelect = document.getElementById("activeSearchSelect");
  const probeLlmBtn = document.getElementById("probeLlmBtn");
  const probeSearchBtn = document.getElementById("probeSearchBtn");

  if (openBtn) {
    openBtn.addEventListener("click", () => {
      loadSettingsFromServer();
      if (modal) modal.classList.add("active");
    });
  }

  const closeModal = () => {
    if (modal) modal.classList.remove("active");
  };
  if (closeBtn) closeBtn.addEventListener("click", closeModal);
  if (cancelBtn) cancelBtn.addEventListener("click", closeModal);

  if (toggleKeyBtn && keyInput) {
    toggleKeyBtn.addEventListener("click", () => {
      if (keyInput.type === "password") {
        keyInput.type = "text";
        toggleKeyBtn.textContent = "🙈";
      } else {
        keyInput.type = "password";
        toggleKeyBtn.textContent = "👁️";
      }
    });
  }

  if (activeLlmSelect) {
    activeLlmSelect.addEventListener("change", () => {
      const pId = activeLlmSelect.value;
      if (systemConfig && systemConfig.llm_providers[pId]) {
        const p = systemConfig.llm_providers[pId];
        const baseUrlEl = document.getElementById("llmBaseUrlInput");
        const modelEl = document.getElementById("llmModelInput");
        const probeResEl = document.getElementById("llmProbeResult");
        if (baseUrlEl) baseUrlEl.value = p.base_url || "";
        if (modelEl) modelEl.value = p.model || "";
        if (keyInput) {
          keyInput.value = "";
          keyInput.placeholder = p.has_key ? `已配置密钥 (${p.api_key_masked})，留空保持` : "请输入 API Key";
        }
        if (probeResEl) probeResEl.textContent = "";
      }
    });
  }

  if (activeSearchSelect) {
    activeSearchSelect.addEventListener("change", () => {
      const pId = activeSearchSelect.value;
      if (systemConfig && systemConfig.search_providers[pId]) {
        const p = systemConfig.search_providers[pId];
        const searchApiEl = document.getElementById("searchApiUrlInput");
        const maxConcEl = document.getElementById("searchMaxConcurrentInput");
        const probeResEl = document.getElementById("searchProbeResult");
        if (searchApiEl) searchApiEl.value = p.api_url || "";
        if (maxConcEl) maxConcEl.value = p.max_concurrent || 15;
        if (probeResEl) probeResEl.textContent = "";
      }
    });
  }

  // 探测 LLM
  if (probeLlmBtn) {
    probeLlmBtn.addEventListener("click", async () => {
      const baseUrlEl = document.getElementById("llmBaseUrlInput");
      const baseUrl = baseUrlEl ? baseUrlEl.value.trim() : "";
      const apiKey = keyInput ? keyInput.value.trim() : "";
      const resultDiv = document.getElementById("llmProbeResult");
      if (!resultDiv) return;
      resultDiv.className = "probe-result";
      resultDiv.textContent = "正在探测端点连通性...";

      try {
        const res = await apiFetch("/api/v1/config/probe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ type: "llm", base_url: baseUrl, api_key: apiKey }),
        });
        const data = await res.json();
        if (data.status === "ONLINE") {
          resultDiv.className = "probe-result online";
          resultDiv.textContent = `🟢 端点在线 | 延迟: ${data.rtt_ms}ms | 发现 ${data.models.length} 个模型: ${data.models.slice(0, 3).join(", ")}...`;
          const modelInput = document.getElementById("llmModelInput");
          if (data.models.length > 0 && modelInput && !modelInput.value) {
            modelInput.value = data.models[0];
          }
        } else {
          resultDiv.className = "probe-result offline";
          resultDiv.textContent = `🔴 探测失败: ${data.msg || data.status}`;
        }
      } catch (e) {
        resultDiv.className = "probe-result offline";
        resultDiv.textContent = `🔴 网络异常: ${e.message}`;
      }
    });
  }

  // 探测搜索端点
  if (probeSearchBtn) {
    probeSearchBtn.addEventListener("click", async () => {
      const apiInput = document.getElementById("searchApiUrlInput");
      const apiUrl = apiInput ? apiInput.value.trim() : "";
      const resultDiv = document.getElementById("searchProbeResult");
      if (!resultDiv) return;
      resultDiv.className = "probe-result";
      resultDiv.textContent = "正在测试 SearXNG 连通性...";

      try {
        const res = await apiFetch("/api/v1/config/probe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ type: "search", base_url: apiUrl }),
        });
        const data = await res.json();
        if (data.status === "ONLINE") {
          resultDiv.className = "probe-result online";
          resultDiv.textContent = `🟢 检索在线 | RTT: ${data.rtt_ms}ms | 测试召回: ${data.sample_count} 条结果`;
        } else {
          resultDiv.className = "probe-result offline";
          resultDiv.textContent = `🔴 检索失败: ${data.msg || data.status}`;
        }
      } catch (e) {
        resultDiv.className = "probe-result offline";
        resultDiv.textContent = `🔴 检索异常: ${e.message}`;
      }
    });
  }

  // 保存配置
  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      if (!systemConfig || !activeLlmSelect || !activeSearchSelect) return;
      const activeLlm = activeLlmSelect.value;
      const activeSearch = activeSearchSelect.value;

      const currentLlm = systemConfig.llm_providers[activeLlm];
      const baseUrlEl = document.getElementById("llmBaseUrlInput");
      const modelEl = document.getElementById("llmModelInput");
      if (baseUrlEl) currentLlm.base_url = baseUrlEl.value.trim();
      if (modelEl) currentLlm.model = modelEl.value.trim();
      if (keyInput && keyInput.value.trim()) {
        currentLlm.api_key = keyInput.value.trim();
      }

      const currentSearch = systemConfig.search_providers[activeSearch];
      const searchApiEl = document.getElementById("searchApiUrlInput");
      const maxConcEl = document.getElementById("searchMaxConcurrentInput");
      if (searchApiEl) currentSearch.api_url = searchApiEl.value.trim();
      if (maxConcEl) currentSearch.max_concurrent = parseInt(maxConcEl.value) || 15;

      try {
        const res = await apiFetch("/api/v1/config/save", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            active_llm_provider: activeLlm,
            active_search_provider: activeSearch,
            deep_research_default: true,
            max_depth: 2,
            llm_providers: systemConfig.llm_providers,
            search_providers: systemConfig.search_providers,
          }),
        });
        if (!res.ok) throw new Error("保存配置失败");
        alert("✅ 配置保存成功，系统已实时热重载！");
        closeModal();
      } catch (e) {
        alert(`保存失败: ${e.message}`);
      }
    });
  }
}

async function loadSettingsFromServer() {
  try {
    const res = await apiFetch("/api/v1/config/providers");
    if (!res.ok) return;
    systemConfig = await res.json();

    const activeLlmSelect = document.getElementById("activeLlmSelect");
    const activeSearchSelect = document.getElementById("activeSearchSelect");

    if (activeLlmSelect) {
      activeLlmSelect.innerHTML = "";
      Object.keys(systemConfig.llm_providers).forEach(pId => {
        const p = systemConfig.llm_providers[pId];
        const opt = document.createElement("option");
        opt.value = pId;
        opt.textContent = `${p.name} (${pId})`;
        if (pId === systemConfig.active_llm_provider) opt.selected = true;
        activeLlmSelect.appendChild(opt);
      });
    }

    if (activeSearchSelect) {
      activeSearchSelect.innerHTML = "";
      Object.keys(systemConfig.search_providers).forEach(pId => {
        const p = systemConfig.search_providers[pId];
        const opt = document.createElement("option");
        opt.value = pId;
        opt.textContent = `${p.name} (${pId})`;
        if (pId === systemConfig.active_search_provider) opt.selected = true;
        activeSearchSelect.appendChild(opt);
      });
    }

    // 触发联动填充
    if (activeLlmSelect) activeLlmSelect.dispatchEvent(new Event("change"));
    if (activeSearchSelect) activeSearchSelect.dispatchEvent(new Event("change"));
  } catch (e) {
    console.error("Failed to load settings:", e);
  }
}

function initKnowledgeModal() {
  const overlay = document.getElementById("knowledgeModal");
  const openBtn = document.getElementById("openKnowledgeBtn");
  const closeBtn = document.getElementById("closeKnowledgeBtn");
  if (!overlay) return;
  const close = () => overlay.classList.remove("active");
  if (openBtn) {
    openBtn.addEventListener("click", async () => {
      overlay.classList.add("active");
      const box = document.getElementById("knowledgeContainer");
      if (box) box.replaceChildren();
      try {
        const res = await apiFetch("/api/v1/knowledge");
        const data = await res.json();
        const articles = data.articles || [];
        if (!articles.length) {
          const empty = document.createElement("div");
          empty.className = "empty-state";
          empty.textContent = "知识库还是空的。完成一场研究后，事实会回流到这里。";
          box.appendChild(empty);
          return;
        }
        articles.forEach((a) => {
          const card = document.createElement("div");
          card.className = "task-card";
          const info = document.createElement("div");
          info.className = "task-info";
          const title = document.createElement("div");
          title.className = "task-title";
          title.textContent = a.topic || a.task_id;
          const meta = document.createElement("div");
          meta.className = "task-meta";
          meta.textContent = `${a.task_id} · 事实 ${a.citations_count || 0} 条`;
          info.append(title, meta);
          card.appendChild(info);
          box.appendChild(card);
        });
      } catch (e) {
        if (box) box.textContent = "加载失败";
      }
    });
  }
  if (closeBtn) closeBtn.addEventListener("click", close);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close();
  });
}

function initAboutModal() {
  const overlay = document.getElementById("aboutModal");
  const openBtn = document.getElementById("openAboutBtn");
  const closeBtn = document.getElementById("closeAboutBtn");
  if (!overlay) return;

  const close = () => overlay.classList.remove("active");
  if (openBtn) openBtn.addEventListener("click", () => overlay.classList.add("active"));
  if (closeBtn) closeBtn.addEventListener("click", close);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && overlay.classList.contains("active")) close();
  });
}
