"""Add guided-workflow evidence; preserve existing stages and all custody records."""


def migrate(c):
    c.executescript('''BEGIN IMMEDIATE;
    ALTER TABLE jobs ADD COLUMN lifecycle_version INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE jobs ADD COLUMN lifecycle_data TEXT NOT NULL DEFAULT '{}';
    CREATE INDEX ix_job_lifecycle ON jobs(lifecycle_version,stage);
    PRAGMA user_version=6;
    COMMIT;''')
