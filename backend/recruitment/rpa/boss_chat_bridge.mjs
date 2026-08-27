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
  const page = await existingBossPage(browser);
  if (!page.url().startsWith(CHAT_URL)) {
    await page.goto(CHAT_URL, { waitUntil: "domcontentloaded", timeout: 30_000 });
  }
  await page.waitForSelector(".chat-top-job .chat-select-job", { timeout: 15_000 });
  await page.waitForSelector(".chat-message-filter-left", { timeout: 15_000 });
  return page;
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
      matches[0].dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
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
      matches[0].dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
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
          tab.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
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
      const friend = item.querySelector(".item-friend");
      const mine = item.querySelector(".item-myself");
      const system = item.querySelector(".item-system");
      let direction = "";
      let content = "";
      if (friend) {
        direction = "candidate";
        content = norm(friend.querySelector(".text > span")?.textContent)
          || norm(friend.querySelector(".message-card-top-title")?.textContent)
          || norm(friend.querySelector(".text")?.textContent);
      } else if (mine) {
        direction = "hr";
        content = norm(mine.querySelector(".text span")?.textContent)
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
  const handles = await page.$$(".geek-item");
  await handles[target.index - 1].click();
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
      const messages = Array.from(list.querySelectorAll(
        '.message-item .item-myself .text span'
      )).map((item) => norm(item.textContent));
      return messages.filter((value) => value === expected.message).length > expected.previousCount;
    }`,
    { timeout: 15_000 },
    { externalId, jobTitle: expectedJob, message, previousCount },
  );
  return { ...(await verifySelected(page, request)), sent: true, verified: true };
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
  const cards = await visibleListElement.$$(".message-item .item-friend .resume-icon");
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

async function execute(page, browser, request) {
  switch (request.operation) {
    case "diagnostic_click_job_filter": {
      await page.click(".chat-top-job .chat-select-job");
      await page.waitForFunction(
        `document.querySelectorAll('.chat-top-job .ui-dropmenu-list li').length > 0`,
        { timeout: 10_000 },
      );
      const optionCount = await page.$$eval(
        ".chat-top-job .ui-dropmenu-list li",
        (items) => items.length,
      );
      return { option_count: optionCount };
    }
    case "diagnostic_select_job": {
      const expectedJob = requireText(normalizeJob(request.job_title), "BOSS 沟通职位筛选值", 120);
      const options = await page.$$(".chat-top-job .ui-dropmenu-list li");
      const optionTitles = await page.$$eval(
        ".chat-top-job .ui-dropmenu-list li",
        (items) => items.map((item) => (item.textContent ?? "").replace(/\s+/g, " ").trim().split(/\s+_\s+/, 1)[0].trim()),
      );
      const matchingIndexes = optionTitles
        .map((title, index) => ({ title, index }))
        .filter((item) => item.title === expectedJob)
        .map((item) => item.index);
      if (matchingIndexes.length !== 1) throw new Error("BOSS 沟通职位无法精确唯一匹配");
      await options[matchingIndexes[0]].click();
      await page.waitForFunction(
        `(expected) => {
          const value = (document.querySelector('.chat-top-job .chat-select-job')?.textContent ?? '')
            .replace(/\\s+/g, ' ').trim().split(/\\s+_\\s+/, 1)[0].trim();
          return value === expected;
        }`,
        { timeout: 15_000 },
        expectedJob,
      );
      return { selected_job: expectedJob };
    }
    case "diagnostic_select_unread": {
      const tabs = await page.$$(".chat-message-filter-left span");
      const tabLabels = await page.$$eval(
        ".chat-message-filter-left span",
        (items) => items.map((item) => (item.textContent ?? "").replace(/\s+/g, " ").trim()),
      );
      const matchingIndexes = tabLabels
        .map((label, index) => ({ label, index }))
        .filter((item) => item.label === "未读")
        .map((item) => item.index);
      if (matchingIndexes.length !== 1) throw new Error("未找到 BOSS 沟通“未读”筛选");
      await tabs[matchingIndexes[0]].click();
      await page.waitForFunction(
        `() => {
          const norm = (value) => (value ?? '').replace(/\\s+/g, ' ').trim();
          const tabs = Array.from(document.querySelectorAll('.chat-message-filter-left span'));
          const tab = tabs.find((item) => norm(item.textContent) === '未读');
          return Boolean(tab && /(active|selected|current|checked)/.test(String(tab.className ?? '')));
        }`,
        { timeout: 10_000 },
      );
      return { unread_selected: true };
    }
    case "diagnostic_filter_match": {
      const expected = request.unread ? "未读" : "全部";
      const matches = await page.$$eval(
        ".chat-message-filter-left span",
        (items, label) => items.map((item, index) => ({
          index,
          text: (item.textContent ?? "").replace(/\s+/g, " ").trim(),
          matches: (item.textContent ?? "").replace(/\s+/g, "").includes(label),
        })),
        expected,
      );
      return { expected, matches };
    }
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
  } else if (request.operation === "inspect_page") {
    const page = await existingBossPage(browser);
    const snapshot = await page.evaluate(() => ({
      url: window.location.href,
      title: document.title,
      job_filter_count: document.querySelectorAll(".chat-top-job .chat-select-job").length,
      message_filter_count: document.querySelectorAll(".chat-message-filter-left").length,
      conversation_count: document.querySelectorAll(".geek-item").length,
      filter_labels: Array.from(document.querySelectorAll(".chat-message-filter-left span"))
        .map((element) => (element.textContent ?? "").replace(/\s+/g, " ").trim()),
      filter_nodes: Array.from(document.querySelectorAll(".chat-message-filter-left span"))
        .map((element) => ({
          label: (element.textContent ?? "").replace(/\s+/g, " ").trim(),
          class_name: String(element.className ?? ""),
          child_span_count: element.querySelectorAll("span").length,
        })),
      current_job: (document.querySelector(".chat-top-job .chat-select-job")?.textContent ?? "")
        .replace(/\s+/g, " ").trim(),
    }));
    process.stdout.write(JSON.stringify({ ok: true, snapshot }));
  } else {
    const page = await chatPage(browser);
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
