import unittest
import os
import tempfile
from localgrep.slice import extract_file_slice
from localgrep.lint_fast import lint_fast_file
from localgrep.test_map import map_test_for_file
from localgrep.sample import get_sample_record, format_sample_text
from localgrep.impact import calculate_impact, format_impact_text
from localgrep.error_decode import decode_error, format_error_decode_text, bind_sql_parameters
from localgrep.env_audit import audit_environment, format_env_audit_text
from localgrep.state_map import generate_state_map, format_state_map_text
from localgrep.api_shape import synthesize_api_shape, format_api_shape_text

class TestLocalGrepImprovements(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cwd = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_slice_php(self):
        php_code = """<?php
namespace App\\Services;

class DummyService
{
    private $prop = 1;

    public function otherMethod()
    {
        $a = 1;
        $b = 2;
        return $a + $b;
    }

    public function targetMethod($x)
    {
        return $x * 2;
    }
}
"""
        filepath = os.path.join(self.cwd, "DummyService.php")
        with open(filepath, "w") as f:
            f.write(php_code)

        res = extract_file_slice("DummyService.php", "targetMethod", cwd=self.cwd)
        self.assertEqual(res["status"], "ok")
        self.assertIn("targetMethod", res["skeleton"])
        self.assertIn("pruned", res["skeleton"])
        self.assertIn("%", res["saving_pct"])

    def test_lint_fast_php(self):
        clean_code = "<?php echo 'Hello World';\n"
        filepath = os.path.join(self.cwd, "Clean.php")
        with open(filepath, "w") as f:
            f.write(clean_code)

        res = lint_fast_file("Clean.php", cwd=self.cwd)
        self.assertEqual(res["status"], "clean")
        self.assertEqual(res["issues_count"], 0)

        broken_code = "<?php echo 'Missing semicolon'\n"
        b_filepath = os.path.join(self.cwd, "Broken.php")
        with open(b_filepath, "w") as f:
            f.write(broken_code)

        res_broken = lint_fast_file("Broken.php", cwd=self.cwd)
        self.assertNotEqual(res_broken["status"], "clean")
        self.assertGreater(res_broken["issues_count"], 0)

    def test_error_decode_sql(self):
        raw_error = """SQLSTATE[23505]: Unique violation (SQL: insert into "users" ("email") values (?)) [bindings: ["foo@bar.com"]]
#0 /app/vendor/laravel/framework/src/Illuminate/Database/Connection.php(418): execute()
#1 /app/app/Services/UserService.php(42): insert()
#2 /app/vendor/laravel/framework/src/Illuminate/Pipeline/Pipeline.php(100): then()"""
        res = decode_error(raw_error, cwd=self.cwd)
        self.assertEqual(res["status"], "ok")
        self.assertIn("'foo@bar.com'", res["sql_query"])
        self.assertEqual(res["innermost_frame"]["line"], 42)
        self.assertIn("UserService.php", res["innermost_frame"]["path"])

    def test_bind_sql_parameters(self):
        sql = "select * from users where id = ? and email = ? and is_admin = ? and notes = ?"
        bindings = '[1, "admin@demo.com", true, null]'
        bound = bind_sql_parameters(sql, bindings)
        self.assertEqual(bound, "select * from users where id = 1 and email = 'admin@demo.com' and is_admin = True and notes = NULL")

    def test_env_audit(self):
        env_content = "APP_KEY=base64:12345678901234567890123456789012\nAPP_ENV=local\nDB_CONNECTION=sqlite\nDB_DATABASE=:memory:\n"
        with open(os.path.join(self.cwd, ".env"), "w") as f:
            f.write(env_content)

        res = audit_environment(cwd=self.cwd)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["errors_count"], 0)

    def test_state_map(self):
        vue_code = """<template><div>{{ isBundle }}</div></template>
<script setup>
import { ref, computed } from 'vue';
const props = defineProps({
    model: Object,
    active: Boolean
});
const count = ref(0);
const isBundle = computed(() => props.model?.type === 'bundle');
</script>"""
        v_path = os.path.join(self.cwd, "TestComp.vue")
        with open(v_path, "w") as f:
            f.write(vue_code)

        res = generate_state_map("TestComp.vue", cwd=self.cwd)
        self.assertEqual(res["status"], "ok")
        self.assertIn("model", res["props"])
        self.assertIn("count", res["refs"])
        self.assertIn("isBundle", res["computeds"])
        self.assertTrue(any("isBundle" in chain[1] for chain in res["flow_chains"]))

    def test_extract_declaration_block(self):
        from localgrep.chunker import extract_declaration_block
        lines = [
            "// A comment\n",
            "const isVideoLastIndex = computed(() => !isEmpty(Settings?.product?.isVideoLastIndex) && Settings?.product?.isVideoLastIndex === true);\n",
            "const otherVar = 1;\n"
        ]
        start_l, end_l, text = extract_declaration_block(lines, 1)
        self.assertEqual(start_l, 2)
        self.assertEqual(end_l, 2)
        self.assertIn("isVideoLastIndex", text)

    def test_vue_single_line_declaration_chunks(self):
        from localgrep.chunker import chunk_vue_file
        lines = [
            "<template><div>{{ test }}</div></template>\n",
            "<script setup>\n",
            "import { computed } from 'vue';\n",
            "const isVideoLastIndex = computed(() => true);\n",
            "const galleryItems = computed(() => {\n",
            "    return [1, 2, 3];\n",
            "});\n",
            "</script>\n"
        ]
        chunks = chunk_vue_file(lines)
        names = [c.get("name") for c in chunks if c.get("name")]
        self.assertIn("isVideoLastIndex", names)
        self.assertIn("galleryItems", names)

if __name__ == "__main__":
    unittest.main()
