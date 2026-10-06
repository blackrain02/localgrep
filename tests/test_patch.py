import os
import unittest
import tempfile
import subprocess
from localgrep.patch import apply_patch

class TestLocalGrepPatch(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cwd = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_exact_match_python(self):
        py_code = """def calculate_total(price, tax):
    subtotal = price + tax
    return subtotal
"""
        filepath = os.path.join(self.cwd, "calc.py")
        with open(filepath, "w") as f:
            f.write(py_code)

        search = "    subtotal = price + tax\n    return subtotal"
        replace = "    subtotal = price + tax\n    discount = 5\n    return subtotal - discount"

        res = apply_patch("calc.py", search, replace, cwd=self.cwd)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["match_type"], "exact")
        self.assertEqual(res["start_line"], 2)
        self.assertEqual(res["end_line"], 3)

        with open(filepath, "r") as f:
            updated = f.read()
        self.assertIn("discount = 5", updated)

    def test_02_whitespace_tab_space_mismatch_php(self):
        # File has tabs
        php_code = "<?php\nclass Order {\n\tpublic function getTotal() {\n\t\t$price = 100;\n\t\treturn $price;\n\t}\n}\n"
        filepath = os.path.join(self.cwd, "Order.php")
        with open(filepath, "w") as f:
            f.write(php_code)

        # Agent provides spaces instead of tabs
        search_with_spaces = "        $price = 100;\n        return $price;"
        replace_with_spaces = "        $price = 150;\n        return $price;"

        res = apply_patch("Order.php", search_with_spaces, replace_with_spaces, cwd=self.cwd)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["match_type"], "fuzzy_whitespace")
        self.assertEqual(res["start_line"], 4)
        self.assertEqual(res["end_line"], 5)

        with open(filepath, "r") as f:
            updated = f.read()
        # Verify it retained tabs in file!
        self.assertIn("\t\t$price = 150;", updated)

    def test_03_dry_run_no_disk_change(self):
        py_code = "x = 10\ny = 20\n"
        filepath = os.path.join(self.cwd, "dry.py")
        with open(filepath, "w") as f:
            f.write(py_code)

        res = apply_patch("dry.py", "x = 10", "x = 999", cwd=self.cwd, dry_run=True)
        self.assertEqual(res["status"], "ok")
        self.assertTrue(res["dry_run"])

        with open(filepath, "r") as f:
            content = f.read()
        self.assertIn("x = 10", content)
        self.assertNotIn("x = 999", content)

    def test_04_php_syntax_guard_rollback(self):
        php_code = "<?php\nfunction add($a, $b) {\n    return $a + $b;\n}\n"
        filepath = os.path.join(self.cwd, "Math.php")
        with open(filepath, "w") as f:
            f.write(php_code)

        # Broken PHP syntax (missing semicolon and unclosed paren)
        search = "    return $a + $b;"
        broken_replace = "    return $a + ($b"

        res = apply_patch("Math.php", search, broken_replace, cwd=self.cwd)
        self.assertEqual(res["status"], "syntax_error")
        self.assertTrue(res["rolled_back"])

        with open(filepath, "r") as f:
            content = f.read()
        self.assertIn("return $a + $b;", content)

    def test_05_force_override_syntax_error(self):
        php_code = "<?php\nfunction add($a, $b) {\n    return $a + $b;\n}\n"
        filepath = os.path.join(self.cwd, "MathForce.php")
        with open(filepath, "w") as f:
            f.write(php_code)

        search = "    return $a + $b;"
        broken_replace = "    return $a + ($b"

        res = apply_patch("MathForce.php", search, broken_replace, cwd=self.cwd, force=True)
        self.assertEqual(res["status"], "ok")

        with open(filepath, "r") as f:
            content = f.read()
        self.assertIn("return $a + ($b", content)

    def test_06_python_syntax_guard(self):
        py_code = "def greet(name):\n    print(f'Hello {name}')\n"
        filepath = os.path.join(self.cwd, "greet.py")
        with open(filepath, "w") as f:
            f.write(py_code)

        broken_search = "    print(f'Hello {name}')"
        broken_replace = "    print('Hello' name"

        res = apply_patch("greet.py", broken_search, broken_replace, cwd=self.cwd)
        self.assertEqual(res["status"], "syntax_error")
        self.assertIn("SyntaxError", res["error_detail"])

        with open(filepath, "r") as f:
            content = f.read()
        self.assertIn("print(f'Hello {name}')", content)

    def test_07_vue_tag_balance_guard(self):
        vue_code = """<template>
  <div class="box">
    <span>Content</span>
  </div>
</template>
<script setup>
const a = 1;
</script>
"""
        filepath = os.path.join(self.cwd, "Comp.vue")
        with open(filepath, "w") as f:
            f.write(vue_code)

        # Broken Vue template tag (close div with span)
        search = "  <div class=\"box\">\n    <span>Content</span>\n  </div>"
        broken = "  <div class=\"box\">\n    <span>Content</span>\n  </section>"

        res = apply_patch("Comp.vue", search, broken, cwd=self.cwd)
        self.assertEqual(res["status"], "syntax_error")

        with open(filepath, "r") as f:
            content = f.read()
        self.assertIn("</div>", content)

    def test_08_ambiguous_non_unique_match(self):
        code = "item = 1\n# middle\nitem = 1\n"
        filepath = os.path.join(self.cwd, "dup.py")
        with open(filepath, "w") as f:
            f.write(code)

        res = apply_patch("dup.py", "item = 1", "item = 2", cwd=self.cwd)
        self.assertEqual(res["status"], "ambiguous")
        self.assertEqual(res["matches_count"], 2)

    def test_09_not_found_target(self):
        code = "a = 1\nb = 2\n"
        filepath = os.path.join(self.cwd, "simple.py")
        with open(filepath, "w") as f:
            f.write(code)

        res = apply_patch("simple.py", "c = 99", "c = 100", cwd=self.cwd)
        self.assertEqual(res["status"], "not_found")

    def test_10_auto_indentation_adaptation(self):
        # Deeply indented file
        py_code = """class Service:
    def process(self):
        if True:
            value = 10
            return value
"""
        filepath = os.path.join(self.cwd, "service.py")
        with open(filepath, "w") as f:
            f.write(py_code)

        # Agent provides flat unindented code
        search = "            value = 10\n            return value"
        flat_replace = "value = 20\nbonus = 5\nreturn value + bonus"

        res = apply_patch("service.py", search, flat_replace, cwd=self.cwd)
        self.assertEqual(res["status"], "ok")

        with open(filepath, "r") as f:
            content = f.read()

        # Check that it automatically indented the replacement to 12 spaces!
        self.assertIn("            value = 20\n            bonus = 5\n            return value + bonus", content)

if __name__ == "__main__":
    unittest.main()
