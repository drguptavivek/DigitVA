import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { createPostgresPool } from "./db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const migrationsDirectory = path.join(__dirname, "migrations");

export async function runMigrations(pool = createPostgresPool()) {
  await pool.query(`
    create table if not exists schema_migrations (
      version text primary key,
      name text not null,
      applied_at timestamptz not null default now()
    );
  `);

  const files = (await readdir(migrationsDirectory)).filter((file) => /^\d+_.+\.sql$/u.test(file)).sort();

  for (const file of files) {
    const version = file.split("_")[0];
    const alreadyApplied = await pool.query("select 1 from schema_migrations where version = $1", [version]);
    if (alreadyApplied.rowCount) continue;

    const sql = await readFile(path.join(migrationsDirectory, file), "utf8");
    await pool.query("begin");
    try {
      await pool.query(sql);
      await pool.query("insert into schema_migrations (version, name) values ($1, $2)", [version, file]);
      await pool.query("commit");
      console.log(`Applied migration ${file}`);
    } catch (error) {
      await pool.query("rollback");
      throw error;
    }
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const pool = createPostgresPool();
  try {
    await runMigrations(pool);
    console.log("Database migrations are up to date.");
  } finally {
    await pool.end();
  }
}