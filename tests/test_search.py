import unittest
from localgrep.daemon import extract_search_terms, extract_meaningful_file_snippet
from localgrep.chunker import chunk_file

class TestSearchTerms(unittest.TestCase):
    def test_camel_case_splitting(self):
        terms = extract_search_terms("userProfileHeader")
        self.assertIn("user", terms)
        self.assertIn("profile", terms)
        self.assertIn("header", terms)

    def test_kebab_case_splitting(self):
        terms = extract_search_terms("comment-item-info")
        self.assertIn("comment", terms)
        self.assertIn("item", terms)
        self.assertIn("info", terms)

    def test_stop_words_filtered(self):
        terms = extract_search_terms("where is the code for payment")
        self.assertNotIn("where", terms)
        self.assertNotIn("code", terms)
        self.assertIn("payment", terms)

    def test_non_latin_query_returns_empty(self):
        # Non-Latin queries must return empty terms rather than fabricating default terms
        terms = extract_search_terms("پرداخت آنلاین سفارش")
        self.assertEqual(terms, [])

    def test_compound_method_preserved(self):
        terms = extract_search_terms("product search published orWhereHas bug")
        self.assertIn("orwherehas", terms)
        self.assertIn("published", terms)
        self.assertIn("product", terms)

    def test_meta_programming_words_filtered(self):
        terms = extract_search_terms("function recalculates variation prices")
        self.assertNotIn("function", terms)
        self.assertIn("recalculates", terms)
        self.assertIn("variation", terms)
        self.assertIn("prices", terms)

class TestMorphologicalStemmingAndTaxonomy(unittest.TestCase):
    def test_stem_word(self):
        from localgrep.daemon import stem_word
        stems_recalc = stem_word("recalculates")
        self.assertIn("recalculate", stems_recalc)
        self.assertIn("calculate", stems_recalc)
        self.assertIn("recalc", stems_recalc)

        stems_prices = stem_word("prices")
        self.assertIn("price", stems_prices)

        stems_published = stem_word("published")
        self.assertIn("publish", stems_published)

    def test_expand_search_terms(self):
        from localgrep.daemon import expand_search_terms
        terms = ["recalculates", "variation", "prices"]
        expanded = expand_search_terms(terms)
        self.assertIn("recalculate", expanded)
        self.assertIn("variant", expanded)
        self.assertIn("price", expanded)

        terms_s2 = ["published", "orwherehas", "bug"]
        expanded_s2 = expand_search_terms(terms_s2)
        self.assertIn("publish", expanded_s2)
        self.assertIn("wherehas", expanded_s2)
        self.assertIn("issue", expanded_s2)

class TestChunker(unittest.TestCase):
    def test_php_free_function_chunking(self):
        php_lines = [
            "<?php\n",
            "function standalone_helper($arg) {\n",
            "    return $arg * 2;\n",
            "}\n",
            "class Sample {\n",
            "    public function methodOne() {\n",
            "        return 1;\n",
            "    }\n",
            "}\n"
        ]
        chunks = chunk_file("helpers.php", php_lines)
        kinds = [c["kind"] for c in chunks]
        self.assertIn("ast_function_definition", kinds)
        self.assertIn("ast_class_declaration", kinds)
        self.assertIn("ast_method_declaration", kinds)

    def test_vue_sfc_chunking(self):
        vue_lines = [
            "<template>\n",
            "  <div><h1>{{ title }}</h1></div>\n",
            "</template>\n",
            "<script setup lang=\"ts\">\n",
            "import { ref } from 'vue'\n",
            "const title = ref('Hello')\n",
            "function handleClick() {\n",
            "    console.log('clicked')\n",
            "}\n",
            "</script>\n"
        ]
        chunks = chunk_file("Component.vue", vue_lines)
        self.assertTrue(len(chunks) >= 2)
        kinds = [c["kind"] for c in chunks]
        self.assertTrue(any("vue_function_declaration" in k or "vue_ast" in k for k in kinds))

if __name__ == "__main__":
    unittest.main()
