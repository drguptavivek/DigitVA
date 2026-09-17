import { createHash, randomBytes, timingSafeEqual, scryptSync } from "node:crypto";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { createServer as createHttpServer } from "node:http";
import { networkInterfaces } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { createServer as createViteServer } from "vite";

import { createPostgresPool } from "./db.mjs";
import { runMigrations } from "./migrate.mjs";

const PORT = Number(process.env.PORT ?? 5173);
const HOST = process.env.HOST ?? "0.0.0.0";
const HMR_PORT = Number(process.env.VITE_HMR_PORT ?? process.env.HMR_PORT ?? PORT + 1);
const pool = createPostgresPool();
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const attachmentStorageRoot = path.resolve(
  process.env.WHO_VA_ATTACHMENT_DIR ?? path.join(__dirname, "uploads", "attachments")
);

const allowedOrigins = new Set(
  (
    process.env.WHO_VA_ALLOWED_ORIGINS ??
    [`http://127.0.0.1:${PORT}`, `http://localhost:${PORT}`, ...localNetworkUrls(PORT)].join(",")
  )
    .split(",")
    .map((origin) => origin.trim())
    .filter(Boolean)
);

const apiSecurityHeaders = {
  "cache-control": "no-store",
  "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
  "cross-origin-resource-policy": "same-origin",
  "referrer-policy": "no-referrer",
  "x-content-type-options": "nosniff"
};

function corsHeadersFor(request) {
  const origin = request.headers.origin;
  if (typeof origin !== "string" || !allowedOrigins.has(origin)) return {};
  return {
    "access-control-allow-origin": origin,
    vary: "Origin"
  };
}

function apiHeaders(request, extraHeaders = {}) {
  return {
    ...apiSecurityHeaders,
    ...corsHeadersFor(request),
    ...extraHeaders
  };
}

const corsPreflightHeaders = {
  "access-control-allow-methods": "DELETE,GET,POST,PUT,OPTIONS",
  "access-control-allow-headers":
    "authorization,content-type,x-attachment-name,x-attachment-size,x-user-id,x-auth-key,x-setup-key",
  "access-control-max-age": "600"
};

async function readJsonBody(request, maxBytes = 5 * 1024 * 1024) {
  const contentType = String(request.headers["content-type"] ?? "")
    .split(";")[0]
    .toLowerCase();
  if (contentType !== "application/json") throw badRequest("Request content type must be application/json");
  const chunks = [];
  let totalBytes = 0;
  for await (const chunk of request) {
    totalBytes += chunk.length;
    if (totalBytes > maxBytes) throw badRequest("JSON body exceeds the maximum request size");
    chunks.push(chunk);
  }
  if (chunks.length === 0) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw badRequest("Request body must be valid JSON");
  }
}

async function readRawBody(request, maxBytes = 30 * 1024 * 1024) {
  const chunks = [];
  let totalBytes = 0;
  for await (const chunk of request) {
    totalBytes += chunk.length;
    if (totalBytes > maxBytes) throw badRequest("Attachment exceeds the maximum upload size");
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

function sendJson(request, response, statusCode, body) {
  response.writeHead(statusCode, {
    "content-type": "application/json; charset=utf-8",
    ...apiHeaders(request)
  });
  response.end(JSON.stringify(body));
}

const partnerSites = new Set(["AIIMS", "ICMR", "WHO Collaborating Centre"]);
const assignedSites = new Set(["Bhopal", "Delhi", "Mumbai", "Pune"]);
const userRoles = new Set(["admin", "data-entry"]);
const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/u;

function generatedUserId(name) {
  const initials = name
    .split(/\s+/u)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "U")
    .join("")
    .padEnd(2, "U");
  return `USR-${initials}-${Date.now().toString(36).toUpperCase()}-${randomBytes(3).toString("hex").toUpperCase()}`;
}

function generatedAuthKey() {
  return `AUTH-${randomBytes(24).toString("hex").toUpperCase()}`;
}

function generatedSessionToken(prefix) {
  return `${prefix}-${randomBytes(32).toString("base64url")}`;
}

function hashSessionToken(token) {
  return createHash("sha256").update(String(token)).digest("hex");
}

function hashPassword(password) {
  const salt = randomBytes(16).toString("hex");
  const hash = scryptSync(password, salt, 64).toString("hex");
  return `scrypt:${salt}:${hash}`;
}

function verifyPassword(password, storedHash) {
  const [scheme, salt, hash] = String(storedHash).split(":");
  if (scheme !== "scrypt" || !salt || !hash) return false;
  const expected = Buffer.from(hash, "hex");
  const actual = scryptSync(password, salt, expected.length);
  return expected.length === actual.length && timingSafeEqual(expected, actual);
}

const loginFailures = new Map();
const loginWindowMs = 15 * 60 * 1000;
const maxLoginFailures = 5;

function requestIp(request) {
  return request.socket.remoteAddress ?? "unknown";
}

function loginRateLimitKey(request, identifier) {
  return `${requestIp(request)}:${String(identifier).trim().toLowerCase()}`;
}

function assertLoginAllowed(request, identifier) {
  const key = loginRateLimitKey(request, identifier);
  const now = Date.now();
  const failure = loginFailures.get(key);
  if (!failure || failure.resetAt <= now) {
    loginFailures.delete(key);
    return;
  }
  if (failure.count >= maxLoginFailures) {
    const error = new Error("Too many login attempts. Try again later.");
    error.statusCode = 429;
    throw error;
  }
}

function recordLoginFailure(request, identifier) {
  const key = loginRateLimitKey(request, identifier);
  const now = Date.now();
  const current = loginFailures.get(key);
  if (!current || current.resetAt <= now) {
    loginFailures.set(key, { count: 1, resetAt: now + loginWindowMs });
    return;
  }
  current.count += 1;
}

function clearLoginFailures(request, identifier) {
  loginFailures.delete(loginRateLimitKey(request, identifier));
}

function badRequest(message) {
  const error = new Error(message);
  error.statusCode = 400;
  return error;
}

function notFound(message) {
  const error = new Error(message);
  error.statusCode = 404;
  return error;
}

function unauthorized(message) {
  const error = new Error(message);
  error.statusCode = 401;
  return error;
}

const attachmentIdPattern = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/u;
const attachmentMimeExtensions = new Map([
  ["image/jpeg", ".jpg"],
  ["application/pdf", ".pdf"],
  ["audio/webm", ".webm"],
  ["audio/mp4", ".m4a"],
  ["audio/ogg", ".ogg"]
]);

function validateAttachmentId(id) {
  if (!attachmentIdPattern.test(id)) throw badRequest("Attachment id is invalid");
  return id;
}

function extensionForAttachment(mimeType, originalName = "") {
  const normalized = String(mimeType).toLowerCase();
  const exact = attachmentMimeExtensions.get(normalized);
  if (exact) return exact;
  throw badRequest(`Attachment content type is not allowed: ${originalName || normalized}`);
}

function isPathInside(root, candidate) {
  const relative = path.relative(root, candidate);
  return relative !== "" && !relative.startsWith("..") && !path.isAbsolute(relative);
}

function validateAttachmentBytes(contentType, bytes) {
  const byte = (index) => bytes[index];
  if (contentType === "image/jpeg") {
    if (byte(0) === 0xff && byte(1) === 0xd8 && byte(2) === 0xff) return;
    throw badRequest("Attachment body is not a valid JPEG");
  }
  if (contentType === "application/pdf") {
    if (byte(0) === 0x25 && byte(1) === 0x50 && byte(2) === 0x44 && byte(3) === 0x46) return;
    throw badRequest("Attachment body is not a valid PDF");
  }
  if (contentType === "audio/webm") {
    if (byte(0) === 0x1a && byte(1) === 0x45 && byte(2) === 0xdf && byte(3) === 0xa3) return;
    throw badRequest("Attachment body is not a valid WebM file");
  }
  if (contentType === "audio/mp4") {
    const brandMarker = Buffer.from(bytes.subarray(4, 8)).toString("ascii");
    if (brandMarker === "ftyp") return;
    throw badRequest("Attachment body is not a valid MP4 audio file");
  }
  if (contentType === "audio/ogg") {
    if (Buffer.from(bytes.subarray(0, 4)).toString("ascii") === "OggS") return;
    throw badRequest("Attachment body is not a valid Ogg file");
  }
  throw badRequest("Attachment content type is not allowed");
}

async function ensureAttachmentTable() {
  await pool.query(`
    create table if not exists who_va_attachments (
      id text primary key,
      original_name text,
      stored_name text not null,
      mime_type text not null,
      size_bytes integer not null,
      storage_path text not null,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    )
  `);
  await pool.query(
    "create index if not exists who_va_attachments_updated_at_idx on who_va_attachments (updated_at)"
  );
}

async function saveAttachment(id, request) {
  await ensureAttachmentTable();
  const attachmentId = validateAttachmentId(id);
  const originalNameHeader = String(request.headers["x-attachment-name"] ?? "");
  const originalName = (() => {
    try {
      return decodeURIComponent(originalNameHeader).slice(0, 255);
    } catch {
      throw badRequest("Attachment name is invalid");
    }
  })();
  const contentType = String(request.headers["content-type"] ?? "application/octet-stream")
    .split(";")[0]
    .toLowerCase();
  if (!attachmentMimeExtensions.has(contentType)) throw badRequest("Attachment content type is not allowed");
  const bytes = await readRawBody(request);
  if (bytes.length === 0) throw badRequest("Attachment body is empty");
  validateAttachmentBytes(contentType, bytes);
  const reportedSize = Number(request.headers["x-attachment-size"] ?? bytes.length);
  if (Number.isFinite(reportedSize) && reportedSize !== bytes.length) {
    throw badRequest("Attachment size does not match the uploaded body");
  }
  const storedName = `${attachmentId}${extensionForAttachment(contentType, originalName)}`;
  const storagePath = path.join(attachmentStorageRoot, storedName);
  const resolvedStoragePath = path.resolve(storagePath);
  if (!isPathInside(attachmentStorageRoot, resolvedStoragePath)) {
    throw badRequest("Attachment storage path is invalid");
  }
  await mkdir(attachmentStorageRoot, { recursive: true });
  await writeFile(resolvedStoragePath, bytes);
  const result = await pool.query(
    `
      insert into who_va_attachments (
        id,
        original_name,
        stored_name,
        mime_type,
        size_bytes,
        storage_path
      )
      values ($1, $2, $3, $4, $5, $6)
      on conflict (id) do update set
        original_name = excluded.original_name,
        stored_name = excluded.stored_name,
        mime_type = excluded.mime_type,
        size_bytes = excluded.size_bytes,
        storage_path = excluded.storage_path,
        updated_at = now()
      returning id, original_name, stored_name, mime_type, size_bytes, created_at, updated_at
    `,
    [attachmentId, originalName || null, storedName, contentType, bytes.length, resolvedStoragePath]
  );
  const saved = result.rows[0];
  return {
    id: saved.id,
    uri: `/api/attachments/${encodeURIComponent(saved.id)}`,
    originalName: saved.original_name,
    storedName: saved.stored_name,
    mimeType: saved.mime_type,
    size: saved.size_bytes,
    createdAt: saved.created_at,
    updatedAt: saved.updated_at
  };
}

async function loadAttachment(id) {
  await ensureAttachmentTable();
  const attachmentId = validateAttachmentId(id);
  const result = await pool.query(
    "select id, original_name, stored_name, mime_type, size_bytes, storage_path from who_va_attachments where id = $1",
    [attachmentId]
  );
  const attachment = result.rows[0];
  if (!attachment) throw notFound("Attachment not found");
  const storagePath = path.resolve(attachment.storage_path);
  if (!isPathInside(attachmentStorageRoot, storagePath)) {
    throw badRequest("Stored attachment path is invalid");
  }
  const fileStats = await stat(storagePath).catch(() => undefined);
  if (!fileStats?.isFile()) throw notFound("Attachment file not found");
  return { ...attachment, storagePath };
}

const formEntryStatuses = new Set(["case-entry", "completed"]);

function validateUserRegistration(payload) {
  const name = typeof payload.name === "string" ? payload.name.trim() : "";
  const email = typeof payload.email === "string" ? payload.email.trim().toLowerCase() : "";
  const role = typeof payload.role === "string" ? payload.role.trim() : "";
  const partnerSite = typeof payload.partnerSite === "string" ? payload.partnerSite.trim() : "";
  const siteAssigned = typeof payload.siteAssigned === "string" ? payload.siteAssigned.trim() : "";
  const password = typeof payload.password === "string" ? payload.password : "";

  if (!characterOnlyPattern.test(name))
    throw badRequest("Name accepts letters only. Spaces are allowed between words.");
  if (!emailPattern.test(email)) throw badRequest("A valid email is required");
  if (!userRoles.has(role)) throw badRequest("Select a valid role");
  if (!partnerSites.has(partnerSite)) throw badRequest("Select a valid partner site");
  if (!assignedSites.has(siteAssigned)) throw badRequest("Select a valid assigned site");
  if (password.length < 8 || password.length > 128)
    throw badRequest("Password must be between 8 and 128 characters");

  return { name, email, role, partnerSite, siteAssigned, password };
}

async function ensureUsersTable() {
  await pool.query(`
    create table if not exists who_va_users (
      user_id text primary key,
      name text not null,
      email text not null unique,
      partner_site text not null,
      site_assigned text not null,
      password_hash text not null,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    )
  `);
  await pool.query(
    "alter table who_va_users add column if not exists role text not null default 'data-entry'"
  );
  await pool.query("alter table who_va_users add column if not exists auth_key text");
  await pool.query("update who_va_users set auth_key = $1 where auth_key is null", [generatedAuthKey()]);
  await pool.query("alter table who_va_users alter column auth_key set not null");
  await pool.query("create index if not exists who_va_users_partner_site_idx on who_va_users (partner_site)");
  await pool.query(
    "create index if not exists who_va_users_site_assigned_idx on who_va_users (site_assigned)"
  );
  await pool.query("create index if not exists who_va_users_role_idx on who_va_users (role)");
}

async function ensureUserSessionsTable() {
  await ensureUsersTable();
  await pool.query(`
    create table if not exists who_va_user_sessions (
      session_id text primary key,
      user_id text not null references who_va_users(user_id) on delete cascade,
      device_id text,
      access_token_hash text not null unique,
      refresh_token_hash text not null unique,
      access_expires_at timestamptz not null,
      refresh_expires_at timestamptz not null,
      revoked_at timestamptz,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    )
  `);
  await pool.query("create index if not exists who_va_user_sessions_user_id_idx on who_va_user_sessions (user_id)");
  await pool.query(
    "create index if not exists who_va_user_sessions_access_token_hash_idx on who_va_user_sessions (access_token_hash)"
  );
  await pool.query(
    "create index if not exists who_va_user_sessions_refresh_token_hash_idx on who_va_user_sessions (refresh_token_hash)"
  );
}

async function createUserSession(userId, deviceId) {
  await ensureUserSessionsTable();
  const accessToken = generatedSessionToken("ACCESS");
  const refreshToken = generatedSessionToken("REFRESH");
  const sessionId = `SESSION-${randomBytes(16).toString("hex").toUpperCase()}`;
  await pool.query(
    `
      insert into who_va_user_sessions (
        session_id, user_id, device_id, access_token_hash, refresh_token_hash, access_expires_at, refresh_expires_at
      )
      values ($1, $2, $3, $4, $5, now() + interval '15 minutes', now() + interval '30 days')
    `,
    [sessionId, userId, deviceId || null, hashSessionToken(accessToken), hashSessionToken(refreshToken)]
  );
  return { accessToken, refreshToken, expiresIn: 15 * 60 };
}

async function userFromUserId(userId) {
  await ensureUsersTable();
  const result = await pool.query(
    `
      select user_id, name, email, role, partner_site, site_assigned, auth_key, created_at
      from who_va_users
      where user_id = $1
    `,
    [userId]
  );
  const saved = result.rows[0];
  if (!saved) throw unauthorized("User not found");
  return {
    userId: saved.user_id,
    name: saved.name,
    email: saved.email,
    role: saved.role,
    partnerSite: saved.partner_site,
    siteAssigned: saved.site_assigned,
    authKey: saved.auth_key,
    createdAt: saved.created_at
  };
}

async function refreshUserSession(payload) {
  const refreshToken = typeof payload.refreshToken === "string" ? payload.refreshToken.trim() : "";
  if (!refreshToken) throw unauthorized("Refresh token is required");
  await ensureUserSessionsTable();
  const result = await pool.query(
    `
      select session_id, user_id
      from who_va_user_sessions
      where refresh_token_hash = $1
        and revoked_at is null
        and refresh_expires_at > now()
    `,
    [hashSessionToken(refreshToken)]
  );
  const session = result.rows[0];
  if (!session) throw unauthorized("Refresh token is invalid or expired");
  const accessToken = generatedSessionToken("ACCESS");
  const nextRefreshToken = generatedSessionToken("REFRESH");
  await pool.query(
    `
      update who_va_user_sessions
      set access_token_hash = $1,
          refresh_token_hash = $2,
          access_expires_at = now() + interval '15 minutes',
          refresh_expires_at = now() + interval '30 days',
          updated_at = now()
      where session_id = $3
    `,
    [hashSessionToken(accessToken), hashSessionToken(nextRefreshToken), session.session_id]
  );
  return {
    user: await userFromUserId(session.user_id),
    accessToken,
    refreshToken: nextRefreshToken,
    expiresIn: 15 * 60
  };
}

async function revokeUserSession(payload, request) {
  await ensureUserSessionsTable();
  const refreshToken = typeof payload.refreshToken === "string" ? payload.refreshToken.trim() : "";
  const authorization = String(request.headers.authorization ?? "");
  const accessToken = authorization.toLowerCase().startsWith("bearer ")
    ? authorization.slice("bearer ".length).trim()
    : "";
  if (!refreshToken && !accessToken) return;
  await pool.query(
    `
      update who_va_user_sessions
      set revoked_at = now(), updated_at = now()
      where revoked_at is null
        and (
          ($1::text is not null and refresh_token_hash = $1)
          or ($2::text is not null and access_token_hash = $2)
        )
    `,
    [refreshToken ? hashSessionToken(refreshToken) : null, accessToken ? hashSessionToken(accessToken) : null]
  );
}

async function hasRegisteredUsers() {
  await ensureUsersTable();
  const result = await pool.query("select exists (select 1 from who_va_users) as has_users");
  return Boolean(result.rows[0]?.has_users);
}

async function requireAdminRequester(request, url) {
  const setupKey = process.env.WHO_VA_SETUP_KEY;
  const providedSetupKey = String(request.headers["x-setup-key"] ?? "").trim();
  const setupKeyBytes = Buffer.from(setupKey ?? "");
  const providedSetupKeyBytes = Buffer.from(providedSetupKey);
  if (
    setupKey &&
    providedSetupKey &&
    providedSetupKeyBytes.length === setupKeyBytes.length &&
    timingSafeEqual(providedSetupKeyBytes, setupKeyBytes)
  ) {
    return;
  }
  const auth = authFromRequest(request, url);
  const requester = await loadUserByAuthKey(auth.userId, auth.authKey);
  if (requester.role !== "admin") {
    const error = new Error("Only admin users can register users");
    error.statusCode = 403;
    throw error;
  }
}

async function requireAdminUser(auth) {
  const requester = await loadAuthenticatedUser(auth);
  if (requester.role !== "admin") {
    const error = new Error("Only admin users can manage user accounts");
    error.statusCode = 403;
    throw error;
  }
  return requester;
}

function userResponseFromRow(saved) {
  return {
    userId: saved.user_id,
    name: saved.name,
    email: saved.email,
    role: saved.role,
    partnerSite: saved.partner_site,
    siteAssigned: saved.site_assigned,
    authKey: saved.auth_key,
    createdAt: saved.created_at
  };
}

async function registerUser(payload, request, url) {
  await ensureUsersTable();
  if (await hasRegisteredUsers()) await requireAdminRequester(request, url);
  const user = validateUserRegistration(payload);
  try {
    const result = await pool.query(
      `
        insert into who_va_users (
          user_id,
          name,
          email,
          role,
          partner_site,
          site_assigned,
          password_hash,
          auth_key
        )
        values ($1, $2, $3, $4, $5, $6, $7, $8)
        returning user_id, name, email, role, partner_site, site_assigned, auth_key, created_at
      `,
      [
        generatedUserId(user.name),
        user.name,
        user.email,
        user.role,
        user.partnerSite,
        user.siteAssigned,
        hashPassword(user.password),
        generatedAuthKey()
      ]
    );
    const saved = result.rows[0];
    return {
      userId: saved.user_id,
      name: saved.name,
      email: saved.email,
      role: saved.role,
      partnerSite: saved.partner_site,
      siteAssigned: saved.site_assigned,
      authKey: saved.auth_key,
      createdAt: saved.created_at
    };
  } catch (error) {
    if (error?.code === "23505") throw badRequest("A user with this email is already registered");
    throw error;
  }
}

function validateAdminUserUpdate(payload) {
  const name = typeof payload.name === "string" ? payload.name.trim() : "";
  const email = typeof payload.email === "string" ? payload.email.trim().toLowerCase() : "";
  const role = typeof payload.role === "string" ? payload.role.trim() : "";
  const partnerSite = typeof payload.partnerSite === "string" ? payload.partnerSite.trim() : "";
  const siteAssigned = typeof payload.siteAssigned === "string" ? payload.siteAssigned.trim() : "";
  const password = typeof payload.password === "string" ? payload.password : "";

  if (!characterOnlyPattern.test(name))
    throw badRequest("Name accepts letters only. Spaces are allowed between words.");
  if (!emailPattern.test(email)) throw badRequest("A valid email is required");
  if (!userRoles.has(role)) throw badRequest("Select a valid role");
  if (!partnerSites.has(partnerSite)) throw badRequest("Select a valid partner site");
  if (!assignedSites.has(siteAssigned)) throw badRequest("Select a valid assigned site");
  if (password && (password.length < 8 || password.length > 128))
    throw badRequest("Password must be between 8 and 128 characters");

  return { name, email, role, partnerSite, siteAssigned, password };
}

async function listUsers(auth) {
  await ensureUsersTable();
  await requireAdminUser(auth);
  const result = await pool.query(`
    select user_id, name, email, role, partner_site, site_assigned, auth_key, created_at
    from who_va_users
    order by lower(name), lower(email)
  `);
  return result.rows.map(userResponseFromRow);
}

async function updateUserByAdmin(userId, payload, auth) {
  await ensureUsersTable();
  await requireAdminUser(auth);
  const targetUserId = typeof userId === "string" ? userId.trim() : "";
  if (!targetUserId) throw badRequest("User ID is required");
  const user = validateAdminUserUpdate(payload);

  const existingResult = await pool.query("select user_id, role from who_va_users where user_id = $1", [
    targetUserId
  ]);
  const existing = existingResult.rows[0];
  if (!existing) throw notFound("User not found");

  if (existing.role === "admin" && user.role !== "admin") {
    const adminCount = await pool.query("select count(*)::int as count from who_va_users where role = 'admin'");
    if (Number(adminCount.rows[0]?.count ?? 0) <= 1) {
      throw badRequest("At least one admin user is required");
    }
  }

  try {
    const result = await pool.query(
      `
        update who_va_users
        set name = $1,
            email = $2,
            role = $3,
            partner_site = $4,
            site_assigned = $5,
            password_hash = case when $6::text = '' then password_hash else $7 end,
            updated_at = now()
        where user_id = $8
        returning user_id, name, email, role, partner_site, site_assigned, auth_key, created_at
      `,
      [
        user.name,
        user.email,
        user.role,
        user.partnerSite,
        user.siteAssigned,
        user.password,
        user.password ? hashPassword(user.password) : "",
        targetUserId
      ]
    );
    return userResponseFromRow(result.rows[0]);
  } catch (error) {
    if (error?.code === "23505") throw badRequest("A user with this email is already registered");
    throw error;
  }
}
async function loginUser(payload, request) {
  await ensureUsersTable();
  const identifier = typeof payload.email === "string" ? payload.email.trim() : "";
  const normalizedEmail = identifier.toLowerCase();
  const password = typeof payload.password === "string" ? payload.password : "";
  if (!identifier || !password) throw badRequest("Email or user ID and password are required");
  assertLoginAllowed(request, identifier);

  const result = await pool.query(
    `
      select user_id, name, email, role, partner_site, site_assigned, password_hash, auth_key, created_at
      from who_va_users
      where email = $1 or user_id = $2
    `,
    [normalizedEmail, identifier]
  );
  const saved = result.rows[0];
  if (!saved || !verifyPassword(password, saved.password_hash)) {
    recordLoginFailure(request, identifier);
    throw badRequest("Invalid email/user ID or password");
  }
  clearLoginFailures(request, identifier);
  return {
    userId: saved.user_id,
    name: saved.name,
    email: saved.email,
    role: saved.role,
    partnerSite: saved.partner_site,
    siteAssigned: saved.site_assigned,
    authKey: saved.auth_key,
    createdAt: saved.created_at
  };
}

async function changeUserPassword(payload, auth) {
  await ensureUsersTable();
  const requester = await loadAuthenticatedUser(auth);
  const currentPassword = typeof payload.currentPassword === "string" ? payload.currentPassword : "";
  const newPassword = typeof payload.newPassword === "string" ? payload.newPassword : "";
  if (!currentPassword) throw badRequest("Current password is required");
  if (newPassword.length < 8 || newPassword.length > 128) {
    throw badRequest("New password must be between 8 and 128 characters");
  }

  const result = await pool.query("select password_hash from who_va_users where user_id = $1", [
    requester.userId
  ]);
  const saved = result.rows[0];
  if (!saved || !verifyPassword(currentPassword, saved.password_hash)) {
    throw badRequest("Current password is incorrect");
  }

  await pool.query(
    "update who_va_users set password_hash = $1, updated_at = now() where user_id = $2",
    [hashPassword(newPassword), requester.userId]
  );
  return userFromUserId(requester.userId);
}
const characterOnlyCaseEntryFields = {
  district: "District",
  block: "Block",
  villages: "Villages",
  phc: "Phc",
  subcentre: "Subcentre",
  deceasedFullName: "Full name of the deceased"
};

const characterOnlyPattern = /^[A-Za-z]+(?: [A-Za-z]+)*$/;

const allowedCaseEntrySexValues = new Set(["female", "male", "undetermined"]);
const allowedDeathPlaceValues = new Set(["hospital-death", "home-death", "on-the-way-to-hospital", "other"]);
const deathPlaceAliases = new Map([
  ["hospital-death", "hospital-death"],
  ["hospital death", "hospital-death"],
  ["hospital", "hospital-death"],
  ["health facility", "hospital-death"],
  ["facility", "hospital-death"],
  ["home-death", "home-death"],
  ["home death", "home-death"],
  ["home", "home-death"],
  ["on-the-way-to-hospital", "on-the-way-to-hospital"],
  ["on the way to hospital", "on-the-way-to-hospital"],
  ["on way to hospital", "on-the-way-to-hospital"],
  ["transit", "on-the-way-to-hospital"],
  ["other", "other"],
  ["other place", "other"],
  ["others", "other"]
]);

function normalizeDeathPlace(value) {
  if (typeof value !== "string") return "";
  const trimmed = value.trim();
  const normalized = trimmed.toLowerCase().replace(/[_-]+/gu, " ").replace(/\s+/gu, " ");
  return deathPlaceAliases.get(trimmed) ?? deathPlaceAliases.get(normalized) ?? "";
}

function validateCaseEntry(caseEntry) {
  for (const [field, label] of Object.entries(characterOnlyCaseEntryFields)) {
    const value = typeof caseEntry[field] === "string" ? caseEntry[field].trim() : "";
    caseEntry[field] = value;
    if (!characterOnlyPattern.test(value)) {
      const error = new Error(`${label} accepts letters only. Spaces are allowed between words.`);
      error.statusCode = 400;
      throw error;
    }
  }

  if (!allowedCaseEntrySexValues.has(caseEntry.deceasedSex)) {
    const error = new Error("Select a valid sex of the deceased.");
    error.statusCode = 400;
    throw error;
  }

  caseEntry.deathPlace = normalizeDeathPlace(caseEntry.deathPlace);
  if (!allowedDeathPlaceValues.has(caseEntry.deathPlace)) {
    const error = new Error("Select a valid death place.");
    error.statusCode = 400;
    throw error;
  }
}

async function ensureDraftTable() {
  await pool.query(`
    create table if not exists who_va_drafts (
      id text primary key,
      user_id text,
      draft jsonb not null,
      instrument_id text not null,
      instrument_version text not null,
      current_section text not null,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    )
  `);
  await pool.query("alter table who_va_drafts add column if not exists user_id text");
  await pool.query("create index if not exists who_va_drafts_updated_at_idx on who_va_drafts (updated_at)");
  await pool.query("create index if not exists who_va_drafts_user_id_idx on who_va_drafts (user_id)");
}
function validateDraft(draft) {
  if (!draft || typeof draft !== "object" || Array.isArray(draft)) {
    const error = new Error("draft must be an object");
    error.statusCode = 400;
    throw error;
  }
  for (const field of ["id", "instrumentId", "instrumentVersion", "currentSection"]) {
    if (typeof draft[field] !== "string" || draft[field].trim() === "") {
      const error = new Error(`draft.${field} is required`);
      error.statusCode = 400;
      throw error;
    }
  }
  return draft;
}

async function saveDraft(payload, auth) {
  await ensureDraftTable();
  const requester = await loadAuthenticatedUser(auth);
  const draft = validateDraft(payload.draft ?? payload);
  const existingResult = await pool.query("select user_id from who_va_drafts where id = $1", [draft.id]);
  const existing = existingResult.rows[0];
  if (existing?.user_id && requester.role !== "admin" && existing.user_id !== requester.userId) {
    throw unauthorized("Draft belongs to another user");
  }
  const result = await pool.query(
    `
      insert into who_va_drafts (
        id,
        user_id,
        draft,
        instrument_id,
        instrument_version,
        current_section
      )
      values ($1, $2, $3::jsonb, $4, $5, $6)
      on conflict (id) do update set
        user_id = excluded.user_id,
        draft = excluded.draft,
        instrument_id = excluded.instrument_id,
        instrument_version = excluded.instrument_version,
        current_section = excluded.current_section,
        updated_at = now()
      returning id, user_id, instrument_id, instrument_version, current_section, created_at, updated_at
    `,
    [
      draft.id,
      requester.userId,
      JSON.stringify(draft),
      draft.instrumentId,
      draft.instrumentVersion,
      draft.currentSection
    ]
  );

  return result.rows[0];
}

async function loadDraft(id, auth) {
  await ensureDraftTable();
  const requester = await loadAuthenticatedUser(auth);
  const result = await pool.query("select user_id, draft from who_va_drafts where id = $1", [id]);
  const row = result.rows[0];
  if (row && requester.role !== "admin" && row.user_id !== requester.userId) {
    throw unauthorized("Draft belongs to another user");
  }
  return row?.draft;
}

async function removeDraft(id, auth) {
  await ensureDraftTable();
  const requester = await loadAuthenticatedUser(auth);
  if (requester.role === "admin") {
    await pool.query("delete from who_va_drafts where id = $1", [id]);
    return;
  }
  await pool.query("delete from who_va_drafts where id = $1 and user_id = $2", [id, requester.userId]);
}
async function listFormEntries(auth) {
  const requester = await loadAuthenticatedUser(auth);
  const params = requester.role === "admin" ? [] : [requester.userId];
  const userFilter = requester.role === "admin" ? "" : "where user_id = $1";
  const result = await pool.query(
    `
      select id, uid, user_id, status, created_at, updated_at, completed_at, case_entry, who_va_prefill
      from who_va_form_entries
      ${userFilter}
      order by updated_at desc
      limit 100
    `,
    params
  );

  return result.rows.map((row) => ({
    id: row.id,
    uid: row.uid,
    userId: row.user_id,
    status: row.status,
    created_at: row.created_at,
    updated_at: row.updated_at,
    completed_at: row.completed_at,
    caseEntry: row.case_entry,
    whoVaData: row.who_va_prefill
  }));
}

async function verifyUserAuthKey(userId, authKey) {
  if (!userId || !authKey)
    throw badRequest("userId and authKey are required for authenticated form entry pushes");
  await ensureUsersTable();
  const result = await pool.query("select 1 from who_va_users where user_id = $1 and auth_key = $2", [
    userId,
    authKey
  ]);
  if (!result.rows[0]) throw badRequest("Invalid user auth key");
}

function authFromRequest(request, url) {
  const authorization = String(request.headers.authorization ?? "");
  const accessToken = authorization.toLowerCase().startsWith("bearer ")
    ? authorization.slice("bearer ".length).trim()
    : "";
  return {
    accessToken,
    userId: String(request.headers["x-user-id"] ?? url.searchParams.get("userId") ?? "").trim(),
    authKey: String(request.headers["x-auth-key"] ?? url.searchParams.get("authKey") ?? "").trim()
  };
}

async function loadUserByAccessToken(accessToken) {
  if (!accessToken) throw unauthorized("Access token is required");
  await ensureUserSessionsTable();
  const result = await pool.query(
    `
      select s.user_id
      from who_va_user_sessions s
      where s.access_token_hash = $1
        and s.revoked_at is null
        and s.access_expires_at > now()
    `,
    [hashSessionToken(accessToken)]
  );
  const session = result.rows[0];
  if (!session) throw unauthorized("Access token is invalid or expired");
  return userFromUserId(session.user_id);
}

async function loadAuthenticatedUser(auth) {
  if (auth.accessToken) return loadUserByAccessToken(auth.accessToken);
  return loadUserByAuthKey(auth.userId, auth.authKey);
}

async function requireAuthenticatedUser(request, url) {
  const auth = authFromRequest(request, url);
  if (!auth.accessToken && (!auth.userId || !auth.authKey)) {
    throw unauthorized("Authorization is required");
  }
  return { auth, user: await loadAuthenticatedUser(auth) };
}

async function loadUserByAuthKey(userId, authKey) {
  if (!userId || !authKey) throw badRequest("userId and authKey are required");
  await ensureUsersTable();
  const result = await pool.query(
    `
      select user_id, name, email, role, partner_site, site_assigned, auth_key, created_at
      from who_va_users
      where user_id = $1 and auth_key = $2
    `,
    [userId, authKey]
  );
  const saved = result.rows[0];
  if (!saved) throw badRequest("Invalid user auth key");
  return {
    userId: saved.user_id,
    name: saved.name,
    email: saved.email,
    role: saved.role,
    partnerSite: saved.partner_site,
    siteAssigned: saved.site_assigned,
    authKey: saved.auth_key,
    createdAt: saved.created_at
  };
}

async function listMobileSyncEntries(auth) {
  const requester = await loadAuthenticatedUser(auth);
  const result = await pool.query(
    `
      select
        f.id,
        f.uid,
        f.user_id,
        f.status,
        f.created_at,
        f.updated_at,
        f.completed_at,
        f.case_entry,
        f.who_va_prefill,
        f.submission,
        f.validation_issues
      from who_va_form_entries f
      where f.user_id = $1
      order by f.updated_at desc
      limit 500
    `,
    [requester.userId]
  );

  return result.rows.map((row) => ({
    id: row.id,
    uid: row.uid,
    userId: row.user_id,
    status: row.status,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    completedAt: row.completed_at,
    caseEntry: row.case_entry,
    whoVaData: row.who_va_prefill,
    submission: row.submission,
    validationIssues: row.validation_issues ?? []
  }));
}

function isSelectedFlag(value) {
  return value === "1" || value === 1 || value === true;
}

function dashboardFormType(whoVaData) {
  if (!whoVaData || typeof whoVaData !== "object") return "Not set";
  if (isSelectedFlag(whoVaData.isAdult) || whoVaData.age_group === "adult") return "Adult";
  if (isSelectedFlag(whoVaData.isChild) || whoVaData.age_group === "child") return "Child";
  if (isSelectedFlag(whoVaData.isNeonatal) || whoVaData.age_group === "neonate") return "Neonatal";
  return "Not set";
}

async function listUserDashboard(auth) {
  await ensureDraftTable();
  const requester = await loadAuthenticatedUser(auth);
  const params = requester.role === "admin" ? [] : [requester.userId];
  const userFilter = requester.role === "admin" ? "" : "where f.user_id = $1";
  const result = await pool.query(
    `
      select
        f.id,
        f.uid,
        f.user_id,
        f.status,
        f.created_at,
        f.updated_at,
        f.completed_at,
        f.case_entry,
        f.who_va_prefill,
        u.name as user_name,
        u.email as user_email,
        u.role as user_role,
        u.partner_site,
        u.site_assigned,
        d.id as draft_id,
        d.current_section as draft_section,
        d.updated_at as draft_updated_at
      from who_va_form_entries f
      left join who_va_users u on u.user_id = f.user_id
      left join who_va_drafts d on d.id = f.uid
      ${userFilter}
      order by coalesce(f.completed_at, d.updated_at, f.updated_at) desc
      limit 250
    `,
    params
  );

  const usersById = new Map();
  for (const row of result.rows) {
    const dashboardStatus =
      row.status === "completed" || row.completed_at ? "final" : row.draft_id ? "drafted" : "pending";
    const ownerId = row.user_id ?? "unassigned";
    const owner = usersById.get(ownerId) ?? {
      userId: ownerId,
      name: row.user_name ?? "Unassigned",
      email: row.user_email ?? "",
      role: row.user_role ?? "",
      partnerSite: row.partner_site ?? "",
      siteAssigned: row.site_assigned ?? "",
      counts: { pending: 0, drafted: 0, final: 0 },
      forms: []
    };
    owner.counts[dashboardStatus] += 1;
    owner.forms.push({
      id: row.id,
      uid: row.uid,
      status: dashboardStatus,
      sourceStatus: row.status,
      createdAt: row.created_at,
      updatedAt: row.updated_at,
      completedAt: row.completed_at,
      draftId: row.draft_id,
      draftSection: row.draft_section,
      draftUpdatedAt: row.draft_updated_at,
      caseEntry: row.case_entry,
      whoVaData: row.who_va_prefill,
      formType: dashboardFormType(row.who_va_prefill)
    });
    usersById.set(ownerId, owner);
  }

  return { requester, users: [...usersById.values()] };
}

async function saveFormEntry(payload) {
  const uid = typeof payload.uid === "string" ? payload.uid.trim() : "";
  if (!uid) {
    const error = new Error("uid is required");
    error.statusCode = 400;
    throw error;
  }

  const userId = typeof payload.userId === "string" && payload.userId.trim() ? payload.userId.trim() : null;
  const requestedStatus = typeof payload.status === "string" ? payload.status.trim() : "case-entry";
  const status = formEntryStatuses.has(requestedStatus) ? requestedStatus : "case-entry";
  const authKey =
    typeof payload.authKey === "string" && payload.authKey.trim() ? payload.authKey.trim() : null;
  if (authKey || status === "completed") await verifyUserAuthKey(userId, authKey);
  const caseEntry = payload.caseEntry && typeof payload.caseEntry === "object" ? payload.caseEntry : {};
  validateCaseEntry(caseEntry);
  const whoVaData = payload.whoVaData && typeof payload.whoVaData === "object" ? payload.whoVaData : {};
  const submission = payload.submission && typeof payload.submission === "object" ? payload.submission : null;
  const validationIssues = Array.isArray(payload.validationIssues) ? payload.validationIssues : [];

  const previousResult = await pool.query(
    `
      select uid, user_id, case_entry, who_va_prefill, submission, validation_issues, status, completed_at
      from who_va_form_entries
      where uid = $1
    `,
    [uid]
  );
  const previous = previousResult.rows[0];
  if (previous?.user_id && userId && previous.user_id !== userId) {
    throw badRequest(`Entry ${uid} belongs to another user and cannot be overwritten by ${userId}`);
  }
  const shouldArchivePrevious =
    status === "completed" &&
    previous &&
    (previous.status === "completed" || previous.completed_at || previous.submission != null);
  if (shouldArchivePrevious) {
    await pool.query(
      `
        insert into who_va_recorded_data (
          entry_uid,
          user_id,
          snapshot_type,
          case_entry,
          who_va_prefill,
          submission,
          validation_issues
        )
        values ($1, $2, 'before_update', $3::jsonb, $4::jsonb, $5::jsonb, $6::jsonb)
      `,
      [
        uid,
        previous.user_id,
        JSON.stringify(previous.case_entry ?? {}),
        JSON.stringify(previous.who_va_prefill ?? {}),
        JSON.stringify(previous.submission ?? {}),
        JSON.stringify(previous.validation_issues ?? [])
      ]
    );
  }

  const result = await pool.query(
    `
      insert into who_va_form_entries (
        uid,
        user_id,
        case_entry,
        who_va_prefill,
        submission,
        validation_issues,
        status,
        completed_at
      )
      values ($1, $2, $3::jsonb, $4::jsonb, $5::jsonb, $6::jsonb, $7, case when $7 = 'completed' then now() else null end)
      on conflict (uid) do update set
        user_id = coalesce(excluded.user_id, who_va_form_entries.user_id),
        case_entry = excluded.case_entry,
        who_va_prefill = excluded.who_va_prefill,
        submission = coalesce(excluded.submission, who_va_form_entries.submission),
        validation_issues = excluded.validation_issues,
        status = case
          when who_va_form_entries.status = 'completed' and excluded.status <> 'completed' then who_va_form_entries.status
          else excluded.status
        end,
        completed_at = case
          when excluded.status = 'completed' then now()
          else who_va_form_entries.completed_at
        end,
        updated_at = now()
      returning id, uid, user_id, status, created_at, updated_at, completed_at
    `,
    [
      uid,
      userId,
      JSON.stringify(caseEntry),
      JSON.stringify(whoVaData),
      submission ? JSON.stringify(submission) : null,
      JSON.stringify(validationIssues),
      status
    ]
  );

  const saved = result.rows[0];
  let recordedSnapshot = Boolean(shouldArchivePrevious);
  if (status === "completed") {
    await pool.query(
      `
        insert into who_va_recorded_data (
          entry_uid,
          user_id,
          snapshot_type,
          case_entry,
          who_va_prefill,
          submission,
          validation_issues
        )
        values ($1, $2, 'completed', $3::jsonb, $4::jsonb, $5::jsonb, $6::jsonb)
      `,
      [
        uid,
        userId,
        JSON.stringify(caseEntry),
        JSON.stringify(whoVaData),
        JSON.stringify(submission ?? {}),
        JSON.stringify(validationIssues)
      ]
    );
    recordedSnapshot = true;
  }

  return {
    ...saved,
    archivedPrevious: Boolean(shouldArchivePrevious),
    recordedSnapshot
  };
}

await runMigrations(pool);

const vite = await createViteServer({
  root: "demo",
  server: {
    hmr: { port: HMR_PORT },
    middlewareMode: true
  },
  appType: "spa"
});

function localNetworkUrls(port) {
  return Object.values(networkInterfaces())
    .flat()
    .filter(
      (networkInterface) =>
        networkInterface && networkInterface.family === "IPv4" && !networkInterface.internal
    )
    .map((networkInterface) => `http://${networkInterface.address}:${port}`);
}

const server = createHttpServer(async (request, response) => {
  try {
    if (request.method === "OPTIONS" && request.url?.startsWith("/api/")) {
      response.writeHead(204, { ...corsPreflightHeaders, ...corsHeadersFor(request) });
      response.end();
      return;
    }

    const url = new URL(request.url ?? "/", "http://127.0.0.1");

    if (url.pathname === "/api/health" && request.method === "GET") {
      await pool.query("select 1");
      sendJson(request, response, 200, { ok: true, database: process.env.PGDATABASE ?? "whova" });
      return;
    }

    if (url.pathname.startsWith("/api/attachments/") && request.method === "PUT") {
      const { auth, user } = await requireAuthenticatedUser(request, url);
      if (!auth.accessToken) await verifyUserAuthKey(user.userId, user.authKey);
      const id = decodeURIComponent(url.pathname.slice("/api/attachments/".length));
      const attachment = await saveAttachment(id, request);
      sendJson(request, response, 200, { ok: true, attachment });
      return;
    }

    if (url.pathname.startsWith("/api/attachments/") && request.method === "GET") {
      const id = decodeURIComponent(url.pathname.slice("/api/attachments/".length));
      const attachment = await loadAttachment(id);
      const bytes = await readFile(attachment.storagePath);
      response.writeHead(200, {
        "content-type": attachment.mime_type,
        "content-length": String(bytes.length),
        "content-disposition": `inline; filename="${String(attachment.stored_name).replace(/["\\\r\n]/gu, "_")}"`,
        "cache-control": "private, max-age=3600",
        ...apiHeaders(request)
      });
      response.end(bytes);
      return;
    }

    if (url.pathname === "/api/form-entries" && request.method === "GET") {
      const { auth } = await requireAuthenticatedUser(request, url);
      const entries = await listFormEntries(auth);
      sendJson(request, response, 200, { ok: true, entries });
      return;
    }

    if (url.pathname === "/api/form-entries" && request.method === "POST") {
      const payload = await readJsonBody(request);
      const { user: requester } = await requireAuthenticatedUser(request, url);
      if (!payload.userId) payload.userId = requester.userId;
      if (!payload.authKey && payload.userId === requester.userId) payload.authKey = requester.authKey;
      if (payload.userId !== requester.userId && requester.role !== "admin") {
        throw unauthorized("Token user mismatch");
      }
      const saved = await saveFormEntry(payload);
      sendJson(request, response, 200, { ok: true, saved });
      return;
    }

    if (url.pathname === "/api/dashboard" && request.method === "GET") {
      const { auth } = await requireAuthenticatedUser(request, url);
      const dashboard = await listUserDashboard(auth);
      sendJson(request, response, 200, { ok: true, ...dashboard });
      return;
    }

    if (url.pathname === "/api/mobile-sync" && request.method === "GET") {
      const { auth } = await requireAuthenticatedUser(request, url);
      const entries = await listMobileSyncEntries(auth);
      sendJson(request, response, 200, { ok: true, entries });
      return;
    }

    if (url.pathname === "/api/users" && request.method === "POST") {
      const user = await registerUser(await readJsonBody(request), request, url);
      sendJson(request, response, 200, { ok: true, user });
      return;
    }

    if (url.pathname === "/api/users" && request.method === "GET") {
      const auth = authFromRequest(request, url);
      const users = await listUsers(auth);
      sendJson(request, response, 200, { ok: true, users });
      return;
    }

    if (url.pathname.startsWith("/api/users/") && request.method === "PATCH") {
      const auth = authFromRequest(request, url);
      const userId = decodeURIComponent(url.pathname.slice("/api/users/".length));
      const user = await updateUserByAdmin(userId, await readJsonBody(request), auth);
      sendJson(request, response, 200, { ok: true, user });
      return;
    }

    if (url.pathname === "/api/profile" && request.method === "GET") {
      const { user } = await requireAuthenticatedUser(request, url);
      sendJson(request, response, 200, { ok: true, user });
      return;
    }

    if (url.pathname === "/api/profile/password" && request.method === "POST") {
      const auth = authFromRequest(request, url);
      const user = await changeUserPassword(await readJsonBody(request), auth);
      sendJson(request, response, 200, { ok: true, user });
      return;
    }

    if (url.pathname === "/api/login" && request.method === "POST") {
      const payload = await readJsonBody(request);
      const user = await loginUser(payload, request);
      const session = await createUserSession(user.userId, payload.deviceId);
      const entries = await listMobileSyncEntries({ accessToken: session.accessToken });
      sendJson(request, response, 200, { ok: true, user, ...session, entries });
      return;
    }

    if (url.pathname === "/api/refresh-token" && request.method === "POST") {
      const session = await refreshUserSession(await readJsonBody(request));
      sendJson(request, response, 200, { ok: true, ...session });
      return;
    }

    if (url.pathname === "/api/logout" && request.method === "POST") {
      await revokeUserSession(await readJsonBody(request), request);
      sendJson(request, response, 200, { ok: true });
      return;
    }

    if (url.pathname === "/api/drafts" && request.method === "POST") {
      const { auth } = await requireAuthenticatedUser(request, url);
      const saved = await saveDraft(await readJsonBody(request), auth);
      sendJson(request, response, 200, { ok: true, saved });
      return;
    }

    if (url.pathname.startsWith("/api/drafts/") && request.method === "GET") {
      const id = decodeURIComponent(url.pathname.slice("/api/drafts/".length));
      const { auth } = await requireAuthenticatedUser(request, url);
      const draft = await loadDraft(id, auth);
      if (!draft) {
        sendJson(request, response, 404, { ok: false, error: "Draft not found" });
        return;
      }
      sendJson(request, response, 200, { ok: true, draft });
      return;
    }

    if (url.pathname.startsWith("/api/drafts/") && request.method === "DELETE") {
      const id = decodeURIComponent(url.pathname.slice("/api/drafts/".length));
      const { auth } = await requireAuthenticatedUser(request, url);
      await removeDraft(id, auth);
      sendJson(request, response, 200, { ok: true });
      return;
    }

    response.setHeader("x-content-type-options", "nosniff");
    response.setHeader("referrer-policy", "no-referrer");
    vite.middlewares(request, response);
  } catch (error) {
    console.error(error);
    const statusCode = Number(error?.statusCode ?? 500);
    sendJson(request, response, statusCode, {
      ok: false,
      error:
        statusCode >= 500 ? "Internal server error" : error instanceof Error ? error.message : String(error)
    });
  }
});

server.listen(PORT, HOST, () => {
  const localUrl = `http://127.0.0.1:${PORT}`;
  const boundUrl = `http://${HOST}:${PORT}`;
  const mobileUrls = localNetworkUrls(PORT);
  console.log(`WHO VA demo with Postgres saving: ${localUrl}`);
  if (HOST !== "127.0.0.1" && mobileUrls.length > 0)
    console.log(`Mobile devices can use: ${mobileUrls.join(", ")}`);
  if (HOST !== "0.0.0.0" && boundUrl !== localUrl) console.log(`Bound to: ${boundUrl}`);
});

process.on("SIGINT", async () => {
  await vite.close();
  await pool.end();
  server.close(() => process.exit(0));
});
