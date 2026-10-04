import unittest
import os
from localgrep.contract import extract_vue_contract, extract_php_contract, extract_ts_js_contract
from localgrep.router import (
    parse_route_line,
    parse_route_block,
    parse_use_statements,
    resolve_controller_action
)
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
const props = withDefaults(defineProps<Props>(), {
  count: 0
});
const emit = defineEmits<{ (e: 'submit', val: string): void }>();
const model = defineModel<string>();

onMounted(() => {
  console.log("internal mounted implementation");
});
</script>
        """
        contract = extract_vue_contract(vue_code)
        self.assertIn("defineProps", contract)
        self.assertIn("withDefaults", contract)
        self.assertIn("defineEmits", contract)
        self.assertIn("defineModel", contract)
        self.assertIn("header", contract)
        self.assertIn("interface Props", contract)
        self.assertNotIn("onMounted", contract)
        self.assertNotIn("internal mounted implementation", contract)

    def test_vue_contract_full_extraction(self):
        vue_code = """
<template>
  <div><slot name="content" /></div>
</template>
<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue';

const count = ref(0);
const double = computed(() => count.value * 2);

watch(count, (newVal) => {
  console.log(newVal);
});

onMounted(() => {
  fetchData();
});
onUnmounted(() => {
  cleanup();
});
</script>
        """
        contract = extract_vue_contract(vue_code, full=True)
        self.assertIn("count (ref)", contract)
        self.assertIn("double (computed)", contract)
        self.assertIn("Lifecycle Hooks:", contract)
        self.assertIn("onMounted: calls [fetchData]", contract)
        self.assertIn("onUnmounted", contract)
        self.assertIn("Watchers: count", contract)

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

    def test_php_contract_full_extraction(self):
        php_code = """<?php
namespace App\\Models;
class Invoice extends Model {
    use HasFactory, SoftDeletes;
    protected $casts = ['is_paid' => 'boolean'];
    protected $fillable = ['number', 'amount'];
    public function markAsPaid(): bool { return true; }
    protected function booted(): void {}
}
        """
        contract = extract_php_contract(php_code, full=True)
        self.assertIn("class Invoice", contract)
        self.assertIn("use HasFactory, SoftDeletes;", contract)
        self.assertIn("$casts", contract)
        self.assertIn("$fillable", contract)
        self.assertIn("public function markAsPaid(): bool", contract)
        self.assertIn("protected function booted(): void", contract)

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

    def test_route_single_line_parsing(self):
        line = "Route::get('orders/{id}', [OrderController::class, 'show'])->name('orders.show');"
        parsed = parse_route_line(line, "routes/web.php", 10, "/tmp")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["method"], "GET")
        self.assertEqual(parsed["uri"], "/orders/{id}")
        self.assertEqual(parsed["name"], "orders.show")
        self.assertEqual(parsed["controller"], "OrderController")
        self.assertEqual(parsed["action"], "show")

    def test_route_multiline_block_parsing(self):
        block = """Route::post('conversations/{id}/toggle-auto-approve', [
            AgentController::class,
            'toggleAutoApprove'
        ])->name('intelligence.agents.toggle_auto_approve');"""
        parsed_items = parse_route_block(block, "routes/web.php", 30)
        self.assertEqual(len(parsed_items), 1)
        r = parsed_items[0]
        self.assertEqual(r["method"], "POST")
        self.assertEqual(r["uri"], "/conversations/{id}/toggle-auto-approve")
        self.assertEqual(r["name"], "intelligence.agents.toggle_auto_approve")
        self.assertEqual(r["controller"], "AgentController")
        self.assertEqual(r["action"], "toggleAutoApprove")

    def test_route_match_parsing(self):
        block = "Route::match(['put', 'patch'], 'vendors/{vendor}/media', [MediaController::class, 'vendor'])->name('vendors.media');"
        parsed_items = parse_route_block(block, "routes/web.php", 106)
        self.assertEqual(len(parsed_items), 1)
        r = parsed_items[0]
        self.assertEqual(r["method"], "PUT|PATCH")
        self.assertEqual(r["uri"], "/vendors/{vendor}/media")
        self.assertEqual(r["name"], "vendors.media")
        self.assertEqual(r["controller"], "MediaController")
        self.assertEqual(r["action"], "vendor")

    def test_route_resource_expansion(self):
        block = "Route::resource('accounts', Ctrl\\AccountController::class)->only(['index', 'store', 'destroy']);"
        parsed_items = parse_route_block(block, "routes/admin.php", 19, uri_prefix="admin", name_prefix="admin.")
        self.assertEqual(len(parsed_items), 3)
        actions = {r["action"]: r for r in parsed_items}
        self.assertIn("index", actions)
        self.assertEqual(actions["index"]["method"], "GET")
        self.assertEqual(actions["index"]["uri"], "/admin/accounts")
        self.assertEqual(actions["index"]["name"], "admin.accounts.index")

        self.assertIn("store", actions)
        self.assertEqual(actions["store"]["method"], "POST")
        self.assertEqual(actions["store"]["uri"], "/admin/accounts")
        self.assertEqual(actions["store"]["name"], "admin.accounts.store")

        self.assertIn("destroy", actions)
        self.assertEqual(actions["destroy"]["method"], "DELETE")
        self.assertEqual(actions["destroy"]["uri"], "/admin/accounts/{account}")
        self.assertEqual(actions["destroy"]["name"], "admin.accounts.destroy")

    def test_use_statements_parser(self):
        code = """
        use Modules\\Ecommerce\\Http\\Controllers\\General\\XHRController;
        use Modules\\Accounting\\Http\\Controllers\\Admin as Ctrl;
        """
        uses = parse_use_statements(code)
        self.assertEqual(uses["XHRController"], "Modules\\Ecommerce\\Http\\Controllers\\General\\XHRController")
        self.assertEqual(uses["Ctrl"], "Modules\\Accounting\\Http\\Controllers\\Admin")

    def test_topo_extraction(self):
        topo = get_project_topology(os.getcwd())
        self.assertEqual(topo["status"], "ok")
        self.assertIn("framework", topo)
        self.assertIn("card", topo)

    def test_inertia_page_route_resolution(self):
        from localgrep.router import lookup_route
        res = lookup_route("contact", "/home/javad/www/demo")
        self.assertEqual(res["status"], "ok")
        self.assertTrue(len(res["results"]) > 0)
        # Check that contact-us route found and rendered Inertia component
        found_inertia = any(r.get("inertia_file") for r in res["results"])
        self.assertTrue(found_inertia)

if __name__ == "__main__":
    unittest.main()
