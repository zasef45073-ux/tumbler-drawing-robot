function escapeHTML(value) {
  if (value === null || value === undefined) return "-";

  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}


function setText(id, value) {
  const element = document.getElementById(id);
  if (!element) return;

  element.textContent = value ?? "-";
}


function setProgress(progress) {
  const safeProgress = Number(progress) || 0;
  const clampedProgress = Math.max(0, Math.min(100, safeProgress));

  setText("currentJobProgressText", `${clampedProgress}%`);

  const progressBar = document.getElementById("currentJobProgressBar");
  if (progressBar) {
    progressBar.style.width = `${clampedProgress}%`;
  }
}


function updateConnectionBadge(connection) {
  const badge = document.getElementById("robotConnectionBadge");
  const liveBadge = document.getElementById("liveBadge");

  if (!badge || !connection) return;

  badge.textContent = connection.badge_text || "● 수신 대기";

  badge.classList.remove(
    "badge-online",
    "badge-delayed",
    "badge-offline",
    "badge-waiting"
  );

  if (connection.code === "ONLINE") {
    badge.classList.add("badge-online");
  } else if (connection.code === "DELAYED") {
    badge.classList.add("badge-delayed");
  } else if (connection.code === "OFFLINE") {
    badge.classList.add("badge-offline");
  } else {
    badge.classList.add("badge-waiting");
  }

  if (liveBadge) {
    liveBadge.classList.remove("offline", "delayed");

    if (connection.code === "OFFLINE") {
      liveBadge.textContent = "OFFLINE";
      liveBadge.classList.add("offline");
    } else if (connection.code === "DELAYED") {
      liveBadge.textContent = "DELAYED";
      liveBadge.classList.add("delayed");
    } else if (connection.code === "ONLINE") {
      liveBadge.textContent = "LIVE";
    } else {
      liveBadge.textContent = "WAITING";
      liveBadge.classList.add("delayed");
    }
  }
}


function updateRobotStatus(robotStatus) {
  if (!robotStatus) return;

  setText("robotState", robotStatus.stateText || robotStatus.state || "대기 중");
  setText("robotLastUpdate", `마지막 업데이트 ${robotStatus.last_update_text || "-"}`);
  setText("robotConnectionText", robotStatus.connection?.label || "수신 대기");
  setText("robotUpdateTime", robotStatus.last_update_text || "-");

  updateConnectionBadge(robotStatus.connection);

  const jointValues = robotStatus.joint_values || [];
  jointValues.forEach(([label, value]) => {
    setText(`joint${label}`, value);
  });

  const poseValues = robotStatus.pose_values || [];
  poseValues.forEach(([label, value]) => {
    setText(`pose${label}`, value);
  });
}


function updatePreviewArea(targetIdList, imageUrl, altText, emptyText) {
  let currentElement = null;

  for (const id of targetIdList) {
    const found = document.getElementById(id);
    if (found) {
      currentElement = found;
      break;
    }
  }

  if (!currentElement) return;

  const parent = currentElement.parentElement;
  if (!parent) return;

  if (imageUrl) {
    parent.innerHTML = `
      <img
        id="${targetIdList[0]}"
        class="preview-image"
        src="${escapeHTML(imageUrl)}"
        alt="${escapeHTML(altText)}"
      />
    `;
  } else {
    parent.innerHTML = `
      <div id="${targetIdList[1]}" class="preview-placeholder">
        ${escapeHTML(emptyText)}
      </div>
    `;
  }
}


function updateCurrentJobDetailButton(jobId) {
  const currentLink = document.getElementById("currentJobDetailLink");
  const currentDisabled = document.getElementById("currentJobDetailDisabled");

  const validJobId = jobId && jobId !== "-";

  if (currentLink) {
    if (validJobId) {
      currentLink.href = `/admin/requests/${encodeURIComponent(jobId)}`;
      currentLink.textContent = "작업 상세 보기";
      currentLink.classList.remove("disabled-btn");
    } else {
      currentLink.removeAttribute("href");
      currentLink.textContent = "작업 상세 보기";
      currentLink.classList.add("disabled-btn");
    }
    return;
  }

  if (currentDisabled && validJobId) {
    const link = document.createElement("a");
    link.id = "currentJobDetailLink";
    link.className = "btn-primary link-button";
    link.href = `/admin/requests/${encodeURIComponent(jobId)}`;
    link.textContent = "작업 상세 보기";

    currentDisabled.replaceWith(link);
  }
}


function updateCurrentJob(currentJob) {
  if (!currentJob) return;

  const jobId = currentJob.id || "-";
  const statusText = currentJob.statusText || currentJob.status || "작업 없음";

  setText("currentJobStatus", statusText);
  setText("currentJobId", jobId);
  setText("currentCustomerName", currentJob.name || "-");
  setText("currentJobStep", currentJob.step || "0 / 5");
  setText("currentJobStartTime", currentJob.start_time || "-");

  setProgress(currentJob.progress);
  updateCurrentJobDetailButton(jobId);

  updatePreviewArea(
    ["currentOriginalImage", "currentOriginalImagePlaceholder"],
    currentJob.imageUrl,
    "원본 이미지",
    "이미지 미리보기 영역"
  );

  updatePreviewArea(
    ["currentConvertedImage", "currentConvertedImagePlaceholder"],
    currentJob.convertedImageUrl,
    "변환 이미지",
    "변환 이미지 미리보기 영역"
  );
}


function updateSummaryCards(summaryCards) {
  if (!Array.isArray(summaryCards)) return;

  const summaryGrid = document.querySelector(".summary-grid");
  if (!summaryGrid) return;

  const cards = summaryGrid.querySelectorAll(".card:not(.robot-status-card)");

  summaryCards.forEach((cardData, index) => {
    const card = cards[index];
    if (!card) return;

    const label = card.querySelector(".summary-label");
    const value = card.querySelector(".summary-value");
    const sub = card.querySelector(".summary-sub");

    if (label) label.textContent = cardData.label ?? "-";
    if (value) value.textContent = cardData.value ?? "0건";
    if (sub) sub.textContent = cardData.sub ?? "";
  });
}


function renderPendingRequests(pendingRequests) {
  const tbody = document.getElementById("pendingRequestsBody");
  if (!tbody) return;

  if (!Array.isArray(pendingRequests) || pendingRequests.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" class="empty-table-message">
          현재 승인 대기 요청이 없습니다.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = pendingRequests
    .map((request) => {
      const requestId = request.id ?? "-";
      const detailUrl = `/admin/requests/${encodeURIComponent(requestId)}`;

      return `
        <tr>
          <td class="request-id">${escapeHTML(requestId)}</td>
          <td>${escapeHTML(request.name)}</td>
          <td>${escapeHTML(request.option)}</td>
          <td>
            <span class="pending-badge">
              ${escapeHTML(request.status)}
            </span>
          </td>
          <td>${escapeHTML(request.time)}</td>
          <td>
            <a class="detail-btn link-button" href="${detailUrl}">
              상세보기
            </a>
          </td>
        </tr>
      `;
    })
    .join("");
}


async function fetchDashboardData() {
  try {
    const response = await fetch("/api/dashboard", {
      method: "GET",
      headers: {
        "Accept": "application/json",
      },
      cache: "no-store",
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const result = await response.json();

    if (!result.ok) {
      throw new Error("API returned ok=false");
    }

    const data = result.data;

    updateSummaryCards(data.summary_cards);
    updateRobotStatus(data.robot_status);
    updateCurrentJob(data.current_job);
    renderPendingRequests(data.pending_requests);

  } catch (error) {
    console.error("대시보드 데이터 갱신 실패:", error);

    const badge = document.getElementById("robotConnectionBadge");
    if (badge) {
      badge.textContent = "● 서버/API 오류";
      badge.classList.remove(
        "badge-online",
        "badge-delayed",
        "badge-offline",
        "badge-waiting"
      );
      badge.classList.add("badge-offline");
    }

    const liveBadge = document.getElementById("liveBadge");
    if (liveBadge) {
      liveBadge.textContent = "ERROR";
      liveBadge.classList.add("offline");
    }
  }
}


document.addEventListener("DOMContentLoaded", () => {
  const intervalMs = window.DASHBOARD_REFRESH_INTERVAL_MS || 1000;

  fetchDashboardData();

  setInterval(fetchDashboardData, intervalMs);
});