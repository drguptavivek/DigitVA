/*
 * JNI shim over the NativeAOT ICD-API engine (libdigitva_icd11.so, private/icd11-offline-spike). Adapted from the
 * spike's apptest/jni/shim.c. The engine exports a C ABI:
 *   char *digitva_icd11_init(const char *bundleDir, const char *dataDir)   NULL on success, else an error text
 *   char *digitva_icd11_{search,codeinfo,doris,codedit}(const char *json, int *status)
 *   void  digitva_icd11_free(char *)
 * Calls are serialized by the Kotlin side (one worker thread); nothing here is thread-safe on its own.
 * Engine error text can hold stack traces and certificate content: it is never logged or returned from here.
 */
#include <jni.h>
#include <dlfcn.h>
#include <string.h>
#include <stdlib.h>

typedef char *(*init_t)(const char *, const char *);
typedef char *(*call_t)(const char *, int *);
typedef void (*free_t)(char *);

static void *engine;
static init_t p_init;
static call_t p_calls[4]; /* index = op: 0 search, 1 codeinfo, 2 doris, 3 codedit */
static free_t p_free;

static const char *const CALL_SYMBOLS[4] = {
    "digitva_icd11_search", "digitva_icd11_codeinfo", "digitva_icd11_doris", "digitva_icd11_codedit"};

/* dlopen the engine by absolute path. Returns 0 on success, a small code otherwise (no dlerror text leaves here). */
JNIEXPORT jint JNICALL Java_expo_modules_digitvaicd11_EngineJni_load(JNIEnv *env, jclass cls, jstring path) {
  if (engine) return 0;
  const char *p = (*env)->GetStringUTFChars(env, path, 0);
  if (!p) return 1;
  void *h = dlopen(p, RTLD_NOW);
  (*env)->ReleaseStringUTFChars(env, path, p);
  if (!h) return 2;
  p_init = (init_t)dlsym(h, "digitva_icd11_init");
  p_free = (free_t)dlsym(h, "digitva_icd11_free");
  for (int i = 0; i < 4; i++) p_calls[i] = (call_t)dlsym(h, CALL_SYMBOLS[i]);
  if (!p_init || !p_free || !p_calls[0] || !p_calls[1] || !p_calls[2] || !p_calls[3]) return 3;
  engine = h;
  return 0;
}

/* Returns 0 on success, 1 when the engine reported an error (text freed, not returned), 2 when not loaded. */
JNIEXPORT jint JNICALL Java_expo_modules_digitvaicd11_EngineJni_initEngine(JNIEnv *env, jclass cls, jstring bundle, jstring data) {
  if (!engine) return 2;
  const char *b = (*env)->GetStringUTFChars(env, bundle, 0);
  const char *d = (*env)->GetStringUTFChars(env, data, 0);
  char *err = (b && d) ? p_init(b, d) : NULL;
  int failed = (!b || !d) ? 1 : (err != NULL);
  if (b) (*env)->ReleaseStringUTFChars(env, bundle, b);
  if (d) (*env)->ReleaseStringUTFChars(env, data, d);
  if (err) p_free(err);
  return failed;
}

/* Runs one call. Fills status[0]. Returns the response bytes (UTF-8 JSON), or NULL when the engine is not loaded. */
JNIEXPORT jbyteArray JNICALL Java_expo_modules_digitvaicd11_EngineJni_call(JNIEnv *env, jclass cls, jint op, jstring input, jintArray status) {
  if (!engine || op < 0 || op > 3) return NULL;
  const char *in = (*env)->GetStringUTFChars(env, input, 0);
  if (!in) return NULL;
  int st = 0;
  char *out = p_calls[op](in, &st);
  (*env)->ReleaseStringUTFChars(env, input, in);
  jint st_out = st;
  (*env)->SetIntArrayRegion(env, status, 0, 1, &st_out);
  if (!out) return NULL;
  size_t n = strlen(out);
  jbyteArray arr = (*env)->NewByteArray(env, (jsize)n);
  if (arr) (*env)->SetByteArrayRegion(env, arr, 0, (jsize)n, (const jbyte *)out);
  p_free(out);
  return arr;
}
