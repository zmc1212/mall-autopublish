# -*- coding: utf-8 -*-
"""只读探测第四发：缺失的 20 个规格值是否存在于页面任何角落。"""
import json, sys
from playwright.sync_api import sync_playwright

MISSING = [
    "3支电光蓝+10支原装黑芯",
    "陨石黑+5支原装黑芯",
    "电光蓝",
    "12支陨石黑（一盒）",
    "十支原装红色笔芯",
    "经典5支+限定5支",
]
PRESENT = ["限定5支各一", "3支芭比粉+10支原装黑芯"]

def main():
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        page = None
        for ctx in browser.contexts:
            for pg in ctx.pages:
                if "publish.htm" in pg.url:
                    page = pg
                    break
        if page is None:
            print("NO_PUBLISH_PAGE")
            return
        info = page.evaluate("""(names) => {
          const html = document.documentElement.innerHTML;
          const text = document.body.innerText || '';
          const out = {};
          for (const n of names) {
            out[n] = { inHtml: html.includes(n), inText: text.includes(n) };
          }
          return out;
        }""", MISSING + PRESENT)
        for k, v in info.items():
            print(("MISSING " if not (v["inHtml"] or v["inText"]) else "FOUND   "), k, v)

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
