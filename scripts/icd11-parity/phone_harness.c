/*
 * Runs the Collect Plus ICD-11 engine (libdigitva_icd11.so) on a phone over a fixed request list, through its one call
 * digitva_icd11_call(op, json, &status), as the app does.
 * Input lines, tab-separated:
 *   D\t<id>\t<certificate text>      DORIS then CoDEdit with the text as the `certificate` argument ({"certificate":<text>}); text that is
 *                                    not JSON makes the arguments invalid JSON, which the bridge refuses (400)
 *   G\t<id>\t<op>\t<json>           any call (op: search, codeinfo, entity, foundation_entity, doris, codedit; json: the object of named arguments)
 * Output (stdout), one line each:
 *   META\tinit_ms\t<ms>\trss_mb\t<n>
 *   CERT\t<id>\t<doris_ms>\t<codedit_ms>\t<doris_status>\t<codedit_status>\t<doris body>\t<codedit body>
 *   CALL\t<id>\t<ms>\t<status>\t<body>
 *   META\tend\trss_mb\t<n>\tpeak_mb\t<n>
 * Bodies never hold a raw tab or newline (JSON escapes them), so fields split cleanly.
 * A library without digitva_icd11_call is refused at the start (as the app's shim refuses it).
 * Build: $NDK/toolchains/llvm/prebuilt/darwin-x86_64/bin/aarch64-linux-android29-clang -O2 -o phone_harness phone_harness.c -ldl
 * usage: phone_harness lib.so bundleDir dataDir input.tsv
 */
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef char *(*init_t)(const char *, const char *);
typedef char *(*callop_t)(const char *, const char *, int *);
typedef void (*free_t)(char *);

static double now_ms(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1e3 + t.tv_nsec / 1e6; }

static long status_kb(const char *key) {
  FILE *f = fopen("/proc/self/status", "r"); char line[256]; long v = -1; size_t n = strlen(key);
  while (f && fgets(line, sizeof line, f)) if (!strncmp(line, key, n)) v = atol(line + n);
  if (f) fclose(f);
  return v;
}

/* Prints a body with any raw newline or tab turned into a space, so one record stays on one line. */
static void put_body(const char *s) {
  for (; s && *s; s++) putchar(*s == '\n' || *s == '\t' || *s == '\r' ? ' ' : *s);
}

int main(int argc, char **argv) {
  if (argc != 5) { fprintf(stderr, "usage: phone_harness lib.so bundleDir dataDir input.tsv\n"); return 2; }
  void *lib = dlopen(argv[1], RTLD_NOW);
  if (!lib) { fprintf(stderr, "dlopen: %s\n", dlerror()); return 1; }
  init_t init = (init_t)dlsym(lib, "digitva_icd11_init");
  callop_t callop = (callop_t)dlsym(lib, "digitva_icd11_call");
  free_t release = (free_t)dlsym(lib, "digitva_icd11_free");
  if (!init || !callop || !release) { fprintf(stderr, "missing engine symbol (digitva_icd11_init, digitva_icd11_call or digitva_icd11_free)\n"); return 1; }

  double t0 = now_ms();
  char *err = init(argv[2], argv[3]);
  if (err) { fprintf(stderr, "init failed\n"); release(err); return 1; }
  printf("META\tinit_ms\t%.0f\trss_mb\t%ld\n", now_ms() - t0, status_kb("VmRSS:") / 1024);

  FILE *in = fopen(argv[4], "r");
  if (!in) { fprintf(stderr, "cannot open %s\n", argv[4]); return 1; }
  size_t cap = 0; char *line = NULL; ssize_t len;
  while ((len = getline(&line, &cap, in)) > 0) {
    if (line[len - 1] == '\n') line[len - 1] = 0;
    char *id = strchr(line, '\t'); if (!id) continue; *id++ = 0;
    char *arg = strchr(id, '\t'); if (!arg) continue; *arg++ = 0;
    if (line[0] == 'D') {
      int s1 = 0, s2 = 0;
      size_t n = strlen(arg) + 32; char *args = malloc(n); snprintf(args, n, "{\"certificate\":%s}", arg);
      double a = now_ms(); char *d = callop("doris", args, &s1); double b = now_ms(); char *c = callop("codedit", args, &s2); double e = now_ms();
      free(args);
      printf("CERT\t%s\t%.2f\t%.2f\t%d\t%d\t", id, b - a, e - b, s1, s2); put_body(d); putchar('\t'); put_body(c); putchar('\n');
      release(d); release(c);
    } else if (line[0] == 'G') {
      char *json = strchr(arg, '\t'); if (!json) continue; *json++ = 0;
      int s = 0; double a = now_ms(); char *r = callop(arg, json, &s); double b = now_ms();
      printf("CALL\t%s\t%.2f\t%d\t", id, b - a, s); put_body(r ? r : "null"); putchar('\n');
      if (r) release(r);
    }
  }
  free(line); fclose(in);
  printf("META\tend\trss_mb\t%ld\tpeak_mb\t%ld\n", status_kb("VmRSS:") / 1024, status_kb("VmHWM:") / 1024);
  return 0;
}
