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
        with urlopen(request, timeout=20) as response:
            value = json.load(response)["value"]
        assert not isinstance(value, dict) or "error" not in value, value
        return value

    try:
        for _ in range(100):
            try:
                call("/status", method="GET")
                break
            except OSError:
                time.sleep(0.05)
        session = call("/session", {"capabilities": {"alwaysMatch": {"browserName": "chrome", "goog:chromeOptions": {
            "args": ["--headless", "--no-sandbox", "--disable-gpu"]}}}})["sessionId"]
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
