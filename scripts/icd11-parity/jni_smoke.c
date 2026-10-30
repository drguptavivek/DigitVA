/*
 * JNI smoke check of the Collect Plus shim (modules/digitva-icd11/android/src/main/cpp/shim.c) on a phone, without an APK.
 * The shim is compiled unchanged into libdigitvaicd11shim.so; this program dlopens it, looks up the Java_..._EngineJni_*
 * functions by name and calls them with a minimal fake JNIEnv (the five JNI functions the shim uses, counting every
 * Get/Release pair and able to fail a call on request). It exercises the real shim code against a real engine library:
 * the old pinned one (no digitva_icd11_call), which load must refuse with 3, or a new one.
 *
 * Checks, in order (each prints "ok <name>" or "FAIL <name>: ..."; the exit status is the number of failures):
 *   before load: initEngine 2, callOp NULL with status untouched
 *   load: unreadable path string 1, missing file 2, a library without the engine symbols 3, then the engine under test:
 *         EXPECT_LOAD 0 (a library with digitva_icd11_call: loads, loads again) or 3 (an old one: refused, refused again)
 *   a refused library leaves the shim unloaded: initEngine 2, callOp NULL with the status untouched; the run ends there
 *   initEngine: a bad directory 1 with none of the engine's error text on stdout or stderr, then the real directories 0
 *   callOp(): search, a refused op (400), bad JSON (400), `limit` and its bounds (invalid 400, with flatResults=false 400), refused
 *             `include`, a mistyped argument, entity, DORIS and CoDEdit (200), a certificate that is not JSON (400, no trace)
 *   a failed NewByteArray gives NULL without crashing; every GetStringUTFChars has its Release; no reply holds a stack trace or path
 *
 * Build: $NDK/.../aarch64-linux-android29-clang -O2 -o jni_smoke jni_smoke.c -ldl
 * usage: jni_smoke SHIM.so ENGINE.so BUNDLE_DIR DATA_DIR EXPECT_LOAD(0|3)
 */
#include <dlfcn.h>
#include <jni.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* --- fake JNIEnv: strings are struct fake_str, byte and int arrays are plain buffers --- */
struct fake_str { const char *utf; int fail; };
struct fake_bytes { jsize n; unsigned char *data; };
struct fake_ints { jint v[4]; };

static int gets, releases, fail_new_array;

/* Like ART: Get hands out a fresh copy and Release frees it, so a shim that used the text after releasing it, released
 * the wrong pointer, or released twice reads poisoned memory or fails the pointer check here instead of passing. */
static const char *live[64];
static int bad_releases;
static const char *f_get(JNIEnv *e, jstring s, jboolean *c) {
  (void)e;
  struct fake_str *f = (struct fake_str *)s;
  if (f->fail) return NULL;
  char *copy = strdup(f->utf);
  for (int i = 0; i < 64; i++) if (!live[i]) { live[i] = copy; break; }
  if (c) *c = JNI_TRUE;
  gets++;
  return copy;
}
static void f_release(JNIEnv *e, jstring s, const char *p) {
  (void)e; (void)s;
  for (int i = 0; i < 64; i++) {
    if (live[i] == p) {
      live[i] = NULL;
      memset((char *)p, 'X', strlen(p)); /* poison before freeing */
      free((char *)p);
      releases++;
      return;
    }
  }
  bad_releases++;
  fprintf(stdout, "FAIL: ReleaseStringUTFChars on a pointer Get did not hand out (or released twice)\n");
}
static jbyteArray f_new_bytes(JNIEnv *e, jsize n) {
  (void)e;
  if (fail_new_array) return NULL;
  struct fake_bytes *b = calloc(1, sizeof *b);
  b->n = n; b->data = malloc(n + 1);
  return (jbyteArray)b;
}
static void f_set_bytes(JNIEnv *e, jbyteArray a, jsize start, jsize len, const jbyte *buf) {
  (void)e;
  struct fake_bytes *b = (struct fake_bytes *)a;
  memcpy(b->data + start, buf, len);
}
static void f_set_ints(JNIEnv *e, jintArray a, jsize start, jsize len, const jint *buf) {
  (void)e;
  memcpy(((struct fake_ints *)a)->v + start, buf, len * sizeof(jint));
}

static struct JNINativeInterface table;
static const struct JNINativeInterface *table_ptr = &table;
#define ENV ((JNIEnv *)&table_ptr)

/* --- the shim's functions --- */
typedef jint (*load_t)(JNIEnv *, jclass, jstring);
typedef jint (*init_t)(JNIEnv *, jclass, jstring, jstring);
typedef jbyteArray (*callop_t)(JNIEnv *, jclass, jstring, jstring, jintArray);
static load_t jload; static init_t jinit; static callop_t jcallop;

static int failures;
static void check(int cond, const char *name, const char *detail) {
  if (cond) printf("ok %s\n", name);
  else { printf("FAIL %s: %s\n", name, detail); failures++; }
}

static struct fake_str S(const char *utf) { struct fake_str s = {utf, 0}; return s; }
#define STR(v, text) struct fake_str v##_s = S(text); jstring v = (jstring)&v##_s
#define BAD(v) struct fake_str v##_s = {"x", 1}; jstring v = (jstring)&v##_s

/* The reply bytes as a C string (the buffer has one spare byte), or NULL; frees the fake array. */
static char *take(jbyteArray a) {
  if (!a) return NULL;
  struct fake_bytes *b = (struct fake_bytes *)a;
  b->data[b->n] = 0;
  char *s = (char *)b->data;
  free(b);
  return s;
}

static int looks_like_trace(const char *s) {
  return s && (strstr(s, " at ") || strstr(s, "Exception") || strstr(s, "/data/local") || strstr(s, ".cs:line"));
}

static double now_ms(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1e3 + t.tv_nsec / 1e6; }

int main(int argc, char **argv) {
  if (argc != 6) { fprintf(stderr, "usage: jni_smoke SHIM.so ENGINE.so BUNDLE_DIR DATA_DIR EXPECT_LOAD\n"); return 99; }
  const char *shim_path = argv[1], *engine_path = argv[2], *bundle = argv[3], *data = argv[4];
  int expect_load = atoi(argv[5]);
  table.GetStringUTFChars = f_get; table.ReleaseStringUTFChars = f_release; table.NewByteArray = f_new_bytes;
  table.SetByteArrayRegion = f_set_bytes; table.SetIntArrayRegion = f_set_ints;

  void *shim = dlopen(shim_path, RTLD_NOW);
  if (!shim) { fprintf(stderr, "dlopen shim: %s\n", dlerror()); return 98; }
  jload = (load_t)dlsym(shim, "Java_expo_modules_digitvaicd11_EngineJni_load");
  jinit = (init_t)dlsym(shim, "Java_expo_modules_digitvaicd11_EngineJni_initEngine");
  jcallop = (callop_t)dlsym(shim, "Java_expo_modules_digitvaicd11_EngineJni_callOp");
  if (!jload || !jinit || !jcallop) { fprintf(stderr, "a JNI function is missing from the shim\n"); return 97; }

  struct fake_ints st; char detail[256];
  STR(op_search, "search"); STR(args_q, "{\"q\":\"heart%\"}");

  /* before load */
  STR(b0, "/b"); STR(d0, "/d");
  check(jinit(ENV, NULL, b0, d0) == 2, "initEngine before load is 2", "");
  st.v[0] = -7;
  check(jcallop(ENV, NULL, op_search, args_q, (jintArray)&st) == NULL && st.v[0] == -7, "callOp before load is NULL, status untouched", "");

  /* load */
  BAD(unreadable);
  check(jload(ENV, NULL, unreadable) == 1, "load with an unreadable path string is 1", "");
  STR(missing, "/data/local/tmp/no_such_library_zz.so");
  check(jload(ENV, NULL, missing) == 2, "load of a missing file is 2", "");
  STR(libm, "libm.so");
  check(jload(ENV, NULL, libm) == 3, "load of a library without the engine symbols is 3", "");
  STR(engine, engine_path);
  int r = jload(ENV, NULL, engine);
  snprintf(detail, sizeof detail, "returned %d", r);
  check(r == expect_load, expect_load ? "load of a library without digitva_icd11_call is refused with 3" : "load of the engine is 0", detail);
  r = jload(ENV, NULL, engine);
  snprintf(detail, sizeof detail, "returned %d", r);
  check(r == expect_load, expect_load ? "a second load of it is refused with 3 too" : "a second load is 0", detail);
  if (expect_load) {
    /* A refused library must not be half-loaded: nothing can be initialised or called through it. */
    check(jinit(ENV, NULL, b0, d0) == 2, "initEngine after a refused load is 2", "");
    st.v[0] = -9;
    check(jcallop(ENV, NULL, op_search, args_q, (jintArray)&st) == NULL && st.v[0] == -9, "callOp after a refused load is NULL, status untouched", "");
    snprintf(detail, sizeof detail, "%d gets, %d releases", gets, releases);
    check(gets == releases && bad_releases == 0, "every string was released", detail);
    printf("%s: %d failure(s)\n", failures == 0 ? "PASS" : "FAIL", failures);
    return failures;
  }

  /* init: a bad directory first, whose error text must not surface; then the real one */
  STR(bad_b, "/data/local/tmp/no_such_bundle_dir_zz"); STR(bad_d, "/data/local/tmp/no_such_data_dir_zz");
  fflush(stdout); fflush(stderr);
  r = jinit(ENV, NULL, bad_b, bad_d);
  check(r == 1, "initEngine with a missing directory is 1 (engine error freed, not returned)", "");
  BAD(unreadable_dir);
  STR(real_b, bundle); STR(real_d, data);
  check(jinit(ENV, NULL, unreadable_dir, real_d) == 1, "initEngine with an unreadable string is 1", "");
  double t0 = now_ms();
  r = jinit(ENV, NULL, real_b, real_d);
  snprintf(detail, sizeof detail, "returned %d", r);
  check(r == 0, "initEngine with the real directories is 0", detail);
  printf("note init %.0f ms\n", now_ms() - t0);
  if (r != 0) { printf("failures %d\n", failures); return failures; }

  char *out;
  /* A certificate WHO accepts (first of make_certificates.py's, with the two quotes escaped for C), as the call's `certificate` argument. */
  STR(op_doris, "doris"); STR(op_codedit, "codedit");
  STR(cert_args, "{\"certificate\":{\"AdministrativeData\":{\"DateBirth\":\"1972-08-28\",\"DateDeath\":\"2026-10-09\",\"Sex\":9},\"ICDVersion\":\"ICD11\",\"MannerOfDeath\":{\"MannerOfDeath\":6},\"Part1\":[{\"Conditions\":[{\"Code\":\"1D01.0Z\",\"Interval\":\"P4D\",\"LinearizationURI\":\"http://id.who.int/icd/release/11/2026-01/mms/684930313/unspecified\",\"Text\":\"Bacterial meningitis\"}]},{\"Conditions\":[{\"Code\":\"1B10.Z\",\"Interval\":\"P6Y\",\"LinearizationURI\":\"http://id.who.int/icd/release/11/2026-01/mms/882244568/unspecified\",\"Text\":\"Respiratory tuberculosis\"}]}],\"Part2\":{\"Conditions\":[{\"Code\":\"1A07.Z\",\"Interval\":\"PT12H\",\"LinearizationURI\":\"http://id.who.int/icd/release/11/2026-01/mms/1528414070/unspecified\",\"Text\":\"Typhoid fever\"}]}}}");
  STR(op_bogus, "bogus"); STR(empty, "{}");
  st.v[0] = -1; out = take(jcallop(ENV, NULL, op_search, args_q, (jintArray)&st));
  check(out && st.v[0] == 200 && strstr(out, "destinationEntities"), "callOp search answers 200", out ? out : "NULL"); free(out);
  STR(op_codeinfo, "codeinfo"); STR(code_args, "{\"code\":\"BA41.Z\"}");
  st.v[0] = -1; out = take(jcallop(ENV, NULL, op_codeinfo, code_args, (jintArray)&st));
  check(out && st.v[0] == 200 && strstr(out, "stemId"), "callOp codeinfo answers 200 with a stemId", out ? out : "NULL"); free(out);
  st.v[0] = -1; out = take(jcallop(ENV, NULL, op_doris, cert_args, (jintArray)&st));
  check(out && st.v[0] == 200 && out[0] == '{' && strstr(out, "\"stemCode\""), "callOp doris answers 200 with camelCase JSON", out ? out : "NULL"); free(out);
  st.v[0] = -1; out = take(jcallop(ENV, NULL, op_codedit, cert_args, (jintArray)&st));
  check(out && st.v[0] == 200 && out[0] == '{', "callOp codedit answers 200 with JSON", out ? out : "NULL"); free(out);
  STR(junk, "{\"certificate\":this is not json}");
  st.v[0] = -1; out = take(jcallop(ENV, NULL, op_doris, junk, (jintArray)&st));
  check(out && st.v[0] == 400 && !looks_like_trace(out), "callOp doris with a certificate that is not JSON is 400, no trace in the reply", out ? out : "NULL"); free(out);
  st.v[0] = -1; out = take(jcallop(ENV, NULL, op_bogus, empty, (jintArray)&st));
  check(out && st.v[0] == 400 && strstr(out, "unknown op"), "callOp with an unknown op is 400", out ? out : "NULL"); free(out);
  STR(not_json, "{not json");
  st.v[0] = -1; out = take(jcallop(ENV, NULL, op_search, not_json, (jintArray)&st));
  check(out && st.v[0] == 400 && strstr(out, "bad json"), "callOp with bad JSON is 400", out ? out : "NULL"); free(out);
  STR(limited, "{\"q\":\"heart%\",\"limit\":3}");
  st.v[0] = -1; out = take(jcallop(ENV, NULL, op_search, limited, (jintArray)&st));
  int hits = 0; if (out) for (const char *p = out; (p = strstr(p, "\"stemId\"")); p++) hits++;
  snprintf(detail, sizeof detail, "status %d, %d stemIds", st.v[0], hits);
  check(out && st.v[0] == 200 && hits <= 3 && strstr(out, "\"resultChopped\":true"), "callOp search with limit 3 keeps at most 3 and sets resultChopped", detail); free(out);
  STR(bad_limit, "{\"q\":\"heart%\",\"limit\":0}");
  st.v[0] = -1; out = take(jcallop(ENV, NULL, op_search, bad_limit, (jintArray)&st));
  check(out && st.v[0] == 400 && strstr(out, "bad argument: limit"), "callOp search with limit 0 is 400", out ? out : "NULL"); free(out);
  STR(nested, "{\"q\":\"heart%\",\"limit\":3,\"flatResults\":false}");
  st.v[0] = -1; out = take(jcallop(ENV, NULL, op_search, nested, (jintArray)&st));
  check(out && st.v[0] == 400 && strstr(out, "limit requires flatResults") && !strstr(out, "destinationEntities"), "callOp search with limit and flatResults false is 400 before WHO runs", out ? out : "NULL"); free(out);
  STR(flat, "{\"q\":\"heart%\",\"limit\":3,\"flatResults\":true}");
  st.v[0] = -1; out = take(jcallop(ENV, NULL, op_search, flat, (jintArray)&st));
  check(out && st.v[0] == 200 && strstr(out, "\"resultChopped\":true"), "callOp search with limit and flatResults true answers 200", out ? out : "NULL"); free(out);
  STR(unlimited_nested, "{\"q\":\"tetanus%\",\"flatResults\":false}");
  st.v[0] = -1; out = take(jcallop(ENV, NULL, op_search, unlimited_nested, (jintArray)&st));
  check(out && st.v[0] == 200 && strstr(out, "destinationEntities"), "callOp search with flatResults false and no limit is WHO's own reply", out ? out : "NULL"); free(out);
  STR(op_entity, "entity"); STR(descendant, "{\"id\":\"391388807\",\"include\":\"descendant\"}");
  st.v[0] = -1; out = take(jcallop(ENV, NULL, op_entity, descendant, (jintArray)&st));
  check(out && st.v[0] == 400 && strstr(out, "include descendant is not allowed"), "callOp entity with include descendant is 400", out ? out : "NULL"); free(out);
  STR(entity_ok, "{\"id\":\"391388807\"}");
  st.v[0] = -1; out = take(jcallop(ENV, NULL, op_entity, entity_ok, (jintArray)&st));
  check(out && st.v[0] == 200 && strstr(out, "\"@id\""), "callOp entity answers 200 with a JSON-LD entity", out ? out : "NULL"); free(out);
  STR(wrong_type, "{\"q\":5}");
  st.v[0] = -1; out = take(jcallop(ENV, NULL, op_search, wrong_type, (jintArray)&st));
  check(out && st.v[0] == 400 && strstr(out, "bad argument: q") && !looks_like_trace(out), "callOp with a mistyped argument is 400 naming it, no value, no trace", out ? out : "NULL"); free(out);
  BAD(unreadable_in);
  st.v[0] = -9;
  check(jcallop(ENV, NULL, unreadable_in, args_q, (jintArray)&st) == NULL && st.v[0] == -9, "callOp with an unreadable op string is NULL, status untouched", "");
  check(jcallop(ENV, NULL, op_search, unreadable_in, (jintArray)&st) == NULL && st.v[0] == -9, "callOp with unreadable arguments is NULL, status untouched", "");

  /* a failed array allocation */
  fail_new_array = 1; st.v[0] = -1;
  jbyteArray none = jcallop(ENV, NULL, op_search, args_q, (jintArray)&st);
  fail_new_array = 0;
  check(none == NULL && st.v[0] == 200, "a failed NewByteArray gives NULL (status 200 was reported) without a crash", "");

  /* the strings were all released */
  snprintf(detail, sizeof detail, "%d gets, %d releases", gets, releases);
  check(gets == releases, "every GetStringUTFChars has a ReleaseStringUTFChars", detail);
  check(bad_releases == 0, "every release matches a pointer Get handed out, once", detail);
  printf("%s: %d failure(s)\n", failures == 0 ? "PASS" : "FAIL", failures);
  return failures;
}
