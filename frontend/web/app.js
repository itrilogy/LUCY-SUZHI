// STORM 现代化前端交互逻辑 (SSE Stream Client + ConfigHub Settings + 任务中心与状态恢复)

let currentEventSource = null;
let currentTaskId = null;
let allCitations = {};
let systemConfig = null;
let taskListCache = [];

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initActionButtons();
  initSettingsModal();
  initTasksModal();
  initAutoRestore();
});

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

function appendLog(message, type = "info") {
  const terminal = document.getElementById("logTerminal");
  if (!terminal) return;
  const line = document.createElement("div");
  line.className = `log-line ${type}`;
  const time = new Date().toLocaleTimeString();
  line.textContent = `[${time}] ${message}`;
  terminal.appendChild(line);
  terminal.scrollTop = terminal.scrollHeight;
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
  const terminal = document.getElementById("logTerminal");
  if (terminal) terminal.innerHTML = '<div class="log-line info">等待任务启动...</div>';
  
  const renderContainer = document.getElementById("articleRender");
  if (renderContainer) {
    renderContainer.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">📝</div>
        <h3>尚未生成研究成果</h3>
        <p>在左侧输入研究主题并点击“启动深度研究”，全流程长文与证据链将在此实时呈现。</p>
      </div>
    `;
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

  const terminal = document.getElementById("logTerminal");
  if (terminal) terminal.innerHTML = "";
  appendLog(`正在启动研究任务: "${topic}"...`, "info");
  resetTimeline();

  try {
    const res = await fetch("/api/v1/research/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        topic: topic,
        deep_research: deepResearch,
        max_depth: maxDepth,
        perspectives: perspectives,
        local_docs_dir: localDocsDir,
      }),
    });

    if (!res.ok) throw new Error(`服务异常: ${res.statusText}`);

    const data = await res.json();
    currentTaskId = data.task_id;
    localStorage.setItem("storm_last_task_id", currentTaskId);
    appendLog(`任务已分配 ID: ${currentTaskId}`, "success");

    loadTaskList(true);
    connectEventStream(currentTaskId);
  } catch (err) {
    appendLog(`启动失败: ${err.message}`, "error");
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

  currentEventSource = new EventSource(`/api/v1/research/stream/${taskId}`);

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
    else if (pct >= 70) hint = "正文生成中 (~15s)";
    else if (pct >= 20) hint = "深度策展中 (~35s)";
    updateProgressAndTokens(pct, tokens, hint);
  } else if (tokens !== undefined) {
    updateProgressAndTokens(null, tokens);
  }

  switch (stage) {
    case "STAGE_SNAPSHOT":
      handleStageSnapshot(data);
      break;

    case "DISCOVERY_START":
      setTimelineStep(1, "active", "提取专家视角中...");
      appendLog("🔍 开始生成多维度专家视角矩阵...", "info");
      break;

    case "DISCOVERY_COMPLETE":
      setTimelineStep(1, "completed", `生成 ${data.personas ? data.personas.length : 0} 个视角`);
      if (data.personas) {
        data.personas.forEach(p => {
          appendLog(`  • 视角: ${p.name} - ${p.description}`, "success");
        });
      }
      break;

    case "CURATION_START":
      setTimelineStep(2, "active", "检索与事实提炼中...");
      appendLog("📚 进入多源知识策展与事实沉淀阶段...", "info");
      break;

    case "DEEP_RESEARCH_TREE_ACTIVE":
      appendLog("  ↳ 启用动态递归探索树 (Tree-of-Thoughts)...", "info");
      break;

    case "DEEP_EXPLORATION_NODE_START":
      appendLog(`🔍 [节点探索 (层级 ${data.depth})] ${data.perspective}: "${data.query}"`, "info");
      break;

    case "SEARCH_ISSUED":
      appendLog(`  ↳ 🌐 [SearXNG 检索发起] "${data.query}"`, "search");
      break;

    case "SEARCH_HITS":
      if (data.samples && data.samples.length > 0) {
        const sampleTitles = data.samples.map(s => s.title).join(" | ");
        appendLog(`  ↳ 📄 命中 ${data.count} 篇权威源: ${sampleTitles}`, "search");
      }
      break;

    case "FACTS_EXTRACTED":
      appendLog(`  ↳ 💡 提炼原子事实 (增益评分: ${(data.gain_score || 0).toFixed(2)}): ${data.facts ? data.facts.join("；") : ''}`, "fact");
      break;

    case "DECISION_BRANCH":
      appendLog(`  ↳ 🌲 [深度决策] 增益达标 (Gain ${(data.gain || 0).toFixed(2)})，生成深度下钻盲区: ${(data.derived_queries || []).join("、")}`, "decision");
      break;

    case "DECISION_SATURATE":
      appendLog(`  ↳ 🛑 [深度决策] ${data.reason} (Gain ${(data.gain || 0).toFixed(2)})`, "warn");
      break;

    case "CURATION_COMPLETE":
      setTimelineStep(2, "completed", `沉淀 ${data.fact_count} 条事实`);
      appendLog(`✅ 事实池构建完毕，累计沉淀 ${data.fact_count} 条核心事实`, "success");
      break;

    case "OUTLINE_START":
      setTimelineStep(3, "active", "编排学术大纲...");
      appendLog("📑 正在生成结构化学术大纲...", "info");
      break;

    case "OUTLINE_COMPLETE":
      setTimelineStep(3, "completed", "大纲已确立");
      if (data.section_titles && data.section_titles.length > 0) {
        appendLog(`✅ 学术大纲确立 (${data.section_titles.length} 个核心章节: ${data.section_titles.join(" → ")})`, "success");
      } else {
        appendLog("✅ 学术大纲生成完成", "success");
      }
      break;

    case "WRITING_START":
      setTimelineStep(4, "active", "章节并行起草中...");
      appendLog("✍️ 正在并行起草章节并构建事实图谱...", "info");
      break;

    case "FACT_GRAPH_EXTRACTING":
      appendLog("  ↳ 正在进行跨信源冲突与事实图谱裁决...", "info");
      break;

    case "FACT_GRAPH_COMPLETE":
      appendLog(`🕸️ 实体图谱抽取完成: 提炼三元组 ${data.triples_count || 0} 条，识别口径差异 ${data.conflicts_count || 0} 处`, "info");
      if (data.sample_triples && data.sample_triples.length > 0) {
        appendLog(`  ↳ 样例三元组: ${data.sample_triples.join(" | ")}`, "info");
      }
      break;

    case "SECTION_WRITING_START":
      appendLog(`  ↳ ✍️ 正在起草章节: 《${data.section}》...`, "info");
      break;

    case "SECTION_WRITTEN":
      appendLog(`  ✓ 章节《${data.section}》起草完成 (字数: ${data.char_count || 0}${data.has_diagram ? '，含机制图' : ''})`, "success");
      break;

    case "WRITING_COMPLETE":
      setTimelineStep(4, "completed", `完成正文 (${data.article_len} 字)`);
      appendLog(`✅ 正文初稿合成完毕，抽取实体关系 ${data.triples_count || 0} 条`, "success");
      break;

    case "REVIEW_START":
      appendLog("⚖️ 正在进行学术红蓝对抗评审...", "info");
      break;

    case "REVIEW_COMPLETE":
      appendLog(`  ✓ 学术综合评分: ${data.score} / 100 (${data.passed ? '学术规范达标' : '触发反思修订'})`, data.passed ? "success" : "warn");
      if (data.suggestions && data.suggestions.length > 0) {
        appendLog(`  ↳ 评审优化意见: ${data.suggestions.join("；")}`, "warn");
      }
      break;

    case "REFLEXION_ACTIVE":
      appendLog("  ↳ 触发自适应反思修正补丁...", "warn");
      break;

    case "REFLEXION_PATCH_APPLIED":
      appendLog(`  ✓ 反思补丁应用完毕，最新正文扩充至 ${data.new_len || 0} 字`, "success");
      break;

    case "POLISH_START":
      setTimelineStep(5, "active", "结构一致性润色...");
      appendLog("✨ 正在进行最终润色与排版对齐...", "info");
      break;

    case "COMPLETED":
    case "DONE":
      setTimelineStep(1, "completed", "视角已确立");
      setTimelineStep(2, "completed", "知识策展完成");
      setTimelineStep(3, "completed", "大纲已完成");
      setTimelineStep(4, "completed", "正文起草完成");
      setTimelineStep(5, "completed", "研究全流程完成");
      appendLog("🎉 深度长文研究全流程执行完毕！", "success");
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
      appendLog(`⚠️ ${data.message || '任务已手动终止'}`, "warn");
      updateStatus("已中断", false);
      const sBtn2 = document.getElementById("startBtn");
      const eBtn2 = document.getElementById("stopBtn");
      if (sBtn2) sBtn2.disabled = false;
      if (eBtn2) eBtn2.disabled = true;
      if (currentEventSource) currentEventSource.close();
      loadTaskList(true);
      break;

    case "ERROR":
      appendLog(`❌ 流程发生异常: ${data.error}`, "error");
      updateStatus("发生错误", false);
      const sBtn3 = document.getElementById("startBtn");
      const eBtn3 = document.getElementById("stopBtn");
      if (sBtn3) sBtn3.disabled = false;
      if (eBtn3) eBtn3.disabled = true;
      if (currentEventSource) currentEventSource.close();
      loadTaskList(true);
      break;
  }
}

// ── 处理重连时的快照回放 ──
function handleStageSnapshot(data) {
  const topicInput = document.getElementById("topicInput");
  if (data.topic && topicInput && !topicInput.value) {
    topicInput.value = data.topic;
  }
  appendLog(`🔄 已恢复任务快照 (状态: ${data.stage}，事实数: ${data.fact_count})`, "info");

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
    const res = await fetch(`/api/v1/research/article/${taskId}`);
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
  if (typeof marked === "undefined") {
    renderContainer.textContent = articleMd;
    return;
  }

  // 1. 将 Markdown 解析为基础 HTML
  let rawHtml = marked.parse(articleMd);

  // 2. 将 language-mermaid 代码块无损转换为 div.mermaid 并还原 HTML 实体
  rawHtml = rawHtml.replace(/<pre><code class="language-mermaid">([\s\S]*?)<\/code><\/pre>/gi, (match, p1) => {
    const unescaped = p1
      .replace(/&gt;/g, ">")
      .replace(/&lt;/g, "<")
      .replace(/&amp;/g, "&")
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'");
    return `<div class="mermaid-wrapper"><div class="mermaid">${unescaped.trim()}</div></div>`;
  });

  // 3. 将正文中的引用标识 [1], [2] 自动转为交互式上标徽标
  rawHtml = rawHtml.replace(/\[(\d+)\](?!\()/g, (match, p1) => {
    return `<sup class="citation-ref-wrapper"><a href="#ref-${p1}" class="citation-ref-badge" onclick="highlightCitation(${p1}, event)">[${p1}]</a></sup>`;
  });

  renderContainer.innerHTML = rawHtml;

  // 4. 异步调用 Mermaid.js 渲染引擎
  if (typeof mermaid !== "undefined") {
    try {
      mermaid.initialize({
        startOnLoad: false,
        theme: "dark",
        securityLevel: "loose",
        themeVariables: {
          darkMode: true,
          background: "#12161f",
          primaryColor: "#6366f1",
          primaryTextColor: "#f8fafc",
          primaryBorderColor: "#818cf8",
          lineColor: "#94a3b8",
          secondaryColor: "#1e293b",
          tertiaryColor: "#0f172a"
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
  const citTabBtn = document.querySelector('.tab-btn[data-target="citationsPane"]');
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
    container.innerHTML = `<div class="empty-state">暂无参考文献</div>`;
    return;
  }

  let html = "";
  keys.sort((a, b) => parseInt(a) - parseInt(b)).forEach(key => {
    const item = citations[key];
    const snippets = (item.snippets || []).join("\n\n");
    html += `
      <div class="citation-card" id="ref-${key}">
        <div class="citation-header">
          <span class="citation-index">[${key}]</span>
          <span class="citation-title">${item.title || "Unknown Title"}</span>
        </div>
        <div class="citation-url"><a href="${item.url}" target="_blank">${item.url}</a></div>
        <div class="citation-snippets">${snippets || "暂无摘录"}</div>
      </div>
    `;
  });
  container.innerHTML = html;
}

// ── 手动中断任务 ──
async function stopCurrentTask() {
  if (!currentTaskId) return;
  try {
    const res = await fetch(`/api/v1/research/stop/${currentTaskId}`, { method: "POST" });
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
  a.href = url;
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
    const res = await fetch(`/api/v1/export/typst/${currentTaskId}`, { method: "POST" });
    if (!res.ok) throw new Error("导出失败");
    const data = await res.json();
    if (data.download_url) {
      triggerBrowserDownload(data.download_url, `${currentTaskId}_paper.typ`);
      appendLog(`📥 已自动触发 Typst 论文源文件下载: ${currentTaskId}_paper.typ`, "success");
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
    const res = await fetch(`/api/v1/export/slides/${currentTaskId}`, { method: "POST" });
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
    const res = await fetch(`/api/v1/export/html/${currentTaskId}`, { method: "POST" });
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
}

async function loadTaskList(silent = false) {
  try {
    const res = await fetch("/api/v1/tasks?limit=50");
    if (!res.ok) return;
    const data = await res.json();
    taskListCache = data.tasks || [];

    const badge = document.getElementById("taskBadgeCount");
    if (badge) badge.textContent = taskListCache.length;

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
          <button class="btn-delete" title="删除任务" onclick="deleteTask('${t.task_id}')">🗑️ 删除</button>
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

function escapeHtml(text) {
  if (!text) return "";
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
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

  const terminal = document.getElementById("logTerminal");
  if (terminal) terminal.innerHTML = "";
  appendLog(`🔄 已切换至任务: ${taskId}`, "info");

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
    const res = await fetch(`/api/v1/tasks/${taskId}`, { method: "DELETE" });
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
        const res = await fetch("/api/v1/config/probe", {
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
        const res = await fetch("/api/v1/config/probe", {
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
        const res = await fetch("/api/v1/config/save", {
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
    const res = await fetch("/api/v1/config/providers");
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
