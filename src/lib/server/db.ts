import { mkdir, readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import type { Pool, PoolClient } from 'pg';
import type { PGlite } from '@electric-sql/pglite';

export type Row = Record<string, unknown>;
export interface Queryable {
  query<T extends Row = Row>(sql: string, params?: unknown[]): Promise<{ rows: T[] }>;
}
export interface Database extends Queryable {
  transaction<T>(fn: (db: Queryable) => Promise<T>): Promise<T>;
}
export class DatabaseUnavailable extends Error {}

const globalDb = globalThis as unknown as { dishplayDb?: Promise<Database> };

async function connect(): Promise<Database> {
  const migrationDir = path.join(process.cwd(), 'migrations');
  const migrationFiles = (await readdir(migrationDir)).filter((name) => /^\d+_[a-z_]+\.sql$/.test(name)).sort();
  const migration = (await Promise.all(migrationFiles.map((name) => readFile(path.join(migrationDir, name), 'utf8')))).join('\n');
  if (process.env.DATABASE_URL) {
    const { Pool: PgPool } = await import('pg');
    const pool: Pool = new PgPool({
      connectionString: process.env.DATABASE_URL,
      max: 3,
      idleTimeoutMillis: 20_000,
      connectionTimeoutMillis: 10_000,
    });
    const adapter = (client: Pool | PoolClient): Queryable => ({
      query: async <T extends Row>(sql: string, params: unknown[] = []) => {
        const result = await client.query<T>(sql, params);
        return { rows: result.rows };
      },
    });
    // Transaction-scoped lock serializes first initialization across serverless instances.
    try {
      const init = await pool.connect();
      try {
        await init.query('BEGIN');
        await init.query('SELECT pg_advisory_xact_lock(73422109)');
        await init.query(migration);
        await init.query('COMMIT');
      } catch (error) {
        await init.query('ROLLBACK');
        throw error;
      } finally {
        init.release();
      }
    } catch (error) {
      await pool.end();
      throw error;
    }
    return {
      ...adapter(pool),
      transaction: async <T>(fn: (db: Queryable) => Promise<T>): Promise<T> => {
        const client = await pool.connect();
        try {
          await client.query('BEGIN');
          const result = await fn(adapter(client));
          await client.query('COMMIT');
          return result;
        } catch (error) {
          await client.query('ROLLBACK');
          throw error;
        } finally {
          client.release();
        }
      },
    };
  }
  if (
    process.env.VERCEL ||
    (process.env.NODE_ENV === 'production' && process.env.ALLOW_LOCAL_DATABASE !== 'true')
  ) {
    throw new DatabaseUnavailable(
      'Connect PostgreSQL with DATABASE_URL to enable restaurant accounts. The public demo remains available.',
    );
  }
  const { PGlite: EmbeddedPostgres } = await import('@electric-sql/pglite');
  const localDataDir = path.resolve(
    process.env.PGLITE_DATA_DIR || path.join(process.cwd(), '.data/dishplay'),
  );
  // PGlite creates the database directory itself, but not missing parent folders.
  await mkdir(path.dirname(localDataDir), { recursive: true });
  const local: PGlite = new EmbeddedPostgres(localDataDir);
  try {
    await local.exec(migration);
  } catch (error) {
    await local.close();
    throw error;
  }
  return {
    query: async <T extends Row>(sql: string, params: unknown[] = []) => ({
      rows: (await local.query<T>(sql, params)).rows,
    }),
    transaction: async <T>(fn: (db: Queryable) => Promise<T>) =>
      local.transaction(async (tx) =>
        fn({
          query: async <R extends Row>(sql: string, params: unknown[] = []) => ({
            rows: (await tx.query<R>(sql, params)).rows,
          }),
        }),
      ),
  };
}

export async function database(): Promise<Database> {
  globalDb.dishplayDb ??= connect().catch((error: unknown) => {
    globalDb.dishplayDb = undefined;
    if (error instanceof DatabaseUnavailable) throw error;
    let message = error instanceof Error ? error.message : 'Unknown database failure';
    if (process.env.DATABASE_URL)
      message = message.split(process.env.DATABASE_URL).join('[redacted database URL]');
    message = message.replace(/postgres(?:ql)?:\/\/\S+/gi, '[redacted database URL]');
    console.error(
      'Database connection or initialization failed:',
      error instanceof Error ? error.name : 'UnknownError',
      message.slice(0, 500),
    );
    throw new DatabaseUnavailable('The database is temporarily unavailable. Please try again.');
  });
  return globalDb.dishplayDb;
}
