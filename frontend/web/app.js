// STORM 现代化前端交互逻辑 (SSE Stream Client + ConfigHub Settings)

let currentEventSource = null;
let currentTaskId = null;
let allCitations = {};
let systemConfig = null;

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initActionButtons();
  initSettingsModal();
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

  startBtn.addEventListener("click", startResearchTask);
  stopBtn.addEventListener("click", stopCurrentTask);
  exportTypstBtn.addEventListener("click", exportTypstPaper);
  exportSlidesBtn.addEventListener("click", exportSlidesMarp);
  exportHtmlBtn.addEventListener("click", exportHtmlReport);
  copyMdBtn.addEventListener("click", copyMarkdownToClipboard);
}

function appendLog(message, type = "info") {
  const terminal = document.getElementById("logTerminal");
  const line = document.createElement("div");
  line.className = `log-line ${type}`;
  const time = new Date().toLocaleTimeString();
  line.textContent = `[${time}] ${message}`;
  terminal.appendChild(line);
  terminal.scrollTop = terminal.scrollHeight;
}

function updateStatus(text, isBusy = false) {
  const headerStatus = document.getElementById("headerStatus");
  const indicator = headerStatus.querySelector(".status-indicator");
  const textEl = headerStatus.querySelector(".status-text");

  textEl.textContent = text;
  if (isBusy) {
    indicator.classList.add("busy");
  } else {
    indicator.classList.remove("busy");
  }
}

function setTimelineStep(stepNum, status = "active", descText = "") {
  const step = document.querySelector(`.timeline-step[data-step="${stepNum}"]`);
  if (!step) return;

  step.classList.remove("active", "completed");
  step.classList.add(status);

  const descEl = document.getElementById(`step${stepNum}Desc`);
  if (descEl && descText) {
    descEl.textContent = descText;
  }
}

// ── 启动研究任务 ──
async function startResearchTask() {
  const topic = document.getElementById("topicInput").value.trim();
  if (!topic) {
    alert("请输入研究课题名称！");
    return;
  }

  const deepResearch = document.getElementById("deepResearchToggle").checked;
  const maxDepth = parseInt(document.getElementById("depthSelect").value);
  const perspectives = parseInt(document.getElementById("perspectivesInput").value);
  const localDocsDir = document.getElementById("localDocsInput").value.trim() || null;

  const startBtn = document.getElementById("startBtn");
  const stopBtn = document.getElementById("stopBtn");

  startBtn.disabled = true;
  stopBtn.disabled = false;
  updateStatus("研究进行中...", true);

  document.getElementById("logTerminal").innerHTML = "";
  appendLog(`正在启动研究任务: "${topic}"...`, "info");

  for (let i = 1; i <= 5; i++) {
    setTimelineStep(i, "", "待开始");
  }

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
    appendLog(`任务已分配 ID: ${currentTaskId}`, "success");

    connectEventStream(currentTaskId);
  } catch (err) {
    appendLog(`启动失败: ${err.message}`, "error");
    startBtn.disabled = false;
    stopBtn.disabled = true;
    updateStatus("发生错误", false);
  }
}

// ── 建立 SSE 实时事件流 ──
function connectEventStream(taskId) {
  if (currentEventSource) {
    currentEventSource.close();
  }

  currentEventSource = new EventSource(`/api/v1/research/stream/${taskId}`);

  currentEventSource.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      handleServerEvent(payload);
    } catch (e) {}
  };

  currentEventSource.onerror = (err) => {
    console.warn("SSE stream closed.");
    currentEventSource.close();
  };
}

// ── 处理来自后端的阶段性流式事件 ──
function handleServerEvent(event) {
  const stage = event.stage;
  const data = event.data || {};

  switch (stage) {
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

    case "DEEP_EXPLORATION_NODE_START":
      appendLog(`  ↳ [递归深度 ${data.depth}] 下钻课题: ${data.query}`, "info");
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
      appendLog("✅ 学术大纲生成完成", "success");
      break;

    case "WRITING_START":
      setTimelineStep(4, "active", "章节并行起草中...");
      appendLog("✍️ 正在并行起草章节并构建事实图谱...", "info");
      break;

    case "FACT_GRAPH_EXTRACTING":
      appendLog("  ↳ 正在进行跨信源冲突与事实图谱裁决...", "info");
      break;

    case "SECTION_WRITTEN":
      appendLog(`  ✓ 章节起草完成: ${data.section}`, "success");
      break;

    case "WRITING_COMPLETE":
      setTimelineStep(4, "completed", `完成正文 (${data.article_len} 字)`);
      appendLog(`✅ 正文初稿合成完毕，抽取实体关系 ${data.triples_count || 0} 条`, "success");
      break;

    case "POLISH_START":
      setTimelineStep(5, "active", "结构一致性润色...");
      appendLog("✨ 正在进行最终润色与排版对齐...", "info");
      break;

    case "COMPLETED":
    case "DONE":
      setTimelineStep(5, "completed", "研究完成");
      appendLog("🎉 深度长文研究全流程执行完毕！", "success");
      updateStatus("已就绪", false);
      document.getElementById("startBtn").disabled = false;
      document.getElementById("stopBtn").disabled = true;
      if (currentEventSource) currentEventSource.close();
      fetchArticleData(currentTaskId);
      break;

    case "ERROR":
      appendLog(`❌ 流程发生异常: ${data.error}`, "error");
      updateStatus("发生错误", false);
      document.getElementById("startBtn").disabled = false;
      document.getElementById("stopBtn").disabled = true;
      if (currentEventSource) currentEventSource.close();
      break;
  }
}

// ── 获取完整长文与引用 ──
async function fetchArticleData(taskId) {
  try {
    const res = await fetch(`/api/v1/research/article/${taskId}`);
    if (!res.ok) return;

    const data = await res.json();
    const articleMd = data.article || "";
    allCitations = data.citations || {};

    const renderContainer = document.getElementById("articleRender");
    if (typeof marked !== "undefined") {
      renderContainer.innerHTML = marked.parse(articleMd);
    } else {
      renderContainer.textContent = articleMd;
    }

    document.getElementById("rawMarkdown").value = articleMd;
    renderCitationsList(allCitations);
  } catch (e) {
    console.error("Failed to fetch article:", e);
  }
}

function renderCitationsList(citations) {
  const container = document.getElementById("citationsList");
  const countSpan = document.getElementById("citationCount");
  const keys = Object.keys(citations);
  countSpan.textContent = keys.length;

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

function stopCurrentTask() {
  if (currentEventSource) {
    currentEventSource.close();
  }
  appendLog("⚠️ 任务已被用户手动暂停/中断。状态已持久化，可随时恢复。", "warn");
  updateStatus("已中断", false);
  document.getElementById("startBtn").disabled = false;
  document.getElementById("stopBtn").disabled = true;
}

async function exportTypstPaper() {
  if (!currentTaskId) {
    alert("请先启动并完成一次研究！");
    return;
  }
  try {
    const res = await fetch(`/api/v1/export/typst/${currentTaskId}`, { method: "POST" });
    if (!res.ok) throw new Error("导出失败");
    const data = await res.json();
    alert(`✅ Typst 论文源文件导出成功！\n文件路径: ${data.file_path}`);
  } catch (e) {
    alert(`导出失败: ${e.message}`);
  }
}

async function exportSlidesMarp() {
  if (!currentTaskId) {
    alert("请先启动并完成一次研究！");
    return;
  }
  try {
    const res = await fetch(`/api/v1/export/slides/${currentTaskId}`, { method: "POST" });
    if (!res.ok) throw new Error("导出失败");
    const data = await res.json();
    alert(`✅ Marp 演示幻灯片导出成功！\n文件路径: ${data.file_path}`);
  } catch (e) {
    alert(`导出失败: ${e.message}`);
  }
}

async function exportHtmlReport() {
  if (!currentTaskId) {
    alert("请先启动并完成一次研究！");
    return;
  }
  try {
    const res = await fetch(`/api/v1/export/html/${currentTaskId}`, { method: "POST" });
    if (!res.ok) throw new Error("导出失败");
    const data = await res.json();
    alert(`✅ 独立印刷级 HTML 研报导出成功！\n文件路径: ${data.file_path}`);
  } catch (e) {
    alert(`导出失败: ${e.message}`);
  }
}

function copyMarkdownToClipboard() {
  const rawText = document.getElementById("rawMarkdown").value;
  if (!rawText) {
    alert("暂无内容可复制！");
    return;
  }
  navigator.clipboard.writeText(rawText).then(() => {
    alert("✅ Markdown 正文已成功复制到剪贴板！");
  });
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

  openBtn.addEventListener("click", () => {
    loadSettingsFromServer();
    modal.classList.add("active");
  });

  const closeModal = () => modal.classList.remove("active");
  closeBtn.addEventListener("click", closeModal);
  cancelBtn.addEventListener("click", closeModal);

  toggleKeyBtn.addEventListener("click", () => {
    if (keyInput.type === "password") {
      keyInput.type = "text";
      toggleKeyBtn.textContent = "🙈";
    } else {
      keyInput.type = "password";
      toggleKeyBtn.textContent = "👁️";
    }
  });

  activeLlmSelect.addEventListener("change", () => {
    const pId = activeLlmSelect.value;
    if (systemConfig && systemConfig.llm_providers[pId]) {
      const p = systemConfig.llm_providers[pId];
      document.getElementById("llmBaseUrlInput").value = p.base_url || "";
      document.getElementById("llmModelInput").value = p.model || "";
      keyInput.value = "";
      keyInput.placeholder = p.has_key ? `已配置密钥 (${p.api_key_masked})，留空保持` : "请输入 API Key";
      document.getElementById("llmProbeResult").textContent = "";
    }
  });

  activeSearchSelect.addEventListener("change", () => {
    const pId = activeSearchSelect.value;
    if (systemConfig && systemConfig.search_providers[pId]) {
      const p = systemConfig.search_providers[pId];
      document.getElementById("searchApiUrlInput").value = p.api_url || "";
      document.getElementById("searchMaxConcurrentInput").value = p.max_concurrent || 15;
      document.getElementById("searchProbeResult").textContent = "";
    }
  });

  // 探测 LLM
  probeLlmBtn.addEventListener("click", async () => {
    const baseUrl = document.getElementById("llmBaseUrlInput").value.trim();
    const apiKey = keyInput.value.trim();
    const resultDiv = document.getElementById("llmProbeResult");
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
        if (data.models.length > 0 && !document.getElementById("llmModelInput").value) {
          document.getElementById("llmModelInput").value = data.models[0];
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

  // 探测搜索端点
  probeSearchBtn.addEventListener("click", async () => {
    const apiUrl = document.getElementById("searchApiUrlInput").value.trim();
    const resultDiv = document.getElementById("searchProbeResult");
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

  // 保存配置
  saveBtn.addEventListener("click", async () => {
    if (!systemConfig) return;
    const activeLlm = activeLlmSelect.value;
    const activeSearch = activeSearchSelect.value;

    const currentLlm = systemConfig.llm_providers[activeLlm];
    currentLlm.base_url = document.getElementById("llmBaseUrlInput").value.trim();
    currentLlm.model = document.getElementById("llmModelInput").value.trim();
    if (keyInput.value.trim()) {
      currentLlm.api_key = keyInput.value.trim();
    }

    const currentSearch = systemConfig.search_providers[activeSearch];
    currentSearch.api_url = document.getElementById("searchApiUrlInput").value.trim();
    currentSearch.max_concurrent = parseInt(document.getElementById("searchMaxConcurrentInput").value) || 15;

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

async function loadSettingsFromServer() {
  try {
    const res = await fetch("/api/v1/config/providers");
    if (!res.ok) return;
    systemConfig = await res.json();

    const activeLlmSelect = document.getElementById("activeLlmSelect");
    const activeSearchSelect = document.getElementById("activeSearchSelect");

    activeLlmSelect.innerHTML = "";
    Object.keys(systemConfig.llm_providers).forEach(pId => {
      const p = systemConfig.llm_providers[pId];
      const opt = document.createElement("option");
      opt.value = pId;
      opt.textContent = `${p.name} (${pId})`;
      if (pId === systemConfig.active_llm_provider) opt.selected = true;
      activeLlmSelect.appendChild(opt);
    });

    activeSearchSelect.innerHTML = "";
    Object.keys(systemConfig.search_providers).forEach(pId => {
      const p = systemConfig.search_providers[pId];
      const opt = document.createElement("option");
      opt.value = pId;
      opt.textContent = `${p.name} (${pId})`;
      if (pId === systemConfig.active_search_provider) opt.selected = true;
      activeSearchSelect.appendChild(opt);
    });

    // 触发联动填充
    activeLlmSelect.dispatchEvent(new Event("change"));
    activeSearchSelect.dispatchEvent(new Event("change"));
  } catch (e) {
    console.error("Failed to load settings:", e);
  }
}
