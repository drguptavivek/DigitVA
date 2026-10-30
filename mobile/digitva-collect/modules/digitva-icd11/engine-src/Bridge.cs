using System.Diagnostics; using System.Runtime.CompilerServices; using System.Runtime.InteropServices; using System.Text.Json;
using System.Text.Json.Nodes; using System.Text.Encodings.Web;
using ICDAPI; using ICDAPI.Controllers; using ICDAPI.Searching; using DorisRuleEngine;
using Microsoft.AspNetCore.Http; using Microsoft.AspNetCore.Mvc; using Microsoft.AspNetCore.Mvc.Formatters; using Microsoft.Extensions.Configuration; using System.Text.Json.Serialization.Metadata;

// Headless C ABI: no Kestrel, no loopback HTTP. Calls ICD-API's controllers in-process and returns what WHO's REST layer
// would write for the same action. Exports: init, free and digitva_icd11_call(op, json, &status), the one call. The ops it
// accepts are the switch in Dispatch and nowhere else. The app's shim requires digitva_icd11_call at load, so a library without it
// is refused loudly. Replies are bounded: `search` takes an optional `limit` (1..200, only with flatResults=true) that trims
// destinationEntities, and `include=descendant` is refused (it returns whole subtrees).
public static unsafe class Icd11Bridge {
  const string Lin = "mms", Rel = "2026-01";
  static LinearizationController _ctl; static FoundationController _fnd; static IOutputFormatter[] _fmts; static readonly object Gate = new();
  static byte* U8(string s) => s == null ? null : (byte*)Marshal.StringToCoTaskMemUTF8(s);
  static string S(byte* p) => p == null ? null : Marshal.PtrToStringUTF8((IntPtr)p);

  [UnmanagedCallersOnly(EntryPoint = "digitva_icd11_free")] public static void Free(byte* p) { if (p != null) Marshal.FreeCoTaskMem((IntPtr)p); }

  [UnmanagedCallersOnly(EntryPoint = "digitva_icd11_init")]
  public static byte* Init(byte* bundleDir, byte* dataDir) { var err = InitCore(S(bundleDir), S(dataDir)); return err == null ? null : U8(err); }

  // Managed body of Init, so a managed caller (a test host) can run it: an UnmanagedCallersOnly method cannot be called from managed code. Returns an error text or null.
  internal static string InitCore(string bundle, string data) {
    lock (Gate) try {
      if (_ctl != null) return null;
      var sw = Stopwatch.StartNew();
      ProtoBuf.Meta.RuntimeTypeModel.Default.AutoCompile = false;
      Environment.SetEnvironmentVariable("TMPDIR", data.TrimEnd('/') + "/");
      var cfg = new ConfigurationBuilder().SetBasePath(bundle).AddJsonFile("appsettings.json").AddJsonFile("appsettings.container.json")
        .AddInMemoryCollection(new Dictionary<string,string>{ ["acceptLicense"]="true",["enableDoris"]="true",["include"]="2026-01_en",
          ["saveAnalytics"]="false",["applicationCacheFolder"]=data,["icd11Conf:EnableCodingTool"]="false"}).Build();
      var conf = new ServiceConfig(bundle, "container", cfg);
      // Phase end times (ms since init start) go to <root>/init-timings.txt, which Kotlin logs. DORIS rules and the
      // search index are independent, so they load on two threads (~4 s faster on a phone) unless
      // DIGITVA_ICD11_SERIAL=1 (A/B switch for measuring; output is identical either way).
      var log = new System.Text.StringBuilder();
      void T(string m) { lock (log) log.Append(m).Append('=').Append(sw.ElapsedMilliseconds).Append(' '); }
      T("config");
      var doris = new Dictionary<string, DorisEngine>(); Exception dorisError = null;
      void LoadDoris() { try { foreach (var k in conf.HistoricalFoundations.Keys) { var e = new DorisEngine(Classification.ICD11, conf.HistoricalFoundations[k], null, null, conf.TheLanguageResource); e.Load(cfg.GetValue<string>("dorisVersion_default")).Wait(); doris[k] = e; } T("doris"); } catch (Exception ex) { dorisError = ex; } }
      var ix = new NewIndexAccessor(conf);
      if (Environment.GetEnvironmentVariable("DIGITVA_ICD11_SERIAL") == "1") { LoadDoris(); ix.Initialize(); T("index"); }
      else { var dt = new Thread(LoadDoris, 64 << 20); dt.Start(); ix.Initialize(); T("index"); dt.Join(); }
      if (dorisError != null) throw dorisError;
      var ver = new APIVersion { TheVersionString = "v2" };
      var ser = new ICDServiceSerializer(conf, ver);
      var ctl = new LinearizationController(conf, ser, ix, ver, cfg, doris, null);
      var fnd = new FoundationController(conf, ser, ver, ix, cfg, null); // argument order differs from LinearizationController
      var http = new DefaultHttpContext(); http.Request.Headers["Accept"]="application/json"; http.Request.Headers["Accept-Language"]="en"; http.Request.Headers["API-Version"]="v2";
      ctl.ControllerContext = new ControllerContext { HttpContext = http }; fnd.ControllerContext = new ControllerContext { HttpContext = http };
      // The formatters WHO registers for its REST API, in its order (Startup.ConfigureServices): JSON-LD, the postcoordination formatter, then
      // System.Text.Json with camelCase names. That last one writes DORIS and CoDEdit, which is why their fields are camelCase over REST.
      _fmts = new IOutputFormatter[] { new ICDAPI.Formatters.JSONLDFormatter(bundle + "/wwwroot"), new ICDAPI.Formatters.EnhancedPCCSFormatter(),
        new SystemTextJsonOutputFormatter(new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase, TypeInfoResolver = new DefaultJsonTypeInfoResolver() }) };
      _ctl = ctl; _fnd = fnd; T("ready");
      try { File.WriteAllText(Path.Combine(Path.GetDirectoryName(data.TrimEnd('/')), "init-timings.txt"), log.ToString()); } catch { }
      return null;
    } catch (Exception ex) { return ex.ToString(); }
  }

  static string Render(IActionResult r, out int status) {
    if (r is ContentResult cr) { status = cr.StatusCode ?? 200; return cr.Content ?? ""; }
    var o = r as ObjectResult; status = o?.StatusCode ?? (r as StatusCodeResult)?.StatusCode ?? 200; var v = o?.Value;
    if (v == null) return "null"; if (v is string s) return JsonSerializer.Serialize(s);
    var h = new DefaultHttpContext(); h.Request.Headers["Accept"]="application/json"; var ms = new MemoryStream(); h.Response.Body = ms;
    var wc = new OutputFormatterWriteContext(h, (st, en) => new StreamWriter(st, en), v.GetType(), v);
    var f = _fmts.First(x => x.CanWriteResult(wc));
    f.WriteAsync(wc).GetAwaiter().GetResult(); return System.Text.Encoding.UTF8.GetString(ms.ToArray());
  }
  static string Err(string m) => JsonSerializer.Serialize(new Dictionary<string,string>{["error"]=m});

  // The one call. `json` is an object of named arguments; absent arguments take WHO's defaults. 400 for an unknown op, JSON that is not
  // an object, or a missing or mistyped argument (the reply names the argument, never the input); 503 before init; 500 when WHO throws.
  [UnmanagedCallersOnly(EntryPoint = "digitva_icd11_call")]
  public static byte* CallOp(byte* op, byte* json, int* st) { var r = Dispatch(S(op), S(json), out int s); if (st != null) *st = s; return U8(r); }

  // Managed body of CallOp, for managed callers.
  internal static string Dispatch(string op, string json, out int status) {
    try {
      if (_ctl == null) { status = 503; return "{\"error\":\"not initialized\"}"; }
      if (op is not ("search" or "codeinfo" or "entity" or "foundation_entity" or "doris" or "codedit")) { status = 400; return "{\"error\":\"unknown op\"}"; }
      JsonDocument doc;
      try { doc = JsonDocument.Parse(json ?? ""); } catch (JsonException) { status = 400; return "{\"error\":\"bad json\"}"; }
      using var _ = doc;
      var a = new Args(doc.RootElement);
      // `descendant` would return a whole subtree; no caller needs it and the reply has no bound. Refused before WHO runs.
      if (op is ("entity" or "foundation_entity") && a.Str("include") is { } inc && inc.Contains("descendant", StringComparison.OrdinalIgnoreCase)) { status = 400; return "{\"error\":\"include descendant is not allowed\"}"; }
      var limit = op == "search" ? a.Int("limit", 1, 200) : null;
      // WHO nests descendants under each result when flatResults is false, and Chop trims only the top level: the reply would not be bounded.
      if (limit != null && !a.Bool("flatResults", true)) { status = 400; return "{\"error\":\"limit requires flatResults\"}"; }
      Func<IActionResult> call = op switch {
        // WHO's defaults (LinearizationController.SearchLinearization) are the fallbacks below.
        "search" => (Func<IActionResult>)(() => _ctl.SearchLinearization(Lin, Rel, a.Str("q"), a.Str("subtreesFilter"), a.Bool("subtreeFilterUsesFoundationDescendants", false),
          a.Bool("includeKeywordResult", false), a.Str("chapterFilter"), a.Bool("includePostcoordination", true), a.Bool("useFlexisearch", false), a.Bool("flatResults", true),
          a.Bool("highlightingEnabled", true), a.Bool("medicalCodingMode", true), a.Str("propertiesToBeSearched"))),
        "codeinfo" => () => _ctl.GetCodeInfo(Lin, Rel, a.Req("code"), a.Bool("flexiblemode", false), a.Bool("convertToTerminalCodes", false)),
        "entity" => () => a.Str("residual") is { } residual ? _ctl.GetLinearizationResidualEntity(Lin, Rel, a.Req("id"), residual, a.Str("include")) : _ctl.GetLinearizationEntity(Lin, Rel, a.Req("id"), a.Str("include")),
        "foundation_entity" => () => _fnd.GetFoundationEntity(a.Req("id"), null, a.Str("include")),
        "doris" => () => { using var d = a.Doc("certificate"); return _ctl.UnderlyingCauseOfDeathDetection(Rel, d); },
        _ => () => { using var d = a.Doc("certificate"); return _ctl.CertificateCheck(Rel, d); },
      };
      string body; lock (Gate) body = Render(call(), out status);
      return limit is { } n && status is >= 200 and < 300 ? Chop(body, n) : body;
    }
    catch (ArgumentException ex) when (ex.Data.Contains("arg")) { status = 400; return Err("bad argument: " + ex.Data["arg"]); }
    catch (Exception ex) { status = 500; return Err(ex.Message); }
  }

  // Keeps the first `n` destinationEntities of a search reply and sets resultChopped when it cut any; a reply without the list, or already
  // within `n`, is returned as it came (so WHO's own resultChopped is never cleared).
  static string Chop(string body, int n) {
    if (JsonNode.Parse(body) is not JsonObject o || o["destinationEntities"] is not JsonArray list || list.Count <= n) return body;
    while (list.Count > n) list.RemoveAt(list.Count - 1);
    o["resultChopped"] = true;
    return o.ToJsonString(new JsonSerializerOptions { Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping });
  }

  // Named arguments of one call. A wrong type or a missing required argument is an ArgumentException that carries the argument's name.
  readonly struct Args(JsonElement root) {
    JsonElement? Get(string n) {
      if (root.ValueKind != JsonValueKind.Object) throw Bad("(arguments)");
      return root.TryGetProperty(n, out var v) && v.ValueKind != JsonValueKind.Null ? v : null;
    }
    static ArgumentException Bad(string n) { var e = new ArgumentException("bad argument"); e.Data["arg"] = n; return e; }
    // An empty string reads as absent, as ASP.NET's binder does for a query or form value; WHO answers a missing `q` itself, with 400.
    public string Str(string n) => Get(n) is { } v ? (v.ValueKind == JsonValueKind.String ? (v.GetString() is { Length: > 0 } s ? s : null) : throw Bad(n)) : null;
    public string Req(string n) => Str(n) ?? throw Bad(n);
    // An integer in [min, max]; absent is null. A string, a fraction or a number out of range is a bad argument.
    public int? Int(string n, int min, int max) => Get(n) is { } v ? (v.ValueKind == JsonValueKind.Number && v.TryGetInt32(out var i) && i >= min && i <= max ? i : throw Bad(n)) : null;
    public bool Bool(string n, bool def) => Get(n) is { } v ? (v.ValueKind is JsonValueKind.True or JsonValueKind.False ? v.GetBoolean() : throw Bad(n)) : def;
    // Any JSON value, null included, counts as a certificate: the DORIS and CoDEdit actions judge it, as they do for a REST body.
    public JsonDocument Doc(string n) => root.ValueKind == JsonValueKind.Object && root.TryGetProperty(n, out var v) ? JsonDocument.Parse(v.GetRawText()) : throw Bad(n);
  }
}
