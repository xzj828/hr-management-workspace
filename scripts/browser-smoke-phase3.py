from pathlib import Path
from tempfile import gettempdir

from playwright.sync_api import sync_playwright


errors = []
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 1000})
    page.on("console", lambda message: errors.append(f"console:{message.text}") if message.type == "error" else None)
    page.on("pageerror", lambda error: errors.append(f"page:{error}"))
    page.on("response", lambda response: errors.append(f"http:{response.status}:{response.url}") if response.status >= 400 else None)

    page.goto("http://127.0.0.1:8011/login")
    page.wait_for_load_state("networkidle")
    page.locator('input[autocomplete="username"]').fill("smoke-admin")
    page.locator('input[autocomplete="current-password"]').fill("SmokePass123!")
    page.get_by_role("button", name="进入系统").click()
    page.wait_for_url(lambda url: "/login" not in str(url))
    page.wait_for_load_state("networkidle")
    errors.clear()  # The anonymous /api/auth/me/ probe on the login screen is expected.

    page.goto("http://127.0.0.1:8011/recruitment")
    page.wait_for_load_state("networkidle")
    page.get_by_text("简历初筛进度").wait_for()
    page.get_by_text("待解析简历").wait_for()

    page.goto("http://127.0.0.1:8011/recruitment/resumes?job=1")
    page.wait_for_load_state("networkidle")
    screening = page.locator('[data-test="resume-screening-preview"]')
    screening.wait_for()
    assert "岗位评分标准" in screening.inner_text()
    assert "上传 Word / Excel" in screening.inner_text()
    assert "解析状态" in page.locator("table").inner_text()

    page.get_by_role("button", name="Copilot").click()
    page.get_by_text("测试连接").wait_for()
    page.get_by_text("原文件留在本机").wait_for()
    page.get_by_role("button", name="关闭").click()

    analysis = page.locator('[data-test^="intelligence-"]').first
    if analysis.count():
        analysis.click()
        page.get_by_role("button", name="结构化信息").wait_for()
        page.get_by_text("AI 结论仅供 HR 复核").wait_for()

    page.screenshot(path=str(Path(gettempdir()) / "hr-phase3-smoke.png"), full_page=True)
    browser.close()

if errors:
    raise SystemExit("Browser errors: " + " | ".join(errors))
print("Phase 3 browser smoke passed")
