import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from web_fill import pipeline as p
from test_web_fill import FakeSession


class MediaIdentityTests(unittest.TestCase):
    def test_compact_spec_names_are_short_ascii_and_content_addressed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a = root / '颜色08-【两个月推荐】1支笔+10支晨光笔芯.jpg'
            b = root / '另一个文件名.jpg'
            a.write_bytes(b'same-content'); b.write_bytes(b'same-content')
            with patch.object(p, 'get_output', return_value=root / 'out'):
                staged = p._prepare_media_uploads([str(a), str(b)], compact=True)
            self.assertEqual(staged[0], staged[1])
            self.assertRegex(Path(staged[0]).name, r'^qn_[0-9a-f]{24}\.jpg$')
            self.assertEqual(len(Path(staged[0]).name), 31)
            self.assertEqual(Path(staged[0]).read_bytes(), a.read_bytes())

    def test_same_filename_from_two_products_has_different_upload_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left, right = root / 'a', root / 'b'
            left.mkdir(); right.mkdir()
            a, b = left / '详情01.jpg', right / '详情01.jpg'
            a.write_bytes(b'product-a'); b.write_bytes(b'product-b')
            with patch.object(p, 'get_output', return_value=root / 'output'):
                staged = p._prepare_media_uploads([str(a), str(b)])
                again = p._prepare_media_uploads([str(a), str(b)])
            self.assertNotEqual(Path(staged[0]).name, Path(staged[1]).name)
            self.assertEqual(staged, again)
            self.assertEqual(a.read_bytes(), b'product-a')
            self.assertEqual(b.read_bytes(), b'product-b')
            self.assertEqual([Path(f).read_bytes() for f in staged], [b'product-a', b'product-b'])

    def test_changed_content_invalidates_name_and_repairs_corrupt_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'a.png'
            source.write_bytes(b'first')
            with patch.object(p, 'get_output', return_value=root / 'output'):
                first = Path(p._prepare_media_uploads([str(source)])[0])
                first.write_bytes(b'corrupt')
                self.assertEqual(p._prepare_media_uploads([str(source)]), [first.as_posix()])
                self.assertEqual(first.read_bytes(), b'first')
                source.write_bytes(b'second')
                second = Path(p._prepare_media_uploads([str(source)])[0])
            self.assertNotEqual(first.name, second.name)
            self.assertEqual(second.read_bytes(), b'second')

    def test_missing_source_fails_before_any_browser_upload(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(p, 'get_output', return_value=Path(directory)), \
             patch.object(p, 'run_script') as run:
            with self.assertRaises(FileNotFoundError):
                p._image_step(FakeSession(), 'details.js', {'contentAddressedMedia': True},
                              [str(Path(directory) / 'missing.jpg')])
            run.assert_not_called()

    def test_staged_names_flow_through_upload_and_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'main.jpg'
            source.write_bytes(b'image-content')
            seen = []
            def run(_session, _script, args, timeout=120):
                seen.append(args)
                if args['phase'] == 'open':
                    return {'uploaded': True}
                return {'selected': [{'name': args['names'][0], 'pic': {'ok': True}}],
                        'slot': {'imgs': 1}}
            original = {'contentAddressedMedia': True, 'files': [str(source)], 'names': ['main.jpg']}
            with patch.object(p, 'get_output', return_value=root / 'output'), \
                 patch.object(p, 'run_script', side_effect=run):
                p._image_step(FakeSession(), 'main_images.js', original, [str(source)])
            self.assertEqual([args['phase'] for args in seen], ['open', 'select'])
            self.assertEqual(seen[0]['names'], [p._media_upload_name(source)])
            self.assertEqual(seen[0]['files'], seen[1]['files'])
            self.assertEqual(original['names'], ['main.jpg'])


if __name__ == '__main__':
    unittest.main()
