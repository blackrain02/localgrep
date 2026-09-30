import unittest
import os
import tempfile
from localgrep.callers import find_callers, get_enclosing_context
from localgrep.events import get_event_map, parse_use_statements, inspect_listener_details
from localgrep.schema import (
    to_snake_case_plural,
    resolve_model_file,
    parse_migration_columns,
    get_model_schema
)

class TestPhase2Callers(unittest.TestCase):
    def test_enclosing_context_extraction(self):
        with tempfile.NamedTemporaryFile("w", suffix=".php", delete=False) as f:
            f.write("""<?php
class OrderService {
    public function submitOrder(Order $order) {
        $total = 100;
        $order->processPayment($total);
        return true;
    }
}
""")
            temp_path = f.name

        try:
            ctx = get_enclosing_context(temp_path, 5)
            self.assertEqual(ctx, "submitOrder()")
        finally:
            os.unlink(temp_path)

    def test_callers_filters_definitions_and_comments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = os.path.join(tmpdir, "app")
            os.makedirs(src_dir)

            # File 1: Definition (should be skipped)
            with open(os.path.join(src_dir, "Service.php"), "w") as f:
                f.write("""<?php
class Service {
    // A comment mentioning executeAction()
    public function executeAction() {
        return true;
    }
}
""")

            # File 2: Invocations (should be captured)
            with open(os.path.join(src_dir, "Consumer.php"), "w") as f:
                f.write("""<?php
class Consumer {
    public function run() {
        $svc = new Service();
        $svc->executeAction();
    }
}
""")

            res = find_callers("executeAction", tmpdir)
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["total"], 1)
            self.assertEqual(len(res["results"]), 1)
            self.assertIn("Consumer.php", res["results"][0]["file"])
            self.assertEqual(res["results"][0]["context"], "run()")

class TestPhase2Events(unittest.TestCase):
    def test_use_statement_parsing(self):
        php_code = """<?php
use App\\Events\\OrderPlaced;
use App\\Listeners\\SendNotification as NotifyListener;
"""
        uses = parse_use_statements(php_code)
        self.assertEqual(uses["OrderPlaced"], "App\\Events\\OrderPlaced")
        self.assertEqual(uses["NotifyListener"], "App\\Listeners\\SendNotification")

    def test_event_map_parsing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            prov_dir = os.path.join(tmpdir, "app", "Providers")
            list_dir = os.path.join(tmpdir, "app", "Listeners")
            os.makedirs(prov_dir)
            os.makedirs(list_dir)

            # Provider
            with open(os.path.join(prov_dir, "EventServiceProvider.php"), "w") as f:
                f.write("""<?php
namespace App\\Providers;
use App\\Events\\OrderPlaced;
use App\\Listeners\\SendOrderEmail;

class EventServiceProvider {
    protected $listen = [
        OrderPlaced::class => [
            SendOrderEmail::class,
        ],
    ];
}
""")

            # Listener
            with open(os.path.join(list_dir, "SendOrderEmail.php"), "w") as f:
                f.write("""<?php
namespace App\\Listeners;
use Illuminate\\Contracts\\Queue\\ShouldQueue;

class SendOrderEmail implements ShouldQueue {
    public $queue = 'notifications';
    public function handle($event) {
        SendEmailJob::dispatch($event->order);
    }
}
""")

            res = get_event_map("", tmpdir)
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["events_count"], 1)
            self.assertIn("OrderPlaced", res["events"])
            listeners = res["events"]["OrderPlaced"]
            self.assertEqual(len(listeners), 1)
            self.assertEqual(listeners[0]["listener"], "SendOrderEmail")
            self.assertTrue(listeners[0]["queued"])
            self.assertEqual(listeners[0]["queue"], "notifications")
            self.assertIn("SendEmailJob", listeners[0]["dispatches_jobs"])

class TestPhase2Schema(unittest.TestCase):
    def test_snake_case_plural(self):
        self.assertEqual(to_snake_case_plural("User"), "users")
        self.assertEqual(to_snake_case_plural("OrderItem"), "order_items")
        self.assertEqual(to_snake_case_plural("Category"), "categories")
        self.assertEqual(to_snake_case_plural("Address"), "addresses")

    def test_model_schema_extraction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model_dir = os.path.join(tmpdir, "app", "Models")
            mig_dir = os.path.join(tmpdir, "database", "migrations")
            os.makedirs(model_dir)
            os.makedirs(mig_dir)

            # Migration
            with open(os.path.join(mig_dir, "2024_01_01_000000_create_products_table.php"), "w") as f:
                f.write("""<?php
use Illuminate\\Support\\Facades\\Schema;
use Illuminate\\Database\\Schema\\Blueprint;

Schema::create('products', function (Blueprint $table) {
    $table->id();
    $table->string('title')->index();
    $table->decimal('price', 10, 2);
    $table->boolean('is_active')->default(true);
    $table->timestamps();
});
""")

            # Model
            with open(os.path.join(model_dir, "Product.php"), "w") as f:
                f.write("""<?php
namespace App\\Models;
use Illuminate\\Database\\Eloquent\\Model;
use Illuminate\\Database\\Eloquent\\Relations\\HasMany;

class Product extends Model {
    protected $fillable = ['title', 'price', 'is_active'];
    protected $casts = [
        'is_active' => 'boolean',
        'price' => 'decimal:2'
    ];

    public function reviews(): HasMany {
        return $this->hasMany(Review::class);
    }
}
""")

            schema = get_model_schema("Product", tmpdir)
            self.assertEqual(schema["status"], "ok")
            self.assertEqual(schema["model"], "Product")
            self.assertEqual(schema["table"], "products")
            self.assertEqual(len(schema["fillable"]), 3)
            self.assertIn("title", schema["fillable"])
            self.assertEqual(schema["casts"]["is_active"], "boolean")

            # Check relations
            self.assertEqual(len(schema["relations"]), 1)
            self.assertEqual(schema["relations"][0]["name"], "reviews")
            self.assertEqual(schema["relations"][0]["type"], "hasMany")
            self.assertEqual(schema["relations"][0]["target"], "Review")

            # Check columns
            col_names = [c["name"] for c in schema["columns"]]
            self.assertIn("id", col_names)
            self.assertIn("title", col_names)
            self.assertIn("price", col_names)
            self.assertIn("is_active", col_names)
            self.assertIn("created_at", col_names)

if __name__ == "__main__":
    unittest.main()
