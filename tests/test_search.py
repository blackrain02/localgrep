import unittest
from localgrep.daemon import extract_search_terms

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

if __name__ == "__main__":
    unittest.main()
