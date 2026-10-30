/*
 * JNI shim over the NativeAOT ICD-API engine (libdigitva_icd11.so, engine-src/Bridge.cs). The engine exports a C ABI:
 *   char *digitva_icd11_init(const char *bundleDir, const char *dataDir)   NULL on success, else an error text
 *   char *digitva_icd11_call(const char *op, const char *json, int *status)   the one call: an op name and a JSON object of arguments
 *   void  digitva_icd11_free(char *)
 * load() requires all three: a library without digitva_icd11_call (an engine archive from before 2026.10.29) is refused with 3,
 * so the app reports the engine unavailable instead of running it half-way. The APK always ships this shim, the Kotlin and the
 * JS built in the same CI run as the staged engine, so a mismatch can only come from a stale pin.
 * Calls are serialized by the Kotlin side (one worker thread); nothing here is thread-safe on its own.
 * Engine error text can hold stack traces and certificate content: it is never logged or returned from here.
 */
#include <jni.h>
#include <dlfcn.h>
#include <string.h>
#include <stdlib.h>

typedef char *(*init_t)(const char *, const char *);
typedef char *(*callop_t)(const char *, const char *, int *);
typedef void (*free_t)(char *);

static void *engine;
static init_t p_init;
static callop_t p_callop;
static free_t p_free;

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
  p_callop = (callop_t)dlsym(h, "digitva_icd11_call");
  if (!p_init || !p_free || !p_callop) return 3;
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

/* Copies an engine result into a new byte array and frees it. NULL in, NULL out. */
static jbyteArray take_result(JNIEnv *env, char *out) {
  if (!out) return NULL;
  size_t n = strlen(out);
  jbyteArray arr = (*env)->NewByteArray(env, (jsize)n);
  if (arr) (*env)->SetByteArrayRegion(env, arr, 0, (jsize)n, (const jbyte *)out);
  p_free(out);
  return arr;
}

/* Runs one call (op name + JSON arguments). Fills status[0]. NULL when the engine is not loaded or returns nothing. */
JNIEXPORT jbyteArray JNICALL Java_expo_modules_digitvaicd11_EngineJni_callOp(JNIEnv *env, jclass cls, jstring op, jstring json, jintArray status) {
  if (!engine) return NULL;
  const char *o = (*env)->GetStringUTFChars(env, op, 0);
  const char *j = (*env)->GetStringUTFChars(env, json, 0);
  if (!o || !j) {
    if (o) (*env)->ReleaseStringUTFChars(env, op, o);
    if (j) (*env)->ReleaseStringUTFChars(env, json, j);
    return NULL;
  }
  int st = 0;
  char *out = p_callop(o, j, &st);
  (*env)->ReleaseStringUTFChars(env, op, o);
  (*env)->ReleaseStringUTFChars(env, json, j);
  jint st_out = st;
  (*env)->SetIntArrayRegion(env, status, 0, 1, &st_out);
  return take_result(env, out);
}
