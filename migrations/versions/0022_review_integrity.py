"""Deferred exact replay/materialization ownership and permanent fact protection.

Auxiliary claims mirror immutable rows. Their composite deferred foreign keys
allow a version, its ready package and its receipt to be built atomically, while
checking the complete reciprocal pair at COMMIT without rewriting old facts.
"""


def apply(connection):
    connection.execute("CREATE UNIQUE INDEX review_version_package_exact ON case_versions(project_id,case_id,version_id,replay_package_id)")
    connection.execute("CREATE UNIQUE INDEX review_package_version_exact ON replay_packages(project_id,case_id,case_version_id,package_id,ready)")
    connection.execute("CREATE UNIQUE INDEX review_link_pair_exact ON package_version_links(project_id,case_id,version_id,package_id)")
    connection.execute("CREATE UNIQUE INDEX review_version_source_exact ON case_versions(project_id,case_id,version_id,source_manifest_id)")
    connection.execute("CREATE UNIQUE INDEX review_manifest_hash_exact ON recording_manifests(project_id,case_id,manifest_id,body_hash)")
    connection.execute("CREATE UNIQUE INDEX review_package_source_exact ON replay_packages(project_id,case_id,package_id,case_version_id,source_manifest_id,source_manifest_hash)")
    connection.execute("""
        CREATE TABLE review_package_source_claims (
            project_id TEXT NOT NULL, case_id TEXT NOT NULL,
            package_id TEXT NOT NULL, version_id TEXT NOT NULL,
            manifest_id TEXT NOT NULL, manifest_hash TEXT NOT NULL,
            PRIMARY KEY(project_id,package_id),
            FOREIGN KEY(project_id,case_id,package_id,version_id,manifest_id,manifest_hash)
                REFERENCES replay_packages(project_id,case_id,package_id,case_version_id,source_manifest_id,source_manifest_hash)
                DEFERRABLE INITIALLY DEFERRED,
            FOREIGN KEY(project_id,case_id,version_id,manifest_id)
                REFERENCES case_versions(project_id,case_id,version_id,source_manifest_id)
                DEFERRABLE INITIALLY DEFERRED,
            FOREIGN KEY(project_id,case_id,manifest_id,manifest_hash)
                REFERENCES recording_manifests(project_id,case_id,manifest_id,body_hash)
                DEFERRABLE INITIALLY DEFERRED
        )
    """)
    for operation in ('INSERT', 'UPDATE'):
        connection.execute(f"""CREATE TRIGGER review_package_source_{operation.lower()}
            AFTER {operation} ON replay_packages WHEN NEW.ready=1
            BEGIN INSERT OR IGNORE INTO review_package_source_claims VALUES
                (NEW.project_id,NEW.case_id,NEW.package_id,NEW.case_version_id,NEW.source_manifest_id,NEW.source_manifest_hash);
            END""")
    connection.execute("""INSERT INTO review_package_source_claims
        SELECT project_id,case_id,package_id,case_version_id,source_manifest_id,source_manifest_hash
        FROM replay_packages WHERE ready=1""")
    connection.execute("""
        CREATE TABLE review_package_pair_claims (
            project_id TEXT NOT NULL, case_id TEXT NOT NULL,
            version_id TEXT NOT NULL, package_id TEXT NOT NULL,
            ready INTEGER NOT NULL DEFAULT 1 CHECK (ready = 1),
            PRIMARY KEY (project_id,case_id,version_id,package_id),
            FOREIGN KEY (project_id,case_id,version_id,package_id)
                REFERENCES case_versions(project_id,case_id,version_id,replay_package_id)
                DEFERRABLE INITIALLY DEFERRED,
            FOREIGN KEY (project_id,case_id,version_id,package_id,ready)
                REFERENCES replay_packages(project_id,case_id,case_version_id,package_id,ready)
                DEFERRABLE INITIALLY DEFERRED,
            FOREIGN KEY (project_id,case_id,version_id,package_id)
                REFERENCES package_version_links(project_id,case_id,version_id,package_id)
                DEFERRABLE INITIALLY DEFERRED
        )
    """)
    # All three paths create the same claim; mismatched paths create separate
    # claims whose exact composite FK cannot be satisfied at transaction end.
    for table, version, package, condition in (
        ("case_versions", "version_id", "replay_package_id", "NEW.replay_package_id IS NOT NULL"),
        ("replay_packages", "case_version_id", "package_id", "NEW.ready = 1"),
        ("package_version_links", "version_id", "package_id", "1"),
    ):
        for operation in ("INSERT", "UPDATE"):
            connection.execute(f"""
                CREATE TRIGGER review_{table}_pair_{operation.lower()}
                AFTER {operation} ON {table} WHEN {condition}
                BEGIN
                    INSERT OR IGNORE INTO review_package_pair_claims
                        (project_id,case_id,version_id,package_id)
                    VALUES (NEW.project_id,NEW.case_id,NEW.{version},NEW.{package});
                END
            """)
    connection.execute("""
        INSERT OR IGNORE INTO review_package_pair_claims(project_id,case_id,version_id,package_id)
        SELECT project_id,case_id,version_id,replay_package_id FROM case_versions WHERE replay_package_id IS NOT NULL
        UNION SELECT project_id,case_id,case_version_id,package_id FROM replay_packages WHERE ready=1
        UNION SELECT project_id,case_id,version_id,package_id FROM package_version_links
    """)
    connection.execute("""
        CREATE TABLE review_version_source_claims (
            project_id TEXT NOT NULL, case_id TEXT NOT NULL,
            version_id TEXT NOT NULL, manifest_id TEXT NOT NULL,
            PRIMARY KEY(project_id,version_id),
            FOREIGN KEY(project_id,case_id,version_id,manifest_id)
                REFERENCES case_versions(project_id,case_id,version_id,source_manifest_id)
                DEFERRABLE INITIALLY DEFERRED,
            FOREIGN KEY(project_id,case_id,manifest_id)
                REFERENCES recording_manifests(project_id,case_id,manifest_id)
                DEFERRABLE INITIALLY DEFERRED
        )
    """)
    connection.execute("""
        CREATE TRIGGER review_version_source_insert AFTER INSERT ON case_versions
        WHEN NEW.source_manifest_id IS NOT NULL
        BEGIN
            INSERT INTO review_version_source_claims VALUES
                (NEW.project_id,NEW.case_id,NEW.version_id,NEW.source_manifest_id);
        END
    """)
    connection.execute("""
        INSERT INTO review_version_source_claims
        SELECT project_id,case_id,version_id,source_manifest_id FROM case_versions WHERE source_manifest_id IS NOT NULL
    """)
    connection.execute("""
        CREATE TABLE review_materialization_claims (
            project_id TEXT NOT NULL, receipt_id TEXT NOT NULL, case_id TEXT NOT NULL,
            manifest_id TEXT NOT NULL, produced_version_id TEXT NOT NULL,
            PRIMARY KEY(project_id,receipt_id),
            FOREIGN KEY(project_id,receipt_id) REFERENCES materialization_receipts(project_id,receipt_id)
                DEFERRABLE INITIALLY DEFERRED,
            FOREIGN KEY(project_id,case_id,manifest_id)
                REFERENCES recording_manifests(project_id,case_id,manifest_id)
                DEFERRABLE INITIALLY DEFERRED,
            FOREIGN KEY(project_id,case_id,produced_version_id,manifest_id)
                REFERENCES case_versions(project_id,case_id,version_id,source_manifest_id)
                DEFERRABLE INITIALLY DEFERRED
        )
    """)
    connection.execute("""
        CREATE TRIGGER review_materialization_insert AFTER INSERT ON materialization_receipts
        BEGIN
            INSERT INTO review_materialization_claims
            SELECT NEW.project_id,NEW.receipt_id,case_id,NEW.manifest_id,NEW.produced_version_id
            FROM recording_manifests WHERE project_id=NEW.project_id AND manifest_id=NEW.manifest_id;
        END
    """)
    connection.execute("""
        INSERT INTO review_materialization_claims
        SELECT r.project_id,r.receipt_id,m.case_id,r.manifest_id,r.produced_version_id
        FROM materialization_receipts r JOIN recording_manifests m
          ON m.project_id=r.project_id AND m.manifest_id=r.manifest_id
    """)
    # Claims are permanent constraint witnesses, never operational projections.
    # The ledger remains correctable by appending usage_adjustments.
    for table in (
        "review_package_pair_claims", "review_package_source_claims", "review_version_source_claims", "review_materialization_claims",
        "materialization_receipts", "item_finalizations", "item_lifecycle_events", "item_usage_facts",
        "usage_adjustments", "analysis_records", "fingerprint_observations",
    ):
        for operation in ("UPDATE", "DELETE"):
            connection.execute(f"""
                CREATE TRIGGER review_{table}_no_{operation.lower()}
                BEFORE {operation} ON {table}
                BEGIN SELECT RAISE(ABORT, 'permanent fact is append-only'); END
            """)
