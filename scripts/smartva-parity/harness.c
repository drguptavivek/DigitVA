/*
 * Scores a fixed request list with the Collect Plus SmartVA engine through the C call both native modules make:
 * smartva_score_json(rows_json, country, hiv, malaria, hce, freetext, extended=0, &result, &error)
 * (SmartVaJni.cpp on Android, DigitvaSmartvaModule.swift on iOS). Like the app, it calls smartva_version() first and
 * no warm-up: the first score loads the model, so its latency is the app's cold call.
 * Input lines (build_requests.js): id \t country \t hiv \t malaria \t hce \t freetext \t rows_json
 * Output (stdout):
 *   META\tversion\t<smartva_version()>
 *   R\t<id>\t<ms>\t<rc>\t<result JSON, or "ERROR " + the engine's error text, or TOO_LARGE>
 *   META\tend\tpeak_rss_kb\t<n>
 * Bodies have raw tabs and newlines turned into spaces (JSON escapes them anyway), so a record stays on one line.
 * The 1 MiB request and 2 MiB reply limits are the modules' own (MAX_REQUEST_BYTES, MAX_REPLY_BYTES).
 * Build: Android  aarch64-linux-android33-clang -O2 -o harness harness.c -L<dir> -lsmartva_rust   (run with LD_LIBRARY_PATH)
 *        iOS sim  xcrun --sdk iphonesimulator clang -target arm64-apple-ios16.4-simulator -O2 -o harness harness.c
 *                 <xcframework>/ios-arm64-simulator/libsmartva_rust.a
 * usage: harness requests.tsv
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <time.h>

const char *smartva_version(void);
int smartva_score_json(const char *, const char *, int, int, int, int, int, char **, char **);
void smartva_free_string(char *);

#define MAX_REQUEST_BYTES (1024 * 1024)
#define MAX_REPLY_BYTES (2 * 1024 * 1024)

static double now_ms(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1e3 + t.tv_nsec / 1e6; }

static void put_body(const char *s) {
  for (; s && *s; s++) putchar(*s == '\n' || *s == '\t' || *s == '\r' ? ' ' : *s);
}

int main(int argc, char **argv) {
  if (argc != 2) { fprintf(stderr, "usage: harness requests.tsv\n"); return 2; }
  const char *version = smartva_version();
  if (!version || !*version) { fprintf(stderr, "smartva_version returned nothing\n"); return 1; }
  printf("META\tversion\t%s\n", version);
  FILE *in = fopen(argv[1], "r");
  if (!in) { fprintf(stderr, "cannot open %s\n", argv[1]); return 1; }
  size_t cap = 0; char *line = NULL; ssize_t len;
  while ((len = getline(&line, &cap, in)) > 0) {
    if (line[len - 1] == '\n') line[--len] = 0;
    char *field[7]; int n = 0; char *p = line;
    while (n < 6) { field[n++] = p; p = strchr(p, '\t'); if (!p) break; *p++ = 0; }
    if (n != 6 || !p) { fprintf(stderr, "malformed line\n"); return 1; }
    field[6] = p;
    if (strlen(field[6]) > MAX_REQUEST_BYTES) { printf("R\t%s\t0\t-1\tTOO_LARGE\n", field[0]); continue; }
    char *result = NULL, *error = NULL;
    double a = now_ms();
    int rc = smartva_score_json(field[6], field[1], atoi(field[2]), atoi(field[3]), atoi(field[4]), atoi(field[5]), 0,
                                &result, &error);
    double ms = now_ms() - a;
    printf("R\t%s\t%.2f\t%d\t", field[0], ms, rc);
    if (rc == 0 && result && strlen(result) <= MAX_REPLY_BYTES) put_body(result);
    else if (rc == 0 && result) fputs("TOO_LARGE", stdout);
    else { fputs("ERROR ", stdout); put_body(error ? error : "(no error text)"); }
    putchar('\n');
    if (result) smartva_free_string(result);
    if (error) smartva_free_string(error);
  }
  free(line); fclose(in);
  struct rusage use; getrusage(RUSAGE_SELF, &use);
  /* ru_maxrss: kilobytes on Linux/Android, bytes on Darwin. */
#ifdef __APPLE__
  printf("META\tend\tpeak_rss_kb\t%ld\n", (long)use.ru_maxrss / 1024);
#else
  printf("META\tend\tpeak_rss_kb\t%ld\n", (long)use.ru_maxrss);
#endif
  return 0;
}
