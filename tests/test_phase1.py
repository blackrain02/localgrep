import unittest
import os
from localgrep.contract import extract_vue_contract, extract_php_contract, extract_ts_js_contract
from localgrep.router import parse_route_line
from localgrep.topo import get_project_topology

class TestPhase1(unittest.TestCase):
    def test_vue_contract_extraction(self):
        vue_code = """
<template>
  <div>
    <slot name="header"></slot>
  </div>
</template>
<script setup lang="ts">
interface Props {
  title: string;
  count?: number;
}
const props = defineProps<Props>();
const emit = defineEmits<{ (e: 'submit', val: string): void }>();
const model = defineModel<string>();
</script>
        """
        contract = extract_vue_contract(vue_code)
        self.assertIn("defineProps", contract)
        self.assertIn("defineEmits", contract)
        self.assertIn("defineModel", contract)
        self.assertIn("header", contract)

    def test_php_contract_extraction(self):
        php_code = """<?php
namespace App\\Services;
class PaymentService implements PaymentInterface {
    public int $timeout = 30;
    protected string $secret = 'hidden';
    public function __construct(public Gateway $gateway) {}
    public function process(Order $order): bool {
        return true;
    }
    private function internalHelper() {}
}
        """
        contract = extract_php_contract(php_code)
        self.assertIn("class PaymentService", contract)
        self.assertIn("public int $timeout", contract)
        self.assertIn("public function process(Order $order): bool", contract)
        self.assertNotIn("internalHelper", contract)
        self.assertNotIn("hidden", contract)

    def test_ts_contract_extraction(self):
        ts_code = """
export interface User { id: number; name: string; }
export const DEFAULT_TIMEOUT = 5000;
export function calculate(a: number, b: number): number {
    return a + b;
}
        """
        contract = extract_ts_js_contract(ts_code)
        self.assertIn("interface User", contract)
        self.assertIn("DEFAULT_TIMEOUT", contract)
        self.assertIn("calculate", contract)

    def test_route_line_parsing(self):
        line = "Route::get('orders/{id}', [OrderController::class, 'show'])->name('orders.show');"
        parsed = parse_route_line(line, "routes/web.php", 10, "/tmp")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["method"], "GET")
        self.assertEqual(parsed["uri"], "/orders/{id}")
        self.assertEqual(parsed["name"], "orders.show")
        self.assertEqual(parsed["controller"], "OrderController")
        self.assertEqual(parsed["action"], "show")

    def test_topo_extraction(self):
        topo = get_project_topology(os.getcwd())
        self.assertEqual(topo["status"], "ok")
        self.assertIn("framework", topo)
        self.assertIn("card", topo)

if __name__ == "__main__":
    unittest.main()
