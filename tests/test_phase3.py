import unittest
import tempfile
import os
from localgrep.verify_patch import verify_patch
from localgrep.audit_diff import audit_diff
from localgrep.test_isolate import parse_test_output

class TestPhase3(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.test_dir.cleanup()

    # --- verify_patch tests ---
    def test_verify_patch_exact_match(self):
        sample_file = os.path.join(self.test_dir.name, "Sample.php")
        with open(sample_file, "w") as f:
            f.write("<?php\n\nclass Sample {\n    public function test(): void {\n        echo 'hello';\n    }\n}\n")

        target = "    public function test(): void {\n        echo 'hello';\n    }"
        res = verify_patch(sample_file, target)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["match_type"], "exact")
        self.assertEqual(res["start_line"], 4)
        self.assertEqual(res["end_line"], 6)
        self.assertEqual(res["tool_args"]["StartLine"], 4)
        self.assertEqual(res["tool_args"]["EndLine"], 6)

    def test_verify_patch_ambiguous(self):
        sample_file = os.path.join(self.test_dir.name, "Repeated.php")
        with open(sample_file, "w") as f:
            f.write("line 1\nrepeat\nline 3\nrepeat\nline 5\n")

        res = verify_patch(sample_file, "repeat")
        self.assertEqual(res["status"], "ambiguous")
        self.assertEqual(res["matches_count"], 2)

    def test_verify_patch_whitespace_mismatch(self):
        sample_file = os.path.join(self.test_dir.name, "Indent.vue")
        with open(sample_file, "w") as f:
            f.write("<template>\n  <div>\n    <span>Hello</span>\n  </div>\n</template>\n")

        # Wrong indentation (no indentation)
        target = "<div>\n<span>Hello</span>\n</div>"
        res = verify_patch(sample_file, target)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["match_type"], "whitespace_corrected")
        self.assertEqual(res["start_line"], 2)
        self.assertEqual(res["end_line"], 4)
        self.assertIn("  <div>\n    <span>Hello</span>\n  </div>", res["target_content"])

    def test_verify_patch_not_found(self):
        sample_file = os.path.join(self.test_dir.name, "Sample.php")
        with open(sample_file, "w") as f:
            f.write("<?php\nfunction foo() {}\n")

        res = verify_patch(sample_file, "non_existent_function_name()")
        self.assertEqual(res["status"], "not_found")
        self.assertFalse(res["found"])

    # --- test_isolate tests ---
    def test_test_isolate_pest_failure(self):
        raw_output = """
   FAIL  Tests\\Feature\\OrderTest
  ⨯ it calculates order total correctly                                   0.04s  
  ─────────────────────────────────────────────────────────────────────────────  
   FAILED  Tests\\Feature\\OrderTest > it calculates order total correctly  
  Failed asserting that 1500 matches expected 2000.

  at tests/Feature/OrderTest.php:45
     41▕     $order = Order::factory()->create();
     42▕     $calculator = new OrderCalculator($order);
     43▕     $total = $calculator->total();
     44▕ 
  ➜  45▕     $this->assertEquals(2000, $total);
     46▕ 

  Tests:    1 failed, 14 passed (15 assertions)
  Duration: 0.18s
"""
        res = parse_test_output(raw_output)
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["failed_count"], 1)
        self.assertEqual(res["passed_count"], 14)
        fail = res["failures"][0]
        self.assertIn("Tests\\Feature\\OrderTest > it calculates order total correctly", fail["test"])
        self.assertEqual(fail["file"], "tests/Feature/OrderTest.php")
        self.assertEqual(fail["line"], 45)
        self.assertIn("Failed asserting that 1500 matches expected 2000", fail["reason"])

    def test_test_isolate_passed(self):
        raw_output = """
   PASS  Tests\\Unit\\MathTest
  ✓ it adds numbers                                                       0.01s  

  Tests:    10 passed (10 assertions)
  Duration: 0.05s
"""
        res = parse_test_output(raw_output)
        self.assertEqual(res["status"], "passed")
        self.assertEqual(res["passed_count"], 10)
        self.assertEqual(res["failed_count"], 0)

if __name__ == "__main__":
    unittest.main()
