import { createRequire } from "node:module";
import { mkdir, readFile, readdir, stat } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { randomUUID } from "node:crypto";

const CHAT_URL = "https://www.zhipin.com/web/chat/index";
const MIN_PORT = 53470;
const MAX_PORT = 53569;

function normalize(value) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function normalizeJob(value) {
  return normalize(value).split(/\s+_\s+/, 1)[0].trim();
}

function requireText(value, label, maxLength) {
  const normalized = normalize(value);
  if (!normalized || normalized.length > maxLength || /[\r\n\0]/.test(String(value ?? ""))) {
    throw new Error(`${label}无效`);
  }
  return normalized;
}

async function readRequest() {
  let raw = "";
  for await (const chunk of process.stdin) raw += chunk;
  let request;
  try {
    request = JSON.parse(raw);
  } catch {
    throw new Error("Puppeteer 桥接请求不是有效 JSON");
  }
  if (!request || typeof request !== "object" || Array.isArray(request)) {
    throw new Error("Puppeteer 桥接请求无效");
  }
  return request;
}

async function loadPuppeteer(packageRoot) {
  const packageJsonPath = path.join(packageRoot, "package.json");
  const metadata = JSON.parse(await readFile(packageJsonPath, "utf8"));
  if (metadata.name !== "@joohw/boss-cli") {
    throw new Error("Puppeteer 桥接仅允许使用已配置的 @joohw/boss-cli");
  }
  const require = createRequire(packageJsonPath);
  const modulePath = require.resolve("puppeteer-core");
  const imported = await import(pathToFileURL(modulePath).href);
  return imported.default;
}

async function existingBossPage(browser) {
  const pages = (await browser.pages()).filter((page) => !page.isClosed());
  const page = [...pages].reverse().find((item) => item.url().startsWith("https://www.zhipin.com/"));
  if (!page) throw new Error("未找到已登录的 BOSS 页面");
  return page;
}

async function chatPage(browser) {
  let lastError;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const page = await existingBossPage(browser);
    try {
      if (!page.url().startsWith(CHAT_URL)) {
        await page.goto(CHAT_URL, { waitUntil: "domcontentloaded", timeout: 30_000 });
      }
      await page.waitForFunction(
        `Boolean(document.querySelector('.chat-top-job .chat-select-job'))
          && Boolean(document.querySelector('.chat-message-filter-left'))`,
        { timeout: 20_000 },
      );
      return page;
    } catch (error) {
      lastError = error;
      if (attempt === 2) throw error;
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  }
  throw lastError;
}

async function selectScope(page, jobTitle, unread) {
  const expectedJob = requireText(normalizeJob(jobTitle), "BOSS 沟通职位筛选值", 120);
  const currentJob = await page.$eval(
    ".chat-top-job .chat-select-job",
    (element) => (element.textContent ?? "").replace(/\s+/g, " ").trim().split(/\s+_\s+/, 1)[0].trim(),
  );
  if (currentJob !== expectedJob) {
    const opened = await page.evaluate(() => {
      const matches = Array.from(document.querySelectorAll(".chat-top-job .chat-select-job"));
      if (matches.length !== 1) return false;
      matches[0].click();
      return true;
    });
    if (!opened) throw new Error("未找到 BOSS 沟通职位筛选器");
    await page.waitForFunction(
      `document.querySelectorAll('.chat-top-job .ui-dropmenu-list li').length > 0`,
      { timeout: 10_000 },
    );
    const selected = await page.evaluate((expected) => {
      const items = Array.from(document.querySelectorAll(".chat-top-job .ui-dropmenu-list li"));
      const matches = items.filter((item) => (item.textContent ?? "")
        .replace(/\s+/g, " ").trim().split(/\s+_\s+/, 1)[0].trim() === expected);
      if (matches.length !== 1) return false;
      matches[0].click();
      return true;
    }, expectedJob);
    if (!selected) throw new Error("BOSS 沟通职位无法精确唯一匹配");
    await page.waitForFunction(
      `(expected) => {
        const value = (document.querySelector('.chat-top-job .chat-select-job')?.textContent ?? '')
          .replace(/\\s+/g, ' ').trim().split(/\\s+_\\s+/, 1)[0].trim();
        return value === expected;
      }`,
      { timeout: 15_000 },
      expectedJob,
    );
    // BOSS updates the dropdown label before its SPA request and conversation
    // frame have settled.  Clicking the unread tab during that transition can
    // detach the old frame and close the managed browser.  Wait until every
    // visible row belongs to the selected job (or the scoped empty state is
    // stable) before applying the second filter.
    await new Promise((resolve) => setTimeout(resolve, 900));
    await page.waitForFunction(
      `(expected) => {
        const norm = (value) => (value ?? '').replace(/\\s+/g, ' ').trim();
        const rows = Array.from(document.querySelectorAll('.geek-item'));
        if (rows.length) {
          window.__ximingJobScopeEmpty = null;
          return rows.every((row) => norm(row.querySelector('.source-job')?.textContent) === expected);
        }
        const now = Date.now();
        const previous = window.__ximingJobScopeEmpty;
        if (previous?.job === expected && now - previous.since >= 1000) return true;
        window.__ximingJobScopeEmpty = { job: expected, since: now };
        return false;
      }`,
      { timeout: 18_000 },
      expectedJob,
    );
  }

  const filterLabel = unread ? "未读" : "全部";
  await page.waitForFunction(
    `(expected) => {
      const container = document.querySelector('.chat-message-filter-left');
      if (!container) return false;
      const labels = Array.from(container.querySelectorAll('span'))
        .map((item) => (item.textContent ?? '').replace(/\\s+/g, ''));
      return labels.length >= 2 && labels.some((label) => label.includes(expected));
    }`,
    { timeout: 15_000 },
    filterLabel,
  );
  let filterApplied = false;
  for (let attempt = 0; attempt < 5 && !filterApplied; attempt += 1) {
    try {
      filterApplied = await page.evaluate((expected) => {
        const items = Array.from(document.querySelectorAll(".chat-message-filter-left span"));
        const matches = items.filter((item) => (item.textContent ?? "")
          .replace(/\s+/g, "").includes(expected));
        if (matches.length !== 1) return false;
        const tab = matches[0];
        const selected = /(active|selected|current|checked)/.test(String(tab.className ?? ""))
          || tab.getAttribute("aria-selected") === "true"
          || Boolean(tab.closest(".active, .selected, .current, .checked"));
        if (!selected) {
          tab.click();
        }
        return true;
      }, filterLabel);
    } catch (error) {
      if (!/detached|context|navigation/i.test(String(error)) || attempt === 4) throw error;
    }
    if (!filterApplied) await new Promise((resolve) => setTimeout(resolve, 300));
  }
  if (!filterApplied) throw new Error(`未找到 BOSS 沟通“${filterLabel}”筛选`);
  await new Promise((resolve) => setTimeout(resolve, 750));
  await page.waitForFunction(
    `(scope) => {
      const norm = (value) => (value ?? '').replace(/\\s+/g, ' ').trim();
      const tabs = Array.from(document.querySelectorAll('.chat-message-filter-left span'));
      const tab = tabs.find((item) => norm(item.textContent).replace(/\s+/g, '').includes(scope.filter));
      const selected = tab && (
        /(active|selected|current|checked)/.test(String(tab.className ?? ''))
        || tab.getAttribute('aria-selected') === 'true'
        || Boolean(tab.closest('.active, .selected, .current, .checked'))
      );
      if (!selected) return false;
      const rows = Array.from(document.querySelectorAll('.geek-item'));
      if (!rows.length) {
        const key = scope.job + ':' + scope.filter;
        const now = Date.now();
        const previous = window.__ximingConversationEmptyScope;
        if (previous?.key === key && now - previous.since >= 1000) return true;
        window.__ximingConversationEmptyScope = { key, since: now };
        return false;
      }
      window.__ximingConversationEmptyScope = null;
      return rows.every((row) => {
        const job = norm(row.querySelector('.source-job')?.textContent);
        const badge = norm(row.querySelector('.badge-count')?.textContent).replace(/\D/g, '');
        return job === scope.job && (!scope.unread || Number.parseInt(badge || '0', 10) > 0);
      });
    }`,
    { timeout: 18_000 },
    { job: expectedJob, filter: filterLabel, unread: Boolean(unread) },
  );
  return expectedJob;
}

async function conversationRows(page) {
  return page.$$eval(".geek-item", (items) => {
    const norm = (value) => (value ?? "").replace(/\s+/g, " ").trim();
    return items.map((element, index) => {
      const badge = norm(element.querySelector(".badge-count")?.textContent);
      const digits = badge.replace(/\D/g, "");
      return {
        index: index + 1,
        external_id: norm(element.getAttribute("data-id")),
        name: norm(element.querySelector(".geek-name")?.textContent),
        job_title: norm(element.querySelector(".source-job")?.textContent),
        preview: norm(element.querySelector(".push-text")?.textContent),
        unread_count: digits ? (Number.parseInt(digits, 10) || 0) : 0,
        selected: element.classList.contains("selected"),
      };
    }).filter((row) => row.external_id && row.name);
  });
}

async function currentMessages(page) {
  return page.$$eval(".chat-message-list", (lists) => {
    const norm = (value) => (value ?? "").replace(/\s+/g, " ").trim();
    const visible = lists.filter((element) => {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    });
    const list = visible[visible.length - 1];
    if (!list) return [];
    let currentTime = "";
    const messages = [];
    for (const item of list.querySelectorAll(".message-item")) {
      const time = norm(item.querySelector(".message-time .time")?.textContent);
      if (time) currentTime = time;
      const friend = item.matches(".item-friend") ? item : item.querySelector(".item-friend");
      const mine = item.matches(".item-myself") ? item : item.querySelector(".item-myself");
      const system = item.matches(".item-system") ? item : item.querySelector(".item-system");
      let direction = "";
      let content = "";
      if (friend) {
        direction = "candidate";
        content = norm(friend.querySelector(".text-content")?.textContent)
          || norm(friend.querySelector(".text > span")?.textContent)
          || norm(friend.querySelector(".message-card-top-title")?.textContent)
          || norm(friend.querySelector(".text")?.textContent);
      } else if (mine) {
        direction = "hr";
        content = norm(mine.querySelector(".text-content")?.textContent)
          || norm(mine.querySelector(".text span")?.textContent)
          || norm(mine.querySelector(".text")?.textContent);
      } else if (system) {
        direction = "system";
        content = norm(system.querySelector(".message-card-top-title")?.textContent)
          || norm(system.querySelector(".text span")?.textContent);
      }
      if (direction && content) messages.push({ direction, content, sent_at: currentTime });
    }
    return messages;
  });
}

async function selectedConversation(page) {
  return page.evaluate(() => {
    const norm = (value) => (value ?? "").replace(/\s+/g, " ").trim();
    const selected = document.querySelector(".geek-item.selected");
    if (!selected) return null;
    return {
      external_id: norm(selected.getAttribute("data-id")),
      name: norm(selected.querySelector(".geek-name")?.textContent),
      job_title: norm(selected.querySelector(".source-job")?.textContent),
      detail_name: norm(document.querySelector(".base-info-single-container .name-box")?.textContent),
      editor_ready: Boolean(document.querySelector("#boss-chat-editor-input")),
    };
  });
}

function assertUniqueIds(rows) {
  const ids = rows.map((row) => row.external_id);
  if (ids.length !== new Set(ids).size) throw new Error("BOSS 沟通列表存在重复稳定 ID");
}

async function openConversation(page, request) {
  const externalId = requireText(request.external_id, "候选人平台稳定 ID", 160);
  const expectedJob = await selectScope(page, request.job_title, Boolean(request.unread));
  const rows = await conversationRows(page);
  assertUniqueIds(rows);
  const matches = rows.filter((row) => row.external_id === externalId && row.job_title === expectedJob);
  if (matches.length !== 1) throw new Error("所选职位范围内无法唯一定位批准的 BOSS 会话");
  const target = matches[0];
  const current = await selectedConversation(page);
  const alreadyOpen = current
    && current.external_id === externalId
    && current.name === target.name
    && current.job_title === expectedJob
    && current.detail_name === target.name
    && current.editor_ready;
  if (!alreadyOpen) {
    const handles = await page.$$(".geek-item");
    await handles[target.index - 1].click();
  }
  await page.waitForFunction(
    `(target) => {
      const norm = (value) => (value ?? '').replace(/\\s+/g, ' ').trim();
      const selected = document.querySelector('.geek-item.selected');
      return norm(selected?.getAttribute('data-id')) === target.externalId
        && norm(selected?.querySelector('.geek-name')?.textContent) === target.name
        && norm(selected?.querySelector('.source-job')?.textContent) === target.jobTitle
        && norm(document.querySelector('.base-info-single-container .name-box')?.textContent) === target.name
        && Boolean(document.querySelector('#boss-chat-editor-input'));
    }`,
    { timeout: 15_000 },
    { externalId, name: target.name, jobTitle: expectedJob },
  );
  await page.waitForFunction(
    `Array.from(document.querySelectorAll('.chat-message-list')).some((element) => {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
    })`,
    { timeout: 15_000 },
  );
  await page.waitForFunction(
    `(externalId) => {
      const lists = Array.from(document.querySelectorAll('.chat-message-list')).filter((element) => {
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      });
      const list = lists[lists.length - 1];
      if (!list) return false;
      const count = list.querySelectorAll('.message-item').length;
      const key = externalId + ':' + count;
      const now = Date.now();
      const previous = window.__ximingMessageListStable;
      if (previous?.key === key && now - previous.since >= (count > 0 ? 500 : 5000)) return true;
      window.__ximingMessageListStable = { key, since: now };
      return false;
    }`,
    { timeout: 15_000 },
    externalId,
  );
  return { ...target, selected: true, messages: await currentMessages(page) };
}

async function verifySelected(page, request) {
  const externalId = requireText(request.external_id, "候选人平台稳定 ID", 160);
  const expectedJob = requireText(normalizeJob(request.job_title), "BOSS 沟通职位", 120);
  const selected = await selectedConversation(page);
  if (!selected
      || selected.external_id !== externalId
      || selected.job_title !== expectedJob
      || selected.name !== selected.detail_name
      || !selected.editor_ready) {
    throw new Error("打开后的 BOSS 会话身份与批准目标不一致");
  }
  return selected;
}

async function waitForOutgoing(page, request) {
  const externalId = requireText(request.external_id, "候选人平台稳定 ID", 160);
  const expectedJob = requireText(normalizeJob(request.job_title), "BOSS 沟通职位", 120);
  const message = requireText(request.message, "发送回执消息", 1000);
  const previousCount = Number.parseInt(request.previous_count, 10);
  if (!Number.isInteger(previousCount) || previousCount < 0) throw new Error("发送回执基线无效");
  await page.waitForFunction(
    `(expected) => {
      const norm = (value) => (value ?? '').replace(/\\s+/g, ' ').trim();
      const selected = document.querySelector('.geek-item.selected');
      if (norm(selected?.getAttribute('data-id')) !== expected.externalId) return false;
      if (norm(selected?.querySelector('.source-job')?.textContent) !== expected.jobTitle) return false;
      const lists = Array.from(document.querySelectorAll('.chat-message-list')).filter((element) => {
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      });
      const list = lists[lists.length - 1];
      if (!list) return false;
      const messages = Array.from(list.querySelectorAll('.message-item.item-myself, .message-item .item-myself')).map((item) =>
        norm(item.querySelector('.text-content')?.textContent)
          || norm(item.querySelector('.text')?.textContent)
          || norm(item.textContent)
      );
      return messages.filter((value) => value === expected.message).length > expected.previousCount;
    }`,
    { timeout: 15_000 },
    { externalId, jobTitle: expectedJob, message, previousCount },
  );
  return { ...(await verifySelected(page, request)), sent: true, verified: true };
}

async function sendText(page, request) {
  await verifySelected(page, request);
  const message = requireText(request.message, "发送内容", 1000);
  const previousCount = Number.parseInt(request.previous_count, 10);
  if (!Number.isInteger(previousCount) || previousCount < 0) throw new Error("发送回执基线无效");
  const editor = await page.$("#boss-chat-editor-input");
  if (!editor) throw new Error("未找到 BOSS 聊天输入框");
  await editor.click();
  await page.keyboard.down("Control");
  await page.keyboard.press("KeyA");
  await page.keyboard.up("Control");
  await page.keyboard.press("Backspace");
  await editor.type(message, { delay: 35 });
  await page.keyboard.press("Enter");
  const receipt = await waitForOutgoing(page, {
    ...request,
    message,
    previous_count: previousCount,
  });
  return receipt;
}

async function requestResume(page, request) {
  await verifySelected(page, request);
  const modalAlreadyOpen = await page.evaluate(() => {
    const visible = (element) => {
      if (!(element instanceof HTMLElement)) return false;
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    };
    const norm = (value) => (value ?? "").replace(/\s+/g, "").trim();
    return Array.from(document.querySelectorAll(".exchange-tooltip"))
      .some((tip) => visible(tip) && norm(tip.textContent).includes("索取简历"));
  });
  const availability = modalAlreadyOpen ? { found: true, available: true } : await page.evaluate(() => {
    const norm = (value) => (value ?? "").replace(/\s+/g, "").trim();
    const items = Array.from(document.querySelectorAll(
      ".operate-exchange-left .operate-icon-item, .operate-icon-item",
    ));
    const matches = items.filter((item) => norm(item.querySelector(".operate-btn")?.textContent)
      .includes("求简历"));
    if (matches.length !== 1) return { found: false, available: false };
    const target = matches[0];
    const button = target.querySelector(".operate-btn");
    const className = `${String(target.className ?? "")} ${String(button?.className ?? "")}`;
    const disabled = /disabled|forbid|ban/i.test(className)
      || button?.getAttribute("disabled") !== null;
    if (!disabled) (button instanceof HTMLElement ? button : target).click();
    return { found: true, available: !disabled };
  });
  if (!availability.found) throw new Error("未找到 BOSS“求简历”按钮");
  if (!availability.available) throw new Error("当前 BOSS“求简历”按钮不可用");
  await page.waitForFunction(
    `() => {
      const visible = (element) => {
        if (!(element instanceof HTMLElement)) return false;
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      };
      const norm = (value) => (value ?? '').replace(/\\s+/g, '').trim();
      return Array.from(document.querySelectorAll('.exchange-tooltip')).some((tip) =>
        visible(tip) && norm(tip.textContent).includes('索取简历')
          && Boolean(tip.querySelector('.btn-box .boss-btn-primary'))
      );
    }`,
    { timeout: 12_000 },
  );
  const tips = await page.$$(".exchange-tooltip");
  let confirmButton = null;
  for (const tip of tips) {
    const matches = await tip.evaluate((element) => {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      const norm = (value) => (value ?? "").replace(/\s+/g, "").trim();
      return style.display !== "none" && style.visibility !== "hidden"
        && rect.width > 0 && rect.height > 0 && norm(element.textContent).includes("索取简历");
    });
    if (!matches) continue;
    const candidates = await tip.$$(".btn-box .boss-btn-primary");
    if (candidates.length === 1) {
      const candidate = candidates[0];
      confirmButton = candidate;
      break;
    }
  }
  if (!confirmButton) throw new Error("BOSS 求简历确认弹窗未能确认");
  const responseTasks = [];
  const onResponse = (response) => {
    if (response.request().method() !== "POST") return;
    try {
      const pathName = new URL(response.url()).pathname;
      responseTasks.push((async () => {
        const body = await response.json().catch(() => null);
        return {
          path: pathName,
          status: response.status(),
          code: body && Object.hasOwn(body, "code") ? body.code : null,
        };
      })());
    } catch {
      // Ignore malformed browser resource URLs.
    }
  };
  page.on("response", onResponse);
  await page.evaluate(() => {
    window.__ximingResumeSignals = [];
    window.__ximingResumeObserver?.disconnect();
    window.__ximingResumeObserver = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          const text = (node.textContent ?? "").replace(/\s+/g, " ").trim();
          if (text && text.length <= 100 && /简历|成功|已发送|已发出|失败|错误|频繁/.test(text)) {
            window.__ximingResumeSignals.push(text);
          }
        }
      }
    });
    window.__ximingResumeObserver.observe(document.body, { childList: true, subtree: true });
  });
  await confirmButton.click();
  await new Promise((resolve) => setTimeout(resolve, 3000));
  page.off("response", onResponse);
  const observedResponses = await Promise.all(responseTasks);
  const signals = await page.evaluate(() => {
    window.__ximingResumeObserver?.disconnect();
    return Array.from(new Set(window.__ximingResumeSignals ?? []));
  });
  const negativeSignal = signals.find((text) => /失败|错误|频繁/.test(text));
  if (negativeSignal) throw new Error(`BOSS 求简历失败：${negativeSignal}`);
  const positiveSignal = signals.find((text) => /成功|已发送|已发出/.test(text));
  const nativeResponses = observedResponses.filter((item) => item.path === "/wapi/zpchat/exchange/test");
  const failedResponse = nativeResponses.find((item) =>
    item.status < 200 || item.status >= 300 || (item.code !== null && ![0, "0"].includes(item.code)));
  if (failedResponse) throw new Error("BOSS 求简历接口返回失败");
  const acknowledgement = nativeResponses.find((item) =>
    item.status >= 200 && item.status < 300 && (item.code === null || [0, "0"].includes(item.code)));
  if (!positiveSignal && !acknowledgement) {
    const observed = observedResponses.map((item) => `${item.path}:${item.status}`).join(",") || "none";
    throw new Error(`BOSS 求简历未返回可验证回执（POST=${observed}）`);
  }
  await page.waitForFunction(
    `() => {
      const visible = (element) => {
        if (!(element instanceof HTMLElement)) return false;
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      };
      const norm = (value) => (value ?? '').replace(/\\s+/g, '').trim();
      const modalOpen = Array.from(document.querySelectorAll('.exchange-tooltip'))
        .some((tip) => visible(tip) && norm(tip.textContent).includes('索取简历'));
      return !modalOpen;
    }`,
    { timeout: 12_000 },
  );
  return {
    ...(await verifySelected(page, request)),
    resume_requested: true,
    request_acknowledged: true,
    response_status: acknowledgement?.status ?? 0,
    response_path: acknowledgement?.path ?? "ui-signal",
    verified: true,
  };
}

async function waitForDownloadedPdf(directory, previousNames, timeoutMs) {
  const started = Date.now();
  let lastCandidate = "";
  let lastSize = -1;
  let stableSince = 0;
  while (Date.now() - started < timeoutMs) {
    const names = await readdir(directory);
    const candidates = names.filter((name) => name.toLowerCase().endsWith(".pdf") && !previousNames.has(name));
    if (candidates.length) {
      const filename = candidates[candidates.length - 1];
      const details = await stat(path.join(directory, filename));
      if (filename === lastCandidate && details.size === lastSize && details.size > 0) {
        if (!stableSince) stableSince = Date.now();
        if (Date.now() - stableSince >= 500) return filename;
      } else {
        lastCandidate = filename;
        lastSize = details.size;
        stableSince = 0;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error("等待 BOSS 简历附件下载超时");
}

async function downloadAttachments(page, browser, request) {
  const selected = await verifySelected(page, request);
  const expectedName = requireText(request.expected_name, "候选人名称", 100);
  if (selected.name !== expectedName) throw new Error("沟通会话候选人名称复核失败，已禁止读取附件");
  const outputRoot = path.resolve(requireText(request.output_dir, "简历附件目录", 1000));
  const directory = path.join(outputRoot, `bridge-${randomUUID()}`);
  await mkdir(directory, { recursive: true });
  const session = await page.createCDPSession();
  await session.send("Browser.setDownloadBehavior", {
    behavior: "allow",
    downloadPath: directory,
    eventsEnabled: true,
  });
  const visibleList = await page.evaluateHandle(() => {
    const lists = Array.from(document.querySelectorAll(".chat-message-list")).filter((element) => {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    });
    return lists[lists.length - 1] ?? null;
  });
  const visibleListElement = visibleList.asElement();
  if (!visibleListElement) throw new Error("未找到当前 BOSS 聊天消息区");
  const cards = await visibleListElement.$$(
    ".message-item.item-friend .resume-icon, .message-item .item-friend .resume-icon",
  );
  const downloaded = [];
  for (const card of cards.slice(0, 10)) {
    const messageItem = await card.evaluateHandle((element) => element.closest(".message-item"));
    const button = await messageItem.asElement()?.$(".message-card-buttons .card-btn");
    if (!button) continue;
    const previousNames = new Set(await readdir(directory));
    await button.click();
    try {
      const filename = await waitForDownloadedPdf(directory, previousNames, 8_000);
      const filePath = path.join(directory, filename);
      const details = await stat(filePath);
      downloaded.push({ path: filePath, filename: path.basename(filename), file_size: details.size });
    } catch {
      // A non-download card or an already unavailable attachment is skipped;
      // the caller can continue polling for a later candidate response.
    }
  }
  await session.detach().catch(() => {});
  return downloaded;
}

const CANDIDATE_SOURCES = {
  recommend: {
    pagePath: "/web/chat/recommend",
    frameName: "recommendFrame",
    framePath: "/web/frame/recommend",
    cardSelector: ".candidate-card-wrap, .card-list .card-item, .geek-list .geek-card",
    nameSelector: ".name-wrap .name, .name",
    actionSelector: ".button-chat-wrap .btn.btn-greet",
  },
  search: {
    pagePath: "/web/chat/search",
    frameName: "searchFrame",
    framePath: "/web/frame/search",
    cardSelector: ".geek-info-card",
    nameSelector: ".name-label",
    actionSelector: ".btn-getcontact",
  },
  deep_search: {
    pagePath: "/web/chat/aiform",
    frameName: "",
    framePath: "",
    cardSelector: ".geeks-box .geek-card-item, .geek-card-list .geek-card-item",
    nameSelector: ".geek-name",
    actionSelector: ".geek-chat .btn-ai-v2, .geek-chat span[class*='btn-ai']",
  },
};

function candidateSource(request) {
  const source = normalize(request.source || "recommend");
  const config = CANDIDATE_SOURCES[source];
  if (!config) throw new Error("候选人复核来源无效");
  return { source, config };
}

async function candidateContext(page, request) {
  const { source, config } = candidateSource(request);
  const currentPath = new URL(page.url()).pathname.replace(/\/+$/, "");
  if (currentPath !== config.pagePath) {
    throw new Error(`当前 BOSS 页面与候选人复核来源不一致：${source}`);
  }
  if (!config.frameName) return { source, config, context: page };
  const iframe = await page.waitForSelector(`iframe[name="${config.frameName}"]`, { timeout: 15_000 });
  const context = await iframe?.contentFrame();
  if (!context || !new URL(context.url()).pathname.startsWith(config.framePath)) {
    throw new Error("候选人列表 iframe 尚未就绪");
  }
  return { source, config, context };
}

async function candidateRowsFromContext(context, config) {
  return context.$$eval(config.cardSelector, (cards, selectors) => {
    const norm = (value) => (value ?? "").replace(/\s+/g, " ").trim();
    const stableId = (card) => {
      const preferred = card.querySelector(".card-inner[data-geekid], .card-inner[data-geek], [data-geekid], [data-geek]");
      const holder = preferred || card;
      return norm(holder.getAttribute("data-geekid")
        || holder.getAttribute("data-geek"));
    };
    return cards.map((card, index) => {
      const action = card.querySelector(selectors.action);
      return {
        index: index + 1,
        display_name: norm(card.querySelector(selectors.name)?.textContent),
        external_id: stableId(card),
        action_label: norm(action?.textContent),
        action_disabled: !action
          || /disabled|forbid|ban/i.test(String(action.className ?? ""))
          || action.getAttribute("disabled") !== null,
      };
    }).filter((row) => row.display_name);
  }, { name: config.nameSelector, action: config.actionSelector });
}

async function listCandidateRows(page, request) {
  const { config, context } = await candidateContext(page, request);
  return candidateRowsFromContext(context, config);
}

async function greetCandidate(page, request) {
  const externalId = requireText(request.external_id, "候选人平台稳定 ID", 160);
  const expectedName = requireText(request.expected_name, "候选人名称", 100);
  requireText(request.message, "统一打招呼话术", 1000);
  const { source, config, context } = await candidateContext(page, request);
  const before = await candidateRowsFromContext(context, config);
  const matches = before.filter((row) => row.external_id === externalId && row.display_name === expectedName);
  if (matches.length !== 1) throw new Error("刷新后无法按稳定 ID 唯一确认候选人");

  const responseTasks = [];
  const onResponse = (response) => {
    if (response.request().method() !== "POST") return;
    try {
      const url = new URL(response.url());
      if (!url.hostname.endsWith("zhipin.com") || !url.pathname.startsWith("/wapi/")) return;
      responseTasks.push((async () => {
        const body = await response.json().catch(() => null);
        return { path: url.pathname, status: response.status(), code: body?.code ?? null };
      })());
    } catch {
      // Ignore malformed browser resource URLs.
    }
  };
  page.on("response", onResponse);
  const clicked = await context.evaluate((expected, selectors) => {
    const norm = (value) => (value ?? "").replace(/\s+/g, " ").trim();
    const stableId = (card) => {
      const preferred = card.querySelector(".card-inner[data-geekid], .card-inner[data-geek], [data-geekid], [data-geek]");
      const holder = preferred || card;
      return norm(holder.getAttribute("data-geekid")
        || holder.getAttribute("data-geek"));
    };
    const cards = Array.from(document.querySelectorAll(selectors.card));
    const matches = cards.filter((card) => stableId(card) === expected.externalId
      && norm(card.querySelector(selectors.name)?.textContent) === expected.name);
    if (matches.length !== 1) return false;
    const button = matches[0].querySelector(selectors.action);
    if (!(button instanceof HTMLElement)) return false;
    const label = norm(button.textContent);
    const disabled = /disabled|forbid|ban/i.test(String(button.className ?? ""))
      || button.getAttribute("disabled") !== null;
    if (disabled || (!label.includes("打招呼") && !label.includes("沟通"))) return false;
    button.scrollIntoView({ block: "center", inline: "nearest" });
    button.click();
    return true;
  }, { externalId, name: expectedName }, {
    card: config.cardSelector,
    name: config.nameSelector,
    action: config.actionSelector,
  });
  if (!clicked) {
    page.off("response", onResponse);
    throw new Error("稳定 ID 对应候选人的打招呼按钮不可用");
  }
  await new Promise((resolve) => setTimeout(resolve, 2500));
  page.off("response", onResponse);
  const responses = await Promise.all(responseTasks);
  const acknowledged = responses.some((item) => item.status >= 200 && item.status < 300
    && (item.code === null || item.code === 0 || item.code === "0"));
  const after = await candidateRowsFromContext(context, config);
  const observed = after.find((row) => row.external_id === externalId && row.display_name === expectedName);
  const uiConfirmed = !observed
    || /继续沟通|已打招呼|已沟通/.test(observed.action_label)
    || observed.action_disabled;
  if (!acknowledged || !uiConfirmed) {
    throw new Error("BOSS 打招呼未返回可验证回执");
  }
  return {
    verified: true,
    greeting_verified: true,
    source,
    target_name: expectedName,
    expected_external_id: externalId,
    observed_external_id: externalId,
    response_path: responses.find((item) => item.status >= 200 && item.status < 300)?.path || "",
  };
}

async function execute(page, browser, request) {
  switch (request.operation) {
    case "candidate_list":
      return { rows: await listCandidateRows(page, request) };
    case "greet_candidate":
      return { receipt: await greetCandidate(page, request) };
    case "list": {
      if (request.job_title) await selectScope(page, request.job_title, Boolean(request.unread));
      const rows = await conversationRows(page);
      assertUniqueIds(rows);
      return { rows };
    }
    case "open":
      return { conversation: await openConversation(page, request) };
    case "selected":
      return { conversation: await verifySelected(page, request) };
    case "wait_outgoing":
      return { receipt: await waitForOutgoing(page, request) };
    case "send_text":
      return { receipt: await sendText(page, request) };
    case "request_resume": {
      let greeting = null;
      if (request.first_contact) greeting = await sendText(page, request);
      const requested = await requestResume(page, request);
      return {
        receipt: {
          ...requested,
          greeting_verified: request.first_contact ? greeting?.verified === true : true,
          resume_requested: true,
          expected_external_id: String(request.external_id ?? ""),
          observed_external_id: String(requested.external_id ?? ""),
        },
      };
    }
    case "download_attachments":
      return { attachments: await downloadAttachments(page, browser, request) };
    default:
      throw new Error("不支持的 Puppeteer 桥接操作");
  }
}

let browser;
try {
  const packageRoot = path.resolve(process.argv[2] ?? "");
  const request = await readRequest();
  const port = Number.parseInt(request.port, 10);
  if (!Number.isInteger(port) || port < MIN_PORT || port > MAX_PORT) {
    throw new Error("浏览器调试端口不在系统管理范围内");
  }
  const puppeteer = await loadPuppeteer(packageRoot);
  browser = await puppeteer.connect({
    browserURL: `http://127.0.0.1:${port}`,
    defaultViewport: null,
    protocolTimeout: 30_000,
  });
  if (request.operation === "ping") {
    process.stdout.write(JSON.stringify({ ok: true, connected: true }));
    process.exitCode = 0;
  } else {
    const page = ["candidate_list", "greet_candidate"].includes(request.operation)
      ? await existingBossPage(browser)
      : await chatPage(browser);
    const result = await execute(page, browser, request);
    process.stdout.write(JSON.stringify({ ok: true, ...result }));
  }
} catch (error) {
  process.stderr.write(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
} finally {
  if (browser) {
    try {
      browser.disconnect();
    } catch {
      // Never call browser.close(): this process only borrows the managed CDP session.
    }
  }
}
