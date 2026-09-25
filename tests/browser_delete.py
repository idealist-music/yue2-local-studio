"""Browser-level deletion confirmation smoke test using an isolated test-engine store."""
from dataclasses import replace
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "serve":
        import uvicorn
        from studio.app import create_app
        from studio.config import load_config
        config = replace(load_config(), data_dir=Path(sys.argv[2]), engine="test", port=int(sys.argv[3]))
        uvicorn.run(create_app(config), host="127.0.0.1", port=config.port, workers=1, proxy_headers=False)
        return

    from playwright.sync_api import sync_playwright, expect
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(ROOT / ".browser")
    with tempfile.TemporaryDirectory(prefix="studio-delete-browser-") as tmp:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        log_path = Path(tmp) / "server.log"
        with log_path.open("w+") as log:
            proc = subprocess.Popen([sys.executable, "-B", __file__, "serve", tmp, str(port)], stdout=log, stderr=log)
            try:
                for _ in range(120):
                    try:
                        if json.load(urllib.request.urlopen(url + "/api/health", timeout=.5))["ready"]:
                            break
                    except OSError:
                        pass
                    time.sleep(.05)
                else:
                    raise RuntimeError("temporary test server did not start")

                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True)
                    page = browser.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(url)

                    def create_song(name):
                        response = page.request.post(url + "/api/jobs", data={
                            "submission_key": os.urandom(16).hex(), "title": name,
                            "style": "test style", "lyrics": "[Verse]\ntest lyrics",
                            "seed_mode": "fixed", "seed": "7", "candidate_count": 1,
                        })
                        assert response.status == 202, response.text()
                        song_id = response.json()["jobs"][0]["id"]
                        for _ in range(100):
                            row = page.request.get(url + "/api/jobs/" + song_id)
                            if row.status == 200 and row.json()["status"] in ("completed", "failed"):
                                assert row.json()["status"] == "completed", row.text()
                                return song_id
                            time.sleep(.05)
                        raise AssertionError("test song did not finish")

                    create_song("Cancel keeps this song")
                    row = page.locator(".song-row").first
                    row.locator(".delete-song-button").click()
                    expect(page.locator("#delete-dialog")).to_be_visible()
                    expect(page.locator("#delete-title")).to_have_text("Cancel keeps this song")
                    expect(page.locator("#delete-confirm")).to_be_enabled()
                    page.locator("#delete-cancel").click()
                    expect(page.locator("#delete-dialog")).to_be_hidden()
                    expect(page.locator(".song-row")).to_have_count(1)

                    # The dialog and dynamic copy are translated after switching languages.
                    page.locator("#language-toggle").click()
                    row.locator(".delete-song-button").click()
                    expect(page.locator("#delete-heading")).to_have_text("Delete song")
                    expect(page.locator("#delete-cancel")).to_have_text("Cancel")
                    page.locator("#delete-cancel").click()
                    page.locator("#language-toggle").click()

                    page.locator(".song-row").first.locator(".delete-song-button").click()
                    page.locator("#delete-confirm").click()
                    expect(page.locator(".song-row")).to_have_count(0)
                    expect(page.locator("#delete-dialog")).to_be_hidden()

                    song_id = create_song("Delete from Track Detail")
                    page.locator(".song-select").click()
                    expect(page.locator("#detail-title")).to_have_text("Delete from Track Detail")
                    page.locator("#detail-delete").click()
                    expect(page.locator("#delete-title")).to_have_text("Delete from Track Detail")
                    page.locator("#delete-confirm").click()
                    expect(page.locator("#song-detail")).to_be_hidden()
                    expect(page.locator(".song-row")).to_have_count(0)
                    assert page.request.get(url + "/api/jobs/" + song_id).status == 404
                    assert not errors, errors
                    print("PASS: library cancel preserves song, localized confirmation, confirmed library delete, Track Detail delete, no browser JS errors")
                    browser.close()
            finally:
                proc.terminate()
                try:
                    proc.wait(10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


if __name__ == "__main__":
    main()
