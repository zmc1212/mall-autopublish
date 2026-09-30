"""Opt-in live image-flow check. Stops before attributes/SKU; never publishes.

Run only when explicitly authorized: QIANNIU_LIVE_IMAGE_UPLOAD=1.
Uses the saved AGPK3319 product and the application's existing Chrome profile.
Any platform restriction fails the test and preserves the browser for the user.
"""

import json
import os
import threading
import unittest
from collections import Counter
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent


@unittest.skipUnless(os.environ.get('QIANNIU_LIVE_IMAGE_UPLOAD') == '1', 'live upload requires explicit opt-in')
class LiveImageUploadTests(unittest.TestCase):
    def test_media_first_without_duplicate_dispatch_or_publish(self):
        from desktop.paths import configure_environ
        configure_environ()
        output = ROOT / 'output' / 'playwright' / 'media-first-live' / datetime.now().strftime('%Y%m%d-%H%M%S')
        output.mkdir(parents=True, exist_ok=True)
        print('LIVE_REPORT_DIR=' + str(output), flush=True)
        os.environ['QIANNIU_OUTPUT_DIR'] = str(output)
        os.environ['QIANNIU_DEBUG_BROWSER'] = '1'
        from desktop.modules import load_web
        from web_fill import pipeline as p
        import job_session
        candidates = [entry.get('product', entry) for entry in job_session.load_session().get('products', [])]
        matches = [product for product in candidates if 'AGPK3319' in json.dumps(product, ensure_ascii=False)]
        self.assertEqual(len(matches), 1, 'Expected one saved AGPK3319 product; never invent test product data')
        product = matches[0]
        payload = p.product_to_payload(product)
        files = payload['main_images'] + payload['portrait_images'] + payload['detail_images']
        self.assertTrue(files)
        self.assertTrue(all(Path(file).is_file() for file in files))
        self.assertEqual(len(files), len({Path(file).name for file in files}), 'Audit needs distinct target filenames')
        web = load_web()
        web.reload_paths()
        session = web.CliSession()
        self.assertTrue(web.cdp_available(), 'Existing Chrome debugging session required; no browser was launched')
        session.cmd('attach', '--cdp', web.CDP_ENDPOINT, raw=False)
        # Attaching may select the workbench instead of the existing draft.
        # Select only a unique existing new-product tab; never create one here.
        candidates = [(index, url) for index, url in p.parse_tabs(session.tab_list())
                      if web.is_publish_page(url) and 'itemid=' not in url.lower()]
        self.assertEqual(len(candidates), 1, 'Expected one existing new-product draft; no navigation or upload attempted')
        session.tab_select(candidates[0][0])
        current_href = session.href()
        self.assertTrue(web.is_publish_page(current_href),
                        'Expected existing new-product page; actual path: ' + current_href.split('?')[0])
        self.assertNotIn('itemid=', session.href().lower())
        before = p.run_script(session, 'probe_state.js', payload)
        risk = p.run_script(session, 'upload_status.js', {})
        self.assertFalse(risk.get('securityChallenge') or risk.get('status', {}).get('securityLimit'),
                         'Existing verification requirement: no live upload attempted')
        self.assertFalse(before.get('title'), 'Do not overwrite a populated draft')
        resume_media = os.environ.get('QIANNIU_LIVE_RESUME_MEDIA') == '1'
        if resume_media:
            self.assertEqual((before.get('checkpoint') or {}).get('key'), p.resume_key(payload),
                             'Only resume media belonging to this exact product checkpoint')
            self.assertIn(before.get('mainImgs'), (0, len(payload['main_images'])),
                          'Do not overwrite partially bound main images')
            self.assertFalse(p.page_conflicts(before, payload), 'Existing draft belongs to another product')
            self.assertLess(before.get('detailImgs', 0), len(payload['detail_images']),
                            'Media already complete: do not run a test that might reach attributes')
        else:
            self.assertEqual(before.get('mainImgs'), 0, 'This upload-count check needs a blank main-image area')
            self.assertEqual(before.get('detailImgs'), 0, 'This upload-count check needs a blank details area')
        template = (ROOT / 'testdata' / 'scripts' / 'image_upload_audit.js').read_text(encoding='utf-8')

        def audit(phase):
            script = output / ('image_upload_audit.' + phase + '.js')
            script.write_text(template.replace('/*PHASE*/', json.dumps(phase)), encoding='utf-8')
            raw = session.cmd('run-code', f'--filename={script}', raw=False, timeout=20)
            if '### Error' in raw:
                raise RuntimeError(raw)
            return p.extract_result(raw)

        audit('start')
        self.assertTrue(audit('read')['active'], 'Instrumentation must survive separate CLI calls')
        session.cancel_event = threading.Event()
        order = []
        original = p._image_step

        def observe_image_step(s, script, args, image_files):
            order.append(args.get('field', script))
            if os.environ.get('QIANNIU_LIVE_LIBRARY_ONLY') == '1':
                args = {**args, 'libraryOnly': True}
            result = original(s, script, args, image_files)
            # Exercise the production scheduler, but stop before unrelated
            # attribute, SKU, logistics or submission actions can execute.
            if script == 'details.js':
                session.cancel_event.set()
            return result

        report = {'scope': 'main/detail image phases only; no publish', 'before': before,
                  'resume_media': resume_media}
        try:
            with patch.object(p, '_image_step', side_effect=observe_image_step):
                result = p.fill_new_product(session, product, web=web, confirm_submit=False,
                                            sku_template_import=True)
            report['result'] = result
            report['order'] = order
        finally:
            session.cancel_event.clear()
            report['audit'] = audit('stop')
            report['after'] = p.run_script(session, 'probe_state.js', payload)
            screenshot_path = json.dumps(str(output / 'page-after.png'))
            report['screenshot'] = session.cmd('run-code',
                'async page => { await page.screenshot({path:' + screenshot_path +
                ',timeout:20000,animations:"disabled",caret:"hide"}); return {saved:true}; }',
                raw=False, timeout=25)
            (output / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        expected_order = []
        if payload['main_images'] and before.get('mainImgs') != len(payload['main_images']):
            expected_order.append('#sell-field-mainImagesGroup')
        if payload['portrait_images'] and before.get('p34Imgs') != len(payload['portrait_images']):
            expected_order.append('#sell-field-threeToFourImages')
        expected_order.append('details.js')
        self.assertEqual(order, expected_order, report['result'].get('notice'))
        self.assertEqual(report['after']['mainImgs'], len(payload['main_images']), report['result'])
        self.assertEqual(report['after']['detailImgs'], len(payload['detail_images']), report['result'])
        self.assertFalse(report['after']['title'], 'Attributes ran before image verification stopped the flow')
        self.assertEqual(report['after']['skuRows'], before['skuRows'], 'SKU import ran before image verification')
        expected_names = Counter(p._media_upload_name(file) for file in files)
        events = Counter(name for event in report['audit']['events'] for name in event['names'])
        # Reusing an existing library image is valid and must not force a new
        # upload. Every file that is submitted still has to be a target, once.
        self.assertFalse(events - expected_names, 'Unknown file or duplicate input dispatch detected')
        requests = Counter(name for request in report['audit']['requests'] for name in request['names'])
        self.assertTrue(all(count == 1 for count in requests.values()), 'Duplicate multipart upload detected')
        # Chromium omits binary multipart file names from postData(). Count the
        # actual upload endpoint as well, so an empty names list cannot pass a
        # duplicate-network-request check vacuously.
        uploads = [request for request in report['audit']['requests']
                   if request.get('fileUpload')]
        self.assertEqual(len(uploads), sum(events.values()), 'File dispatch/network count mismatch')
        self.assertTrue(all(request.get('status') == 200 for request in uploads),
                        'At least one upload lacks a successful HTTP response')
        if os.environ.get('QIANNIU_LIVE_LIBRARY_ONLY') == '1':
            self.assertFalse(events, 'A library-only retry must never submit files')
            self.assertFalse(uploads, 'A library-only retry must never make upload requests')


if __name__ == '__main__':
    unittest.main()
