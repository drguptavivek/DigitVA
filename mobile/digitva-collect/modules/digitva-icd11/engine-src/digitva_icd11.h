/*
 * C ABI of the NativeAOT ICD-API engine (Bridge.cs), as the iOS framework exports it. Android dlopens the same three
 * symbols from libdigitva_icd11.so (android/src/main/cpp/shim.c). Strings are UTF-8; every non-NULL return is freed with
 * digitva_icd11_free. Not thread-safe on its own: callers serialize.
 */
#ifndef DIGITVA_ICD11_H
#define DIGITVA_ICD11_H

/* NULL on success, else an error text (may hold stack traces and paths: never log or return it). */
char *digitva_icd11_init(const char *bundleDir, const char *dataDir);
/* The one call: an op name and a JSON object of arguments. Writes the HTTP-like status to *status. */
char *digitva_icd11_call(const char *op, const char *json, int *status);
void digitva_icd11_free(char *p);

#endif
