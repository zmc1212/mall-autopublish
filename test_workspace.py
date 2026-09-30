import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook
from PIL import Image

import workspace
from workspace import clip_title, scan_workspace, sync_workbook


def write_mini_pack(folder, spec_name="规格A"):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), "red").save(folder / "宝贝主图01.jpg")
    Image.new("RGB", (8, 8), "blue").save(folder / "详情01.jpg")
    Image.new("RGB", (8, 8), "green").save(folder / f"颜色01-{spec_name}.jpg")
    return folder


def list_naruto_packs():
    testdata = Path(__file__).resolve().parent / "testdata"
    if not testdata.is_dir():
        return []
    return sorted(
        [path for path in testdata.iterdir() if path.is_dir() and "火影" in path.name],
        key=lambda item: item.name,
    )


def link_folder(source, dest):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest
    source = Path(source).resolve()
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(dest), str(source)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0 or not dest.exists():
            raise OSError(result.stderr or result.stdout or "mklink failed")
        return dest
    dest.symlink_to(source, target_is_directory=True)
    return dest


class WorkspaceTests(unittest.TestCase):
    def test_product_attribute_override_survives_template_projection(self):
        import json
        override = json.dumps({"IP联名": ""}, ensure_ascii=False)
        row = workspace._as_template_row({"商品属性(JSON)": override,
                                          "品牌*": "M＆G/晨光", "型号": "AGPK3319"})
        self.assertEqual(row["商品属性(JSON)"], override)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _titles(self, path):
        wb = load_workbook(path, data_only=True)
        try:
            sheet = wb["商品清单"]
            headers = [cell.value for cell in sheet[1]]
            rows = []
            for values in sheet.iter_rows(min_row=2, values_only=True):
                if not any(values):
                    continue
                rows.append(dict(zip(headers, values)))
            return rows
        finally:
            wb.close()

    def test_empty_workspace(self):
        scan = scan_workspace(self.root)
        self.assertEqual(scan["folders"], [])
        synced = sync_workbook(self.root)
        self.assertTrue(Path(synced["path"]).is_file())
        self.assertEqual(synced["count"], 0)
        self.assertTrue((self.root / "批次默认.json").is_file())

    def test_two_packs_merge_keeps_edited_title(self):
        write_mini_pack(self.root / "火影-001", "规格A")
        write_mini_pack(self.root / "火影-002", "规格B")
        synced = sync_workbook(self.root, {
            "品牌": "卡游",
            "商品属性模板": "中性笔",
            "物流模板": "48小时",
            "销售模板": "仓库多规格",
            "价格": 9.9,
            "库存": 20,
        })
        self.assertEqual(synced["count"], 2)
        path = Path(synced["path"])
        wb = load_workbook(path)
        sheet = wb["商品清单"]
        headers = [cell.value for cell in sheet[1]]
        title_col = headers.index("商品标题*") + 1
        id_col = headers.index("商品标识*") + 1
        for row in range(2, sheet.max_row + 1):
            if sheet.cell(row, id_col).value == "火影-001":
                sheet.cell(row, title_col).value = "卡游手改标题不要覆盖"
        wb.save(path)
        wb.close()
        write_mini_pack(self.root / "火影-003", "规格C")
        again = sync_workbook(self.root)
        rows = {row["商品标识*"]: row for row in self._titles(again["path"])}
        self.assertEqual(rows["火影-001"]["商品标题*"], "卡游手改标题不要覆盖")
        self.assertIn("火影-003", rows)
        self.assertEqual(rows["火影-001"]["价格*"], 9.9)

    def test_missing_folder_removed_on_rescan(self):
        # 清单以工作空间文件夹为镜像：文件夹被删/被替换后旧行不再保留。
        write_mini_pack(self.root / "火影-001")
        write_mini_pack(self.root / "火影-002")
        sync_workbook(self.root, {"品牌": "卡游"})
        shutil.rmtree(self.root / "火影-002")
        synced = sync_workbook(self.root)
        rows = {row["商品标识*"]: row for row in self._titles(synced["path"])}
        self.assertNotIn("火影-002", rows)
        self.assertIn("火影-001", rows)
        self.assertEqual(synced["removed"], ["火影-002"])

    def test_removed_folder_reappears_as_added_row(self):
        write_mini_pack(self.root / "火影-002")
        sync_workbook(self.root, {"品牌": "卡游"})
        shutil.rmtree(self.root / "火影-002")
        removed = sync_workbook(self.root)
        self.assertEqual(removed["removed"], ["火影-002"])
        write_mini_pack(self.root / "火影-002")
        again = sync_workbook(self.root)
        rows = {row["商品标识*"]: row for row in self._titles(again["path"])}
        self.assertIn("火影-002", rows)
        self.assertEqual(again["added"], ["火影-002"])

    def test_external_pack_row_is_preserved(self):
        # 图片包指向工作空间之外的行视为手工维护，重扫不删除。
        write_mini_pack(self.root / "火影-001")
        synced = sync_workbook(self.root, {"品牌": "卡游"})
        with tempfile.TemporaryDirectory() as external_dir:
            external_pack = write_mini_pack(Path(external_dir) / "外部商品")
            path = Path(synced["path"])
            wb = load_workbook(path)
            try:
                sheet = wb["商品清单"]
                headers = [cell.value for cell in sheet[1]]
                sheet.cell(2, headers.index("商品标识*") + 1).value = "外部商品"
                sheet.cell(2, headers.index("图片包路径*") + 1).value = str(external_pack)
                wb.save(path)
            finally:
                wb.close()
            again = sync_workbook(self.root)
            rows = {row["商品标识*"]: row for row in self._titles(again["path"])}
            self.assertIn("外部商品", rows)
            self.assertEqual(rows["外部商品"]["图片包路径*"], str(external_pack))
            self.assertEqual(again["added"], ["火影-001"])

    def test_folder_without_images_is_error(self):
        emptyish = self.root / "空图夹"
        emptyish.mkdir()
        (emptyish / "readme.txt").write_text("no images", encoding="utf-8")
        scan = scan_workspace(self.root)
        self.assertTrue(any(item["folder"] == "空图夹" for item in scan["errors"]))
        self.assertEqual(scan["folders"], [])

    def test_ignores_xlsx_inside_pack(self):
        pack = write_mini_pack(self.root / "火影-001")
        (pack / "夹内清单.xlsx").write_bytes(b"not-a-real-xlsx")
        scan = scan_workspace(self.root)
        self.assertEqual(len(scan["folders"]), 1)
        self.assertEqual(scan["folders"][0]["product_id"], "火影-001")
        self.assertEqual(scan["errors"], [])

    def test_pack_with_video_reports_video_count(self):
        pack = write_mini_pack(self.root / "火影-001")
        (pack / "主视频.mp4").write_bytes(b"fake-video")
        scan = scan_workspace(self.root)
        self.assertEqual(scan["errors"], [])
        self.assertEqual(len(scan["folders"]), 1)
        self.assertEqual(scan["folders"][0]["video_count"], 1)

    def test_video_only_folder_still_reports_error(self):
        pack = self.root / "纯视频"
        pack.mkdir()
        (pack / "主视频.mp4").write_bytes(b"fake-video")
        scan = scan_workspace(self.root)
        self.assertEqual(scan["folders"], [])
        self.assertTrue(any(item["folder"] == "纯视频" for item in scan["errors"]))

    def test_skips_hidden_and_empty(self):
        (self.root / ".hidden").mkdir()
        write_mini_pack(self.root / ".hidden")
        (self.root / "空白").mkdir()
        scan = scan_workspace(self.root)
        reasons = {item["folder"]: item["reason"] for item in scan["skipped"]}
        self.assertEqual(reasons.get(".hidden"), "隐藏目录")
        self.assertEqual(reasons.get("空白"), "空目录")

    def test_long_folder_name_clipped_to_title(self):
        name = "测" * 31
        write_mini_pack(self.root / name)
        synced = sync_workbook(self.root, {"品牌": ""})
        row = self._titles(synced["path"])[0]
        self.assertLessEqual(workspace.title_width(row["商品标题*"]), 60)
        self.assertEqual(row["商品标题*"], clip_title(name))
        self.assertEqual(row["品牌*"], "卡游")
        self.assertFalse(row["型号"])

    def test_scanned_title_uses_folder_name_and_defaults_fill_required_data(self):
        name = "无品牌前缀商品"
        write_mini_pack(self.root / name)
        synced = sync_workbook(self.root)
        row = self._titles(synced["path"])[0]
        self.assertEqual(row["商品标题*"], name)
        self.assertEqual(row["品牌*"], "卡游")
        results = workspace._seller().validate_workbook(synced["path"])
        self.assertEqual(results[0]["errors"], [])
        self.assertEqual(results[0]["product"]["attributes"]["品牌"], "卡游")
        self.assertEqual(results[0]["product"]["attributes"]["型号"], "忍道版第1弹")

    def test_sku_overrides_kept_on_rescan(self):
        write_mini_pack(self.root / "火影-001", "原名")
        synced = sync_workbook(self.root, {"品牌": "卡游"})
        path = Path(synced["path"])
        wb = load_workbook(path)
        sku = wb["SKU规格"]
        sku.cell(2, 3).value = "手改规格"
        sku.cell(2, 4).value = 8.8
        wb.save(path)
        wb.close()
        again = sync_workbook(self.root)
        wb = load_workbook(again["path"], data_only=True)
        try:
            self.assertEqual(wb["SKU规格"].cell(2, 3).value, "手改规格")
            self.assertEqual(wb["SKU规格"].cell(2, 4).value, 8.8)
        finally:
            wb.close()

    def test_two_level_categories_map_template_and_relative_path(self):
        write_mini_pack(self.root / "中性笔" / "商品A", "黑色")
        synced = sync_workbook(self.root, {"品牌": "卡游"})
        scan = synced["scan"]
        self.assertEqual([item["name"] for item in scan["categories"]], ["中性笔"])
        self.assertTrue(scan["categories"][0]["template_found"])
        row = self._titles(synced["path"])[0]
        self.assertEqual(row["商品标识*"], "中性笔-商品A")
        self.assertEqual(row["图片包路径*"], "中性笔/商品A")
        self.assertEqual(row["商品属性模板*"], "中性笔")

    def test_mixed_legacy_and_two_level_layout(self):
        write_mini_pack(self.root / "旧商品")
        write_mini_pack(self.root / "中性笔" / "新商品")
        synced = sync_workbook(self.root)
        rows = {row["商品标识*"]: row for row in self._titles(synced["path"])}
        self.assertEqual(set(rows), {"旧商品", "中性笔-新商品"})
        self.assertEqual(rows["旧商品"]["图片包路径*"], "旧商品")
        self.assertEqual(rows["中性笔-新商品"]["图片包路径*"], "中性笔/新商品")

    def test_selected_categories_are_persisted_and_filter_workbook(self):
        write_mini_pack(self.root / "中性笔" / "商品A")
        write_mini_pack(self.root / "修正带" / "商品B")
        first = sync_workbook(self.root, selected_categories=["中性笔"])
        self.assertEqual(first["count"], 1)
        self.assertEqual({row["商品标识*"] for row in self._titles(first["path"])}, {"中性笔-商品A"})
        again = sync_workbook(self.root)
        self.assertEqual(again["count"], 1)
        selected = {item["name"] for item in again["scan"]["categories"] if item["selected"]}
        self.assertEqual(selected, {"中性笔"})
        both = sync_workbook(self.root, selected_categories=["中性笔", "修正带"])
        self.assertEqual(both["count"], 2)

    def test_new_category_is_selected_by_default_and_unknown_template_is_reported(self):
        write_mini_pack(self.root / "中性笔" / "商品A")
        sync_workbook(self.root)
        write_mini_pack(self.root / "自定义类别" / "商品B")
        synced = sync_workbook(self.root)
        self.assertEqual(synced["count"], 2)
        custom = next(item for item in synced["scan"]["categories"] if item["name"] == "自定义类别")
        self.assertFalse(custom["template_found"])
        self.assertTrue(any(item["error"] == "未配置同名商品属性模板" for item in synced["scan"]["errors"]))

    def test_unknown_category_uses_default_template_and_can_be_validated(self):
        # 上级目录是分组名，不应被当成商品属性模板名写入总表。
        write_mini_pack(self.root / "已完成产品" / "商品A")
        synced = sync_workbook(self.root, {"品牌": "卡游"})
        rows = self._titles(synced["path"])
        self.assertEqual(synced["count"], 1)
        self.assertEqual(rows[0]["商品属性模板*"], "中性笔")
        results = workspace._seller().validate_workbook(synced["path"])
        self.assertEqual(len(results), 1)

    def test_rescan_repairs_legacy_unknown_template(self):
        write_mini_pack(self.root / "商品A")
        synced = sync_workbook(self.root, {"品牌": "卡游"})
        path = Path(synced["path"])
        wb = load_workbook(path)
        try:
            sheet = wb["商品清单"]
            headers = [cell.value for cell in sheet[1]]
            sheet.cell(2, headers.index("商品属性模板*") + 1).value = "已完成产品"
            wb.save(path)
        finally:
            wb.close()
        repaired = sync_workbook(self.root)
        row = self._titles(repaired["path"])[0]
        self.assertEqual(row["商品属性模板*"], "中性笔")
        self.assertEqual(len(workspace._seller().validate_workbook(repaired["path"])), 1)

    def test_same_name_across_category_and_legacy_layout_is_reported(self):
        write_mini_pack(self.root / "中性笔-商品A")
        write_mini_pack(self.root / "中性笔" / "商品A")
        scan = scan_workspace(self.root)
        self.assertEqual(len(scan["folders"]), 1)
        self.assertTrue(any("商品标识冲突" in item["error"] for item in scan["errors"]))


class LiveWorkspacePacksTests(unittest.TestCase):
    def test_two_real_packs_validate(self):
        packs = list_naruto_packs()
        if len(packs) < 2:
            self.skipTest("需要 testdata 里两个火影真图夹")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        try:
            link_folder(packs[0], root / "火影-001")
            link_folder(packs[1], root / "火影-002")
        except OSError as exc:
            self.skipTest(f"无法连接真图夹: {exc}")
        synced = sync_workbook(root, {
            "品牌": "卡游",
            "商品属性模板": "中性笔",
            "物流模板": "48小时",
            "销售模板": "仓库多规格",
            "价格": 9.9,
            "库存": 20,
        })
        import importlib.util
        spec = importlib.util.spec_from_file_location("seller", Path(__file__).with_name("千牛自动上架.py"))
        seller = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(seller)
        results = seller.validate_workbook(synced["path"])
        self.assertGreaterEqual(len(results), 2)
        self.assertTrue(all(item["validation"] == "通过" for item in results[:2]), results[0].get("errors"))
        self.assertTrue(results[0]["product"].get("pack_dir"))
        self.assertNotEqual(results[0]["product"]["title"], results[1]["product"]["title"])


if __name__ == "__main__":
    unittest.main()
