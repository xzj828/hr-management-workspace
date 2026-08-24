import os
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright


base_url = os.environ.get("HR_SMOKE_URL", "http://127.0.0.1:8769")
username = os.environ.get("HR_SMOKE_USER", "smoke-admin")
password = os.environ.get("HR_SMOKE_PASSWORD", "Smoke-pass-2026")
screenshot = Path(tempfile.gettempdir()) / "hr-recruitment-smoke.png"
workflow_screenshot = Path(tempfile.gettempdir()) / "hr-workflow-editor-smoke.png"

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1720, "height": 1000})
    console_errors = []
    failed_responses = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on(
        "response",
        lambda response: failed_responses.append(f"{response.status} {response.url}")
        if response.status >= 400
        else None,
    )
    page.goto(f"{base_url}/login", wait_until="networkidle")
    page.get_by_label("账号").fill(username)
    page.get_by_label("密码").fill(password)
    page.locator("form.login-card button.primary-button").click()
    page.wait_for_url("**/attendance")

    page.goto(f"{base_url}/recruitment/candidates", wait_until="networkidle")
    page.get_by_role("heading", name="候选人").wait_for()
    page.locator('[data-test^="candidate-check-"]').first.check()
    page.locator('[data-test="open-communication"]').click()
    page.get_by_text("发送前最后确认").wait_for()
    page.get_by_role("button", name="取消").last.click()

    page.goto(f"{base_url}/recruitment/automation", wait_until="networkidle")
    page.locator(".automation-workspace-tabs button").nth(2).click()
    page.get_by_text("节点库").wait_for()
    page.get_by_text("人工确认", exact=True).last.wait_for()
    page.locator('[data-test="save-workflow"]').wait_for()
    screen_node = page.locator('[data-node-key="screen"]')
    before = screen_node.bounding_box()
    page.mouse.move(before["x"] + 50, before["y"] + 24)
    page.mouse.down()
    page.mouse.move(before["x"] + 190, before["y"] + 145, steps=8)
    page.mouse.up()
    after = screen_node.bounding_box()
    if after["x"] <= before["x"] + 80 or after["y"] <= before["y"] + 70:
        raise SystemExit("Workflow node did not move freely on the canvas")
    page.locator('[data-edge-key="source-screen"]').click(force=True)
    page.locator('[data-test="remove-selection"]').click()
    if page.locator('[data-edge-key="source-screen"]').count() != 0 or screen_node.count() != 1:
        raise SystemExit("Workflow edge deletion did not preserve its nodes")
    screen_node.click()
    page.locator('[data-test="remove-selection"]').click()
    if screen_node.count() != 0:
        raise SystemExit("Workflow node deletion failed")
    page.locator('[data-test="workflow-library-wait_reply"]').click()
    page.locator('[data-test="auto-layout"]').click()
    page.screenshot(path=str(workflow_screenshot), full_page=True)

    page.goto(f"{base_url}/recruitment/pipeline", wait_until="networkidle")
    card = page.locator(".recruitment-candidate-card").first
    target = page.locator('[data-stage="interviewing"]')
    card.drag_to(target)
    page.locator('[data-test="stage-reason"]').wait_for()
    page.get_by_role("button", name="取消").last.click()

    page.goto(f"{base_url}/recruitment/resumes", wait_until="networkidle")
    page.get_by_role("heading", name="简历中心").wait_for()
    page.get_by_text("V1", exact=False).first.wait_for()
    page.screenshot(path=str(screenshot), full_page=True)
    browser.close()

unexpected_responses = [
    item for item in failed_responses if not item.endswith("403 " + f"{base_url}/api/auth/me/")
]
script_errors = [item for item in console_errors if not item.startswith("Failed to load resource:")]
if script_errors or unexpected_responses:
    raise SystemExit(
        "Browser console errors: "
        + " | ".join(script_errors)
        + "\nFailed responses: "
        + " | ".join(unexpected_responses)
    )
print(f"Recruitment UI smoke passed. Screenshots: {workflow_screenshot} | {screenshot}")
