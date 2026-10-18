import unittest
import os
import tempfile
import json
import subprocess
from localgrep.error_decode import decode_error, format_error_decode_text, bind_sql_parameters
from localgrep.factory import inspect_model_factory, format_factory_text
from localgrep.importgraph import analyze_import_graph, format_importgraph_text
from localgrep.diff_context import extract_diff_context, format_diff_context_text
from localgrep.selftest import run_selftest, format_selftest_text

DEMO_DIR = "/home/javad/www/demo"

class TestErrorDecode(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cwd = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_decode_demo_default_log(self):
        """Test decoding storage/logs/laravel.log from demo project (100+ vendor frames, frame #4 app frame)."""
        res = decode_error("", cwd=DEMO_DIR)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["error_type"], "InvalidArgumentException")
        self.assertIn("Log [security] is not defined", res["message"])
        self.assertIsNotNone(res["innermost_frame"])
        self.assertIn("ImpersonateCustomerController.php", res["innermost_frame"]["rel_path"])
        self.assertEqual(res["innermost_frame"]["line"], 45)
        self.assertGreater(res["total_frames_count"], 90)
        self.assertGreaterEqual(res["app_frames_count"], 5)
        self.assertIn("Code Context:", format_error_decode_text(res))

    def test_decode_single_line_log_file(self):
        """Test single-line log with JSON exception object at /tmp/opencode/err.log."""
        if not os.path.isfile("/tmp/opencode/err.log"):
            self.skipTest("/tmp/opencode/err.log not present")
        res = decode_error("/tmp/opencode/err.log", cwd=DEMO_DIR)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["error_type"], "ErrorException")
        self.assertIn("Undefined property: stdClass::$gateway_code", res["message"])
        self.assertIsNotNone(res["innermost_frame"])
        self.assertIn("Daric.php", res["innermost_frame"]["rel_path"])
        self.assertEqual(res["innermost_frame"]["line"], 101)

    def test_decode_multiline_log_file(self):
        """Test multi-line log with stacktrace at /tmp/opencode/err2.log."""
        if not os.path.isfile("/tmp/opencode/err2.log"):
            self.skipTest("/tmp/opencode/err2.log not present")
        res = decode_error("/tmp/opencode/err2.log", cwd=DEMO_DIR)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["error_type"], "ErrorException")
        self.assertIn("Undefined property: stdClass::$gateway_code", res["message"])
        self.assertIn("Daric.php", res["innermost_frame"]["rel_path"])

    def test_decode_file_flags(self):
        """Test --file, -f, and --file= flags."""
        if not os.path.isfile("/tmp/opencode/err.log"):
            self.skipTest("/tmp/opencode/err.log not present")
        for flag in ["--file /tmp/opencode/err.log", "-f /tmp/opencode/err.log", "--file=/tmp/opencode/err.log", "-f=/tmp/opencode/err.log"]:
            res = decode_error(flag, cwd=DEMO_DIR)
            self.assertEqual(res["status"], "ok", f"Failed for flag: {flag}")
            self.assertEqual(res["error_type"], "ErrorException")

    def test_decode_piped_raw_log_line(self):
        """Test piping a raw log line with embedded path without treating it as missing file."""
        log_line = '[2026-10-18 12:00:00] production.ERROR: Undefined property: stdClass::$gateway_code {"exception":"[object] (ErrorException(code: 0): Undefined property at /home/javad/www/demo/vendor/bina/ecommerce/app/Drivers/Daric.php:101)"}'
        res = decode_error(log_line, cwd=DEMO_DIR)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["error_type"], "ErrorException")
        self.assertIn("Undefined property: stdClass::$gateway_code", res["message"])
        self.assertIn("Daric.php", res["innermost_frame"]["rel_path"])

    def test_decode_sql_query_and_bindings(self):
        """Test SQL query exception with bindings interpolation."""
        sql_log = "SQLSTATE[42S22]: Column not found: 1054 Unknown column 'sku' in 'where clause' (SQL: select * from products where sku = ? and store_id = ?) [bindings: ['PROD-999', 5]]"
        res = decode_error(sql_log, cwd=self.cwd)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["error_type"], "QueryException")
        self.assertIn("select * from products where sku = 'PROD-999' and store_id = '5'", res["sql_query"])

    def test_decode_python_traceback(self):
        """Test Python traceback parsing where the deepest frame is selected."""
        py_trace = """Traceback (most recent call last):
  File "/home/javad/www/demo/scripts/runner.py", line 45, in main
    execute_step()
  File "/home/javad/www/demo/app/Services/Processor.py", line 88, in execute_step
    raise ValueError("Invalid configuration payload provided")
ValueError: Invalid configuration payload provided
"""
        res = decode_error(py_trace, cwd=DEMO_DIR)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["error_type"], "ValueError")
        self.assertIn("Invalid configuration payload provided", res["message"])
        self.assertIsNotNone(res["innermost_frame"])
        self.assertIn("Processor.py", res["innermost_frame"]["rel_path"])
        self.assertEqual(res["innermost_frame"]["line"], 88)

    def test_decode_non_error_honest_rejection(self):
        """Anti-pattern test: Non-error text must return status error, never a fake Exception card."""
        res = decode_error("This is just some random debugging text without error signatures", cwd=self.cwd)
        self.assertEqual(res["status"], "error")
        self.assertIn("does not appear to contain a recognized error", res["message"])

    def test_decode_missing_file(self):
        """Missing file must return clean error status."""
        res = decode_error("/tmp/definitely_missing_file_12345.log", cwd=self.cwd)
        self.assertEqual(res["status"], "error")
        self.assertIn("Specified log file not found", res["message"])

    def test_decode_empty_file(self):
        """Empty log file must return clean error status."""
        empty_path = os.path.join(self.cwd, "empty.log")
        open(empty_path, "w").close()
        res = decode_error(empty_path, cwd=self.cwd)
        self.assertEqual(res["status"], "error")
        self.assertIn("Log file is empty", res["message"])

    def test_decode_info_only_file(self):
        """Log file with only INFO messages must return honest error."""
        info_path = os.path.join(self.cwd, "info.log")
        with open(info_path, "w") as f:
            f.write("[2026-10-18 10:00:00] local.INFO: Everything running fine.\n")
        res = decode_error(info_path, cwd=self.cwd)
        self.assertEqual(res["status"], "error")
        self.assertIn("No error or exception entries detected", res["message"])


class TestFactory(unittest.TestCase):
    def test_factory_user_core(self):
        """Test core User model factory discovery and attribute extraction."""
        res = inspect_model_factory("User", cwd=DEMO_DIR)
        self.assertEqual(res["status"], "ok")
        self.assertTrue(res["model"].endswith("User"))
        self.assertIn("UserFactory.php", res["factory_file"])
        self.assertIn("name", res["definition_attributes"])
        self.assertIn("email", res["definition_attributes"])
        state_names = [s["method"] for s in res["states"]]
        self.assertIn("unverified", state_names)
        self.assertIn("=== Model Factory:", format_factory_text(res))

    def test_factory_vendor_module(self):
        """Test vendor/bina module Order model factory discovery."""
        res = inspect_model_factory("Order", cwd=DEMO_DIR)
        self.assertEqual(res["status"], "ok")
        self.assertTrue(res["model"].endswith("Order"))
        self.assertIn("vendor/bina", res["factory_file"])

    def test_factory_not_found_with_suggestions(self):
        """Test suggestions when model factory is not found."""
        res = inspect_model_factory("Usr", cwd=DEMO_DIR)
        self.assertEqual(res["status"], "error")
        self.assertIn("User", res["suggestions"])
        self.assertIn("Suggestions:", format_factory_text(res))


class TestImportGraph(unittest.TestCase):
    def test_importgraph_ts_composable(self):
        """Test AST consumer extraction on TypeScript composable."""
        res = analyze_import_graph("resources/js/composables/useMarkdown.ts", cwd=DEMO_DIR)
        self.assertEqual(res["status"], "ok")
        self.assertTrue(res["is_frontend"])
        self.assertIn("parseMarkdown", res["exports"])
        self.assertGreater(res["total_consumers"], 50)
        self.assertIn("Import Graph", format_importgraph_text(res))

    def test_importgraph_vue_component(self):
        """Test AST dependency extraction on Vue SFC component."""
        res = analyze_import_graph("resources/js/Pages/Ecommerce/Admin/PaymentGateways.vue", cwd=DEMO_DIR)
        self.assertEqual(res["status"], "ok")
        self.assertTrue(res["is_frontend"])
        self.assertGreater(len(res["dependencies"]), 0)

    def test_importgraph_nonexistent_file(self):
        """Test error handling on nonexistent file."""
        res = analyze_import_graph("resources/js/nonexistent_file_xyz.ts", cwd=DEMO_DIR)
        self.assertEqual(res["status"], "error")
        self.assertIn("not found", res["message"].lower())


class TestDiffContext(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cwd = self.temp_dir.name
        # Initialize a temporary git repository
        subprocess.run(["git", "init"], cwd=self.cwd, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=self.cwd, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.cwd, check=True)

        self.php_file = os.path.join(self.cwd, "UserService.php")
        with open(self.php_file, "w") as f:
            f.write("""<?php
namespace App\\Services;

class UserService
{
    public function findUserById(int $id)
    {
        $a = 1;
        return $a;
    }
}
""")
        subprocess.run(["git", "add", "UserService.php"], cwd=self.cwd, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.cwd, check=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_diff_context_enclosing_function_php(self):
        """Test that diff hunk accurately detects enclosing class and method signature."""
        with open(self.php_file, "w") as f:
            f.write("""<?php
namespace App\\Services;

class UserService
{
    public function findUserById(int $id)
    {
        $a = 1;
        $modified_var = 42;
        return $a + $modified_var;
    }
}
""")
        res = extract_diff_context(cwd=self.cwd)
        self.assertEqual(res["status"], "ok")
        self.assertGreater(res["files_count"], 0)
        hunk = res["files"][0]["hunks"][0]
        self.assertIn("findUserById", hunk["enclosing"])
        text = format_diff_context_text(res)
        self.assertIn("UserService.php", text)
        self.assertIn("findUserById", text)


class TestSelfTest(unittest.TestCase):
    def test_selftest_execution(self):
        """Test running regression self-test suite (12/12 passing)."""
        res = run_selftest(cwd=DEMO_DIR)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["failed"], 0)
        self.assertEqual(res["total_tests"], 12)
        self.assertEqual(res["passed"], 12)
        self.assertLess(res["total_duration_ms"], 6000)
        text = format_selftest_text(res)
        self.assertIn("PASS (12/12 passed", text)

if __name__ == "__main__":
    unittest.main()
