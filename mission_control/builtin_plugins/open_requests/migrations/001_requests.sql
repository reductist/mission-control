CREATE TABLE plugin__13__open_requests__state (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), revision INTEGER NOT NULL CHECK(revision > 0)) STRICT;
INSERT INTO plugin__13__open_requests__state VALUES (1, 1);
CREATE TABLE plugin__13__open_requests__requests (id TEXT PRIMARY KEY, document TEXT NOT NULL CHECK(json_valid(document))) STRICT;
CREATE TABLE plugin__13__open_requests__history (id INTEGER PRIMARY KEY, request_id TEXT NOT NULL REFERENCES plugin__13__open_requests__requests(id), actor TEXT NOT NULL, occurred_at TEXT NOT NULL, operation TEXT NOT NULL, document TEXT NOT NULL CHECK(json_valid(document))) STRICT;
CREATE TABLE plugin__13__open_requests__receipts (command_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL CHECK(json_valid(result))) STRICT;
CREATE TRIGGER plugin__13__open_requests__history_immutable_update BEFORE UPDATE ON plugin__13__open_requests__history BEGIN SELECT RAISE(ABORT, 'request history is immutable'); END;
CREATE TRIGGER plugin__13__open_requests__history_immutable_delete BEFORE DELETE ON plugin__13__open_requests__history BEGIN SELECT RAISE(ABORT, 'request history is immutable'); END;
