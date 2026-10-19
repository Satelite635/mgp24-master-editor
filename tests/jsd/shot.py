import sys
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b=p.chromium.launch(executable_path="/opt/pw-browsers/chromium" if False else None)
    for w in (1000,1400):
        pg=b.new_page(viewport={"width":w,"height":300})
        pg.goto("file:///home/claude/mgp_editor/webui.html")
        pg.evaluate("document.querySelector('#dirty').textContent='● 6 unsaved files';document.querySelector('#dirty').classList.add('on');document.querySelector('#b_save').disabled=false;document.querySelector('#b_launch').disabled=false")
        pg.screenshot(path=f"/tmp/jsd/hdr{w}.png",clip={"x":0,"y":0,"width":w,"height":130})
    b.close()
