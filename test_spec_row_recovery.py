import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from web_fill import pipeline as p
from test_web_fill import FakeSession


class SpecRowRecoveryTests(unittest.TestCase):
    def exercise(self, identical=False, stuck=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = [root / 'a.jpg', root / 'b.jpg']
            files[0].write_bytes(b'a')
            files[1].write_bytes(b'a' if identical else b'b')
            sources = {1: 'shared.jpg', 2: 'shared.jpg'}
            replacements = []

            def run(session, name, args, timeout=120):
                if name == 'spec_row_status.js':
                    return {'total': 2, 'missing': [], 'sources': [
                        {'index': i, 'src': src} for i, src in sources.items()]}
                if name == 'spec_row_images.js':
                    i = args['index'] + 1
                    if args['phase'] == 'open':
                        if not args['forceReplace']:
                            return {'already': True, 'saved': True, 'imageSrc': sources[i]}
                        replacements.append(i)
                        self.assertTrue(Path(args['image']).name.startswith('qn_'))
                        self.assertEqual(Path(args['image']).read_bytes(), files[i - 1].read_bytes())
                        return {'ready': True}
                    if not stuck:
                        sources[i] = f'correct-{i}.jpg'
                    return {'saved': True, 'imageSrc': sources[i]}
                return {}

            with patch.object(p, 'get_output', return_value=root / 'out'), \
                 patch.object(p, 'run_script', side_effect=run), patch.object(p.time, 'sleep'):
                payload = {'skus': [{'image': str(f)} for f in files]}
                if stuck:
                    with self.assertRaisesRegex(RuntimeError, '最终复核'):
                        p._spec_row_image_step(FakeSession(), payload)
                else:
                    result = p._spec_row_image_step(FakeSession(), payload)
                    self.assertTrue(result['bind']['saved'])
            return replacements

    def test_existing_conflicting_rows_are_replaced_instead_of_skipped(self):
        self.assertEqual(self.exercise(), [1, 2])

    def test_identical_local_images_may_share_remote_source(self):
        self.assertEqual(self.exercise(identical=True), [])

    def test_persistent_conflicts_stop_after_bounded_repairs(self):
        self.assertEqual(self.exercise(stuck=True), [1, 2, 1, 2])


if __name__ == '__main__':
    unittest.main()
