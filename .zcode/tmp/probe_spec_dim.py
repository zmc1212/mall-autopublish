# -*- coding: utf-8 -*-
"""只读探测第三发：商品规格维度区域的值列表 + 残留识别弹窗。"""
import json, sys
from playwright.sync_api import sync_playwright

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
        info = page.evaluate("""() => {
          // 找到“销售规格”标题所在区域，取其后续兄弟内容里的规格维度编辑区
          const all = [...document.querySelectorAll('div, span')];
          const specLabel = all.find(el => (el.innerText || '').trim() === '商品规格'
            && el.children.length === 0);
          let dimText = '';
          if (specLabel) {
            let el = specLabel;
            for (let i = 0; i < 8 && el; i++) el = el.parentElement;
            if (el) dimText = (el.innerText || '').slice(0, 2000);
          }
          // 残留弹窗（含“识别”或“在当前规格后添加”）
          const dialogs = [...document.querySelectorAll('.next-dialog, [role=dialog], [class*=Modal], [class*=modal], [class*=Dialog], [class*=dialog]')]
            .map(d => ({
              cls: String(d.className || '').slice(0, 100),
              visible: !!(d.offsetWidth || d.offsetHeight),
              text: (d.innerText || '').replace(/\\s+/g, ' ').slice(0, 300),
            }))
            .filter(d => d.text);
          // 商品规格值可能存在的 tag/chip 集合
          const chips = [...document.querySelectorAll('[class*=tag], [class*=Tag], [class*=chip], [class*=label-item], .next-tag')]
            .map(el => (el.innerText || '').trim())
            .filter(t => t && t.length <= 40);
          return { specLabelFound: !!specLabel, dimText, dialogs: dialogs.slice(0, 8), chipCount: chips.length, chips: chips.slice(0, 60) };
        }""")
        print(json.dumps(info, ensure_ascii=False, indent=1)[:7000])

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
