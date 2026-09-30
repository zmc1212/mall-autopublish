import argparse
import importlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

def _load_web():
    spec = importlib.util.spec_from_file_location('web', ROOT / '千牛网页执行.py')
    web = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(web)
    return web

def _load_pipeline():
    importlib.import_module('web_fill')
    return importlib.import_module('web_fill.pipeline')

SLIDER_WORDS = ('滑块', '验证码', '请拖动', '请按住滑块', '请完成验证', '操作过于频繁', 'punish', 'captcha')

def has_slider(text):
    return any(word in str(text or '') for word in SLIDER_WORDS)

def write_summary(main_result, detail_result):
    summary = {'main_images': main_result, 'detail_images': detail_result}
    out = ROOT / 'output' / 'playwright' / 'upload_slider_test.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    failed = any(result.get('error') or result.get('skipped') for result in summary.values())
    print('[6] result ->', out, flush=True)
    print('[6] ' + ('STOPPED: 未通过，已保留现场。' if failed else 'PASS: 图片已核验。')
          + ' no submit, no spec images.', flush=True)
    return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='真实图片上传检查；不提交商品，任何未确认结果立即停止')
    parser.add_argument('--live', action='store_true', help='明确允许向当前千牛账号上传测试图片')
    if not parser.parse_args(argv).live:
        print('未执行真实上传；需显式指定 --live。离线回归请运行 test_upload_slider_safety。', flush=True)
        return 2
    web = _load_web()
    pipeline = _load_pipeline()
    session = web.CliSession()
    session.attach()
    print('[1] attach ok, href =', session.href(), flush=True)
    risk = pipeline.run_script(session, 'upload_status.js', {})
    if risk.get('securityChallenge') or risk.get('status', {}).get('securityLimit'):
        return write_summary({'error': '现有验证码或频率限制尚未解除；未上传任何文件'},
                             {'skipped': '前置安全检查未通过'})
    product = {'title': '主图详情图滑块测试勿提交', 'brand': 'Deli/得力', 'model': 'S11', 'category': '中性笔', 'category_id': '50012720'}
    payload = pipeline.product_to_payload(product)
    payload['skus'] = []
    payload['main_images'] = [str(ROOT / 'testdata' / 'images' / 'main-1-1.jpg')]
    payload['portrait_images'] = []
    payload['detail_images'] = [str(ROOT / 'testdata' / 'images' / 'detail-01.jpg'), str(ROOT / 'testdata' / 'images' / 'detail-03.jpg'), str(ROOT / 'testdata' / 'images' / 'detail-05.jpg')]
    steps = []
    try:
        href, how = pipeline.ensure_fill_tab(session, web=web)
        print('[2] tab:', how, href, flush=True)
    except Exception as exc:
        print('[2] ensure_fill_tab failed:', exc, flush=True)
        raise
    try:
        if how != 'reuse-publish':
            print('[3] enter publish via category...', flush=True)
            cat = pipeline.run_gate(session, 'category.js', payload, steps, 'category', timeout=90)
            print('[3] category:', json.dumps(cat, ensure_ascii=False)[:400], flush=True)
            if not web.is_publish_page(session.href()):
                print('[3] not publish page:', session.href(), flush=True)
                return 1
        else:
            print('[3] reuse publish:', session.href(), flush=True)
        before = pipeline.run_script(session, 'probe_state.js', payload)
        if ('itemid=' in session.href().lower() or before.get('title')
                or before.get('mainImgs') or before.get('detailImgs')):
            return write_summary({'error': '实测仅允许空白新建页，未覆盖现有商品或草稿'},
                                 {'skipped': '页面非空白'})
    except Exception as exc:
        print('[3] enter publish failed:', exc, flush=True)
        if has_slider(exc):
            print('>>> SLIDER detected (enter publish)', flush=True)
        raise
    print('[4] upload main image x1...', flush=True)
    try:
        main_result = pipeline._image_step(session, 'main_images.js', {'files': payload['main_images'], 'names': [Path(p).name for p in payload['main_images']], 'field': '#sell-field-mainImagesGroup'}, payload['main_images'])
        print('[4] main result:', json.dumps(main_result, ensure_ascii=False)[:600], flush=True)
    except Exception as exc:
        print('[4] main error:', exc, flush=True)
        if has_slider(exc):
            print('>>> SLIDER detected (main upload)', flush=True)
        main_result = {'error': str(exc)}
        return write_summary(main_result, {'skipped': '主图未核验成功；未继续上传详情图'})
    print('[5] upload detail images x3...', flush=True)
    try:
        detail_result = pipeline._image_step(session, 'details.js', {'files': payload['detail_images'], 'names': [Path(p).name for p in payload['detail_images']]}, payload['detail_images'])
        print('[5] detail result:', json.dumps(detail_result, ensure_ascii=False)[:600], flush=True)
    except Exception as exc:
        print('[5] detail error:', exc, flush=True)
        if has_slider(exc):
            print('>>> SLIDER detected (detail upload)', flush=True)
        detail_result = {'error': str(exc)}
    return write_summary(main_result, detail_result)

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('interrupted', flush=True)
        raise SystemExit(130)
