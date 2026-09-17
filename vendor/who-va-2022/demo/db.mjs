import pg from "pg";

const { Pool } = pg;

export function createPostgresPool() {
  if (process.env.DATABASE_URL) return new Pool({ connectionString: process.env.DATABASE_URL });

  return new Pool({
    host: process.env.PGHOST ?? "localhost",
    port: Number(process.env.PGPORT ?? 5433),
    user: process.env.PGUSER ?? "postgres",
    password: process.env.PGPASSWORD ?? "aiims@123",
    database: process.env.PGDATABASE ?? "whova"
  });
}
