import unittest

from app.utils import (
    get_display_label,
    normalize_label_name,
    should_display_violation_overlay,
)


class LabelUtilsTestCase(unittest.TestCase):
    def test_aliases_normalize_to_expected_keys(self) -> None:
        self.assertEqual(normalize_label_name("hardhat"), "helmet")
        self.assertEqual(normalize_label_name("novest"), "no_vest")
        self.assertEqual(normalize_label_name("nohelmet"), "no_helmet")
        self.assertEqual(normalize_label_name("smoke"), "smoking")

    def test_display_labels_are_localized(self) -> None:
        self.assertEqual(get_display_label("smoking"), "抽烟行为")
        self.assertEqual(get_display_label("no_vest"), "无反光背心")
        self.assertEqual(get_display_label("novest"), "无反光背心")
        self.assertEqual(get_display_label("no_helmet"), "无安全帽")
        self.assertEqual(get_display_label("nohelmet"), "无安全帽")
        self.assertEqual(get_display_label("helmet"), "安全帽")
        self.assertEqual(get_display_label("vest"), "反光背心")
        self.assertEqual(get_display_label("person"), "人员")

    def test_only_violation_classes_are_drawn(self) -> None:
        self.assertTrue(should_display_violation_overlay("smoking"))
        self.assertTrue(should_display_violation_overlay("novest"))
        self.assertTrue(should_display_violation_overlay("nohelmet"))
        self.assertFalse(should_display_violation_overlay("person"))
        self.assertFalse(should_display_violation_overlay("helmet"))
        self.assertFalse(should_display_violation_overlay("vest"))


if __name__ == "__main__":
    unittest.main()
