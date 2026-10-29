/*
 * Runs the Collect Plus ICD-11 engine (libdigitva_icd11.so) on a phone over a fixed request list.
 * Input lines, tab-separated:
 *   D\t<id>\t<certificate text>      DORIS then CoDEdit (the text is passed as is, even when it is not JSON)
 *   S\t<id>\t<search text>           search
 *   C\t<id>\t<code or expression>    code info
 * Output (stdout), one line each:
 *   META\tinit_ms\t<ms>\trss_mb\t<n>
 *   CERT\t<id>\t<doris_ms>\t<codedit_ms>\t<doris_status>\t<codedit_status>\t<doris body>\t<codedit body>
 *   SEARCH\t<id>\t<ms>\t<status>\t<body>      CODEINFO\t<id>\t<ms>\t<status>\t<body>
 *   META\tend\trss_mb\t<n>\tpeak_mb\t<n>
 * Bodies never hold a raw tab or newline (JSON escapes them), so fields split cleanly.
 * Build: $NDK/toolchains/llvm/prebuilt/darwin-x86_64/bin/aarch64-linux-android29-clang -O2 -o phone_harness phone_harness.c -ldl
 * usage: phone_harness lib.so bundleDir dataDir input.tsv
 */
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef char *(*init_t)(const char *, const char *);
typedef char *(*call_t)(const char *, int *);
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
  call_t doris = (call_t)dlsym(lib, "digitva_icd11_doris"), codedit = (call_t)dlsym(lib, "digitva_icd11_codedit");
  call_t search = (call_t)dlsym(lib, "digitva_icd11_search"), codeinfo = (call_t)dlsym(lib, "digitva_icd11_codeinfo");
  free_t release = (free_t)dlsym(lib, "digitva_icd11_free");
  if (!init || !doris || !codedit || !search || !codeinfo || !release) { fprintf(stderr, "missing engine symbol\n"); return 1; }

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
      double a = now_ms(); char *d = doris(arg, &s1); double b = now_ms(); char *c = codedit(arg, &s2); double e = now_ms();
      printf("CERT\t%s\t%.2f\t%.2f\t%d\t%d\t", id, b - a, e - b, s1, s2); put_body(d); putchar('\t'); put_body(c); putchar('\n');
      release(d); release(c);
    } else if (line[0] == 'S' || line[0] == 'C') {
      int s = 0; double a = now_ms(); char *r = (line[0] == 'S' ? search : codeinfo)(arg, &s); double b = now_ms();
      printf("%s\t%s\t%.2f\t%d\t", line[0] == 'S' ? "SEARCH" : "CODEINFO", id, b - a, s); put_body(r); putchar('\n');
      release(r);
    }
  }
  free(line); fclose(in);
  printf("META\tend\trss_mb\t%ld\tpeak_mb\t%ld\n", status_kb("VmRSS:") / 1024, status_kb("VmHWM:") / 1024);
  return 0;
}
