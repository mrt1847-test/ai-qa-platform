"""Durable server-owned recording call reservations; never stores credentials."""
def apply(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS model_request_receipts (
        project_id TEXT NOT NULL, attempt_id TEXT NOT NULL, request_key TEXT NOT NULL,
        call_id TEXT NOT NULL, worker_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
        policy_ref TEXT NOT NULL, price_mode TEXT NOT NULL CHECK(price_mode='estimate'),
        state TEXT NOT NULL CHECK(state IN ('pending','completed')),
        charged INTEGER NOT NULL CHECK(charged IN (0,1)),
        status_code INTEGER, response_json TEXT, created_at TEXT NOT NULL, completed_at TEXT,
        PRIMARY KEY(project_id,attempt_id,request_key), UNIQUE(project_id,call_id),
        FOREIGN KEY(project_id,attempt_id) REFERENCES attempts(project_id,attempt_id),
        CHECK((state='pending' AND response_json IS NULL AND status_code IS NULL AND completed_at IS NULL AND charged=1)
           OR (state='completed' AND response_json IS NOT NULL AND status_code IS NOT NULL AND completed_at IS NOT NULL))
    )""")
    connection.execute("""CREATE UNIQUE INDEX IF NOT EXISTS model_request_one_pending
        ON model_request_receipts(project_id,attempt_id) WHERE state='pending'""")
    connection.execute("""CREATE TRIGGER IF NOT EXISTS model_request_receipt_immutable
        BEFORE UPDATE ON model_request_receipts WHEN OLD.state='completed'
          OR NEW.project_id<>OLD.project_id OR NEW.attempt_id<>OLD.attempt_id
          OR NEW.request_key<>OLD.request_key OR NEW.call_id<>OLD.call_id
          OR NEW.worker_id<>OLD.worker_id OR NEW.fingerprint<>OLD.fingerprint
          OR NEW.policy_ref<>OLD.policy_ref OR NEW.created_at<>OLD.created_at OR NEW.price_mode<>OLD.price_mode
        BEGIN SELECT RAISE(ABORT,'model request receipt is immutable'); END""")
    connection.execute("""CREATE TRIGGER IF NOT EXISTS model_request_receipt_no_delete
        BEFORE DELETE ON model_request_receipts
        BEGIN SELECT RAISE(ABORT,'model request receipt is immutable'); END""")
