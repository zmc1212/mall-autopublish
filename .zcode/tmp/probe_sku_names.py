# -*- coding: utf-8 -*-
"""只读探测第二发：17 行的规格名 + 销售信息区域文本，判断是哪 17 个值被加进来了。"""
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
          const rows = [...document.querySelectorAll('table tr')].filter(tr => {
            const t = tr.innerText || '';
            return t.includes('元') && t.includes('件') && !t.includes('SKU分类');
          });
          const rowNames = rows.map(tr => ({
            inputs: [...tr.querySelectorAll('input, textarea')].map(el => String(el.value || '').trim()).filter(v => v),
          }));
          // 找“销售信息/商品规格”区域文本
          const heading = [...document.querySelectorAll('span, div, h3')]
            .find(el => (el.innerText || '').trim() === '销售信息');
          let salesText = '';
          if (heading) {
            let el = heading;
            for (let i = 0; i < 6 && el; i++) el = el.parentElement;
            salesText = el ? (el.innerText || '').slice(0, 1500) : '';
          }
          const m = (document.body.innerText || '').match(/已成功识别[\\s\\S]{0,200}/);
          return { rowCount: rows.length, rowNames, salesText: salesText.slice(0, 1500), recognized: m ? m[0] : '' };
        }""")
        print(json.dumps(info, ensure_ascii=False, indent=1)[:6000])

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
