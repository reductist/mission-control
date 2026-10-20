"""Real browser regression coverage; run with MC_BROWSER_TESTS=1.

Requires Chrome/Chromium and ChromeDriver on PATH. Uses native WebDriver
clicks so focus-before-click stacking failures cannot be masked by JS click().
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

from mission_control.database import Database
from mission_control.server import MissionControlApplication, build_server


@pytest.fixture
def browser(tmp_path):
    if os.environ.get("MC_BROWSER_TESTS") != "1":
        pytest.skip("Set MC_BROWSER_TESTS=1 to run native browser interactions")
    driver_path = shutil.which("chromedriver")
    assert driver_path, "ChromeDriver is required for browser tests"
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    driver = subprocess.Popen([driver_path, f"--port={port}"], stdout=subprocess.DEVNULL)
    server = build_server(MissionControlApplication(Database(tmp_path / "browser.db"), demo=True), "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"

    def call(path, data=None, method="POST"):
        request = Request(base + path, data=json.dumps(data or {}).encode() if method == "POST" else None,
                          headers={"Content-Type": "application/json"}, method=method)
        try:
            with urlopen(request, timeout=20) as response:
                value = json.load(response)["value"]
        except HTTPError as error:
            raise AssertionError(error.read().decode()) from error
        assert not isinstance(value, dict) or "error" not in value, value
        return value

    try:
        for _ in range(100):
            try:
                call("/status", method="GET")
                break
            except OSError:
                time.sleep(0.05)
        options = {"args": ["--headless", "--no-sandbox", "--disable-gpu"]}
        if os.environ.get("MC_CHROME_BINARY"):
            options["binary"] = os.environ["MC_CHROME_BINARY"]
        session = call("/session", {"capabilities": {"alwaysMatch": {
            "browserName": "chrome", "goog:chromeOptions": options}}})["sessionId"]
        prefix = f"/session/{session}"

        def execute(script):
            return call(prefix + "/execute/sync", {"script": script, "args": []})

        def click(selector):
            element = call(prefix + "/element", {"using": "css selector", "value": selector})
            call(prefix + "/element/" + element["element-6066-11e4-a52e-4f735466cecf"] + "/click")

        def viewport(width):
            call(prefix + "/goog/cdp/execute", {"cmd": "Emulation.setDeviceMetricsOverride", "params": {
                "width": width, "height": 915, "deviceScaleFactor": 1, "mobile": width <= 680}})
            call(prefix + "/url", {"url": f"http://127.0.0.1:{server.server_port}"})

        def tap(x, y):
            call(prefix + "/actions", {"actions": [{"type": "pointer", "id": "touch", "parameters": {"pointerType": "touch"}, "actions": [
                {"type": "pointerMove", "duration": 0, "x": x, "y": y},
                {"type": "pointerDown", "button": 0}, {"type": "pointerUp", "button": 0}]}]})

        yield execute, click, viewport, tap
        call(prefix, method="DELETE")
    finally:
        driver.terminate()
        driver.wait(timeout=10)
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("width", [320, 412])
def test_mobile_native_section_clicks_and_inspector_focus(browser, width):
    execute, click, viewport, tap = browser
    viewport(width)
    for _ in range(2):
        for view, title in [("overview", "Overview"), ("schedule", "Schedule"), ("house", "House"),
                            ("maintenance", "Maintenance"), ("yard", "Yard"), ("history", "History")]:
            click(f'.mobile-section-tab[data-view="{view}"]')
            assert execute('return document.querySelector("#page-title").textContent') == title
            assert execute('return document.querySelector("#drawer-backdrop").hidden')
            assert execute('return document.querySelectorAll(".mobile-section-tab[aria-current=page]").length') == 1
    click('.mobile-section-tab[data-view="overview"]')
    execute('document.querySelector("#quick-add-title").focus()')
    click("#inspector-toggle")
    time.sleep(0.2)
    # Inspector contains a proxy for the selected task's native Add command.
    execute('(document.querySelector("#inspector-pane button") || document.querySelector("#inspector-pane")).focus()')
    assert execute('const e=document.querySelector("#inspector-pane"),r=e.getBoundingClientRect(); return e.contains(document.elementFromPoint(r.left+20,r.top+60))')
    assert int(execute('return getComputedStyle(document.querySelector("#inspector-pane")).zIndex')) > 20
    execute('document.activeElement.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape",bubbles:true}))')
    assert execute('return document.querySelector("#drawer-backdrop").hidden')
    assert execute('return document.activeElement.id') == "inspector-toggle"
    for _ in range(2):
        click("#inspector-toggle")
        time.sleep(0.2)
        # Native click at the exposed left edge, outside the right Inspector.
        tap(5, 200)
        assert execute('return document.querySelector("#drawer-backdrop").hidden')
    assert execute('return getComputedStyle(document.querySelector(".task-title")).fontSize') == "14px"
    assert execute('return getComputedStyle(document.querySelector(".task-description")).fontSize') == "12px"
    assert execute('return document.documentElement.scrollWidth <= innerWidth')
    execute('document.querySelector("#quick-add-title").focus(); document.activeElement.dispatchEvent(new KeyboardEvent("keydown",{key:"]",bubbles:true}))')
    assert execute('return document.querySelector("#drawer-backdrop").hidden')
    execute('document.dispatchEvent(new KeyboardEvent("keydown",{key:"s",bubbles:true}))')
    assert execute('return document.activeElement.classList.contains("mobile-section-tab")')
    assert execute('return document.querySelector("#drawer-backdrop").hidden')


def test_desktop_sidebar_and_keyboard_context(browser):
    execute, click, viewport, _tap = browser
    viewport(1440)
    assert execute('return getComputedStyle(document.querySelector(".mobile-section-tabs")).display') == "none"
    assert execute('return getComputedStyle(document.querySelector(".keybar")).display') == "flex"
    click('.nav-item[data-view="schedule"]')
    before = execute('return document.querySelector(".queue-pane").getBoundingClientRect().width')
    click("#navigator-toggle")
    click("#inspector-toggle")
    assert execute('return document.querySelector(".queue-pane").getBoundingClientRect().width') > before


@pytest.mark.parametrize(("width", "expected_columns"), [(320, 1), (412, 1), (1440, 3)])
def test_provider_schedule_row_responsive_layout(browser, width, expected_columns):
    execute, click, viewport, _tap = browser
    viewport(width)
    click((".mobile-section-tab" if width <= 680 else ".nav-item") + '[data-view="schedule"]')
    execute(
        '''
        const fixture = document.createElement("section");
        fixture.id = "provider-layout-fixture";
        fixture.innerHTML = scheduleRow({
          id: "provider-layout-fixture",
          kind: "event",
          title: "Provider event title ".repeat(8),
          detail: `https://example.invalid/${"x".repeat(240)}`,
          timing: {
            kind: "timed",
            starts_at: "2026-10-20T12:00:00+00:00",
            ends_at: "2026-10-20T13:00:00+00:00",
          },
          source: {
            plugin_id: "google-calendar",
            entity_type: "calendar-event",
            entity_id: "provider-layout-fixture",
          },
        });
        document.querySelector("#app").prepend(fixture);
        wireExpandableText(fixture);
        '''
    )
    row = "#provider-layout-fixture .schedule-row"
    columns = execute(
        f'return getComputedStyle(document.querySelector({json.dumps(row)})).gridTemplateColumns'
    )
    assert len(columns.split()) == expected_columns
    assert execute(
        f'return document.querySelectorAll({json.dumps(row + " .expandable-text")}).length'
    ) == 2
    assert execute(
        f'return [...document.querySelectorAll({json.dumps(row + " .text-preview")})]'
        '.every((element) => element.textContent.endsWith("..."))'
    )
    click(row + " .expandable-text")
    assert execute(
        f'return document.querySelector({json.dumps(row + " .expandable-text")})'
        '.getAttribute("aria-expanded")'
    ) == "true"
    assert execute("return document.documentElement.scrollWidth <= innerWidth")
    if width <= 680:
        assert execute(
            f'return getComputedStyle(document.querySelector({json.dumps(row + " > .state-badge")}))'
            '.gridColumnStart'
        ) == "1"


@pytest.mark.parametrize("width", [320, 412])
def test_mobile_task_deadlines_tags_edit_and_schedule_filter(browser, width):
    execute, click, viewport, _tap = browser
    viewport(width)

    def wait_for(script):
        for _ in range(100):
            if execute(script):
                return
            time.sleep(0.05)
        assert execute(script), script

    def fill(selector, value):
        execute(f"const e=document.querySelector({json.dumps(selector)}); "
                f"e.value={json.dumps(value)}; e.dispatchEvent(new Event('input',{{bubbles:true}})); "
                "e.dispatchEvent(new Event('change',{bubbles:true}));")

    today = execute("return new Date().toLocaleDateString('en-CA')")
    titles = [f"Browser synthetic yard {width}", f"Browser synthetic social {width}"]
    for index, title in enumerate(titles):
        fill("#quick-add-title", title)
        if not execute('return document.querySelector("details.task-options").open'):
            click("details.task-options > summary")
        fill("#create-date", today)
        fill("#create-zone", "Europe/London")
        assert execute('return document.querySelector("#create-deadline-mode").value') == "end-of-day"
        if index:
            fill("#create-deadline-mode", "specific")
            assert not execute('return document.querySelector(".specific-time-fields").hidden')
            fill("#create-time", "18:30")
        if not execute('return document.querySelector("details.task-options .tag-picker").open'):
            click("details.task-options .tag-picker > summary")
        for tag in (["yard", "maintenance"] if index == 0 else ["personal-social"]):
            click(f'#create-tags input[value="{tag}"]')
        click('#quick-add-form button[type="submit"]')
        wait_for(f"return [...document.querySelectorAll('.task-title')].some(e=>e.textContent==={json.dumps(title)})")
        assert execute("return document.documentElement.scrollWidth <= innerWidth")

    # Reload through WebDriver: values must come back from persisted server data.
    viewport(width)
    wait_for(f"return [...document.querySelectorAll('.task-title')].some(e=>e.textContent==={json.dumps(titles[0])})")
    ids = []
    for index, title in enumerate(titles):
        task_id = execute(f"const row=[...document.querySelectorAll('.task-row')].find(e=>e.querySelector('.task-title')?.textContent==={json.dumps(title)}); return row?.querySelector('[data-edit-task]')?.dataset.editTask")
        assert task_id
        ids.append(task_id)
        click(f'[data-edit-task="{task_id}"]')
        assert execute('return document.querySelector("#edit-date").value') == today
        assert execute('return document.querySelector("#edit-zone").value') == "Europe/London"
        assert execute('return document.querySelector("#edit-deadline-mode").value') == ("specific" if index else "end-of-day")
        assert execute('return [...document.querySelectorAll("#edit-tags input:checked")].map(e=>e.value).sort()') == (["personal-social"] if index else ["maintenance", "yard"])
        if index:
            assert execute('return document.querySelector("#edit-time").value') == "18:30"
        click("[data-close-task-editor]")

    click('.mobile-section-tab[data-view="schedule"]')
    wait_for('return !!document.querySelector("#schedule-tags")')
    click(".schedule-controls .tag-picker > summary")
    click('#schedule-tags input[value="yard"]')
    assert titles[0] in execute('return document.querySelector("#app").textContent')
    assert titles[1] not in execute('return document.querySelector("#app").textContent')
    click('#schedule-tags input[value="personal-social"]')
    assert all(title in execute('return document.querySelector("#app").textContent') for title in titles)
    click('[data-schedule-layout="calendar"]')
    assert all(title in execute('return document.querySelector("#app").textContent') for title in titles)
    click('[data-clear-schedule-tags]')
    assert execute('return document.querySelectorAll("#schedule-tags input:checked").length') == 0

    # Removing the deadline retains an unscheduled task; removing tags persists.
    click('.mobile-section-tab[data-view="overview"]')
    click(f'[data-edit-task="{ids[0]}"]')
    fill("#edit-date", "")
    click("#task-edit-form .tag-picker > summary")
    click('#edit-tags input[value="yard"]')
    click('#task-edit-form button[type="submit"]')
    wait_for('return !document.querySelector("#task-editor-dialog").open')
    wait_for(f'return document.activeElement?.dataset?.editTask === "{ids[0]}"')
    viewport(width)
    wait_for(f'return !!document.querySelector(\'[data-edit-task="{ids[0]}"]\')')
    click(f'[data-edit-task="{ids[0]}"]')
    assert execute('return document.querySelector("#edit-date").value') == ""
    assert execute('return [...document.querySelectorAll("#edit-tags input:checked")].map(e=>e.value)') == ["maintenance"]
    click("[data-close-task-editor]")
    click('.mobile-section-tab[data-view="schedule"]')
    click('[data-schedule-layout="calendar"]')
    assert titles[0] not in execute('return [...document.querySelectorAll(".calendar-item")].map(e=>e.textContent).join(" ")')
    assert titles[1] in execute('return document.querySelector("#app").textContent')

    # A nonexistent civil time must fail visibly rather than shift the deadline.
    click('.mobile-section-tab[data-view="overview"]')
    click(f'[data-edit-task="{ids[1]}"]')
    fill("#edit-date", "2026-03-29")
    fill("#edit-time", "01:30")
    click('#task-edit-form button[type="submit"]')
    wait_for('return document.querySelector("#task-edit-form .form-error").textContent.includes("does not exist")')
    assert execute('return document.querySelector("#task-editor-dialog").open')
    # The explicit second occurrence survives saving/reopening a repeated time.
    fill("#edit-date", "2026-10-25")
    fill("#edit-occurrence", "later")
    click("#task-edit-form .tag-picker > summary")
    click('#edit-tags input[value="house-search"]')
    click('#task-edit-form button[type="submit"]')
    wait_for('return !document.querySelector("#task-editor-dialog").open')
    wait_for(f'return document.activeElement?.dataset?.editTask === "{ids[1]}"')
    viewport(width)
    wait_for(f'return !!document.querySelector(\'[data-edit-task="{ids[1]}"]\')')
    click(f'[data-edit-task="{ids[1]}"]')
    assert execute('return document.querySelector("#edit-date").value') == "2026-10-25"
    assert execute('return document.querySelector("#edit-time").value') == "01:30"
    assert execute('return document.querySelector("#edit-occurrence").value') == "later"
    assert execute('return [...document.querySelectorAll("#edit-tags input:checked")].map(e=>e.value).sort()') == ["house-search", "personal-social"]


def test_unrelated_edit_preserves_precise_timed_deadline(browser):
    execute, click, viewport, _tap = browser
    viewport(412)
    deadline = {"kind": "due-at", "due_at": "2026-10-15T18:30:45.123Z", "time_zone": "UTC"}
    payload = {"title": "Browser precision fixture", "deadline": deadline, "tags": ["yard"]}
    task = execute('return fetch("/api/tasks",{method:"POST",headers:{"Content-Type":"application/json","X-Mission-Control-Token":document.querySelector(\'meta[name="mission-control-write-token"]\').content},body:' + json.dumps(json.dumps(payload)) + '}).then(r=>r.json())')
    viewport(412)
    for _ in range(100):
        if execute(f'return !!document.querySelector(\'[data-edit-task="{task["id"]}"]\')'):
            break
        time.sleep(0.05)
    click(f'[data-edit-task="{task["id"]}"]')
    execute('document.querySelector("#edit-task-title").value="Browser precision edited"')
    click('#task-edit-form button[type="submit"]')
    for _ in range(100):
        if not execute('return document.querySelector("#task-editor-dialog").open'):
            break
        time.sleep(0.05)
    result = execute('return fetch("/api/dashboard").then(r=>r.json()).then(d=>d.tasks.find(t=>t.id===' + json.dumps(task["id"]) + '))')
    assert result["title"] == "Browser precision edited"
    assert result["deadline"] == deadline
