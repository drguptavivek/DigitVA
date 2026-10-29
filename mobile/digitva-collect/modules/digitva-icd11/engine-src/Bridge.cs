using System.Diagnostics; using System.Runtime.CompilerServices; using System.Runtime.InteropServices; using System.Text.Json;
using ICDAPI; using ICDAPI.Controllers; using ICDAPI.Searching; using DorisRuleEngine;
using Microsoft.AspNetCore.Http; using Microsoft.AspNetCore.Mvc; using Microsoft.AspNetCore.Mvc.Formatters; using Microsoft.Extensions.Configuration;

// Headless C ABI: no Kestrel, no loopback HTTP. Calls ICD-API's LinearizationController in-process.
public static unsafe class Icd11Bridge {
  static LinearizationController _ctl; static IOutputFormatter[] _fmts; static readonly object Gate = new();
  static byte* U8(string s) => s == null ? null : (byte*)Marshal.StringToCoTaskMemUTF8(s);
  static string S(byte* p) => p == null ? null : Marshal.PtrToStringUTF8((IntPtr)p);

  [UnmanagedCallersOnly(EntryPoint = "digitva_icd11_free")] public static void Free(byte* p) { if (p != null) Marshal.FreeCoTaskMem((IntPtr)p); }

  [UnmanagedCallersOnly(EntryPoint = "digitva_icd11_init")]
  public static byte* Init(byte* bundleDir, byte* dataDir) {
    lock (Gate) try {
      if (_ctl != null) return null;
      var sw = Stopwatch.StartNew();
      string bundle = S(bundleDir), data = S(dataDir);
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
      var ctl = new LinearizationController(conf, new ICDServiceSerializer(conf, ver), ix, ver, cfg, doris, null);
      var http = new DefaultHttpContext(); http.Request.Headers["Accept"]="application/json"; http.Request.Headers["Accept-Language"]="en"; http.Request.Headers["API-Version"]="v2";
      ctl.ControllerContext = new ControllerContext { HttpContext = http };
      _fmts = new IOutputFormatter[] { new ICDAPI.Formatters.JSONLDFormatter(bundle + "/wwwroot"), new ICDAPI.Formatters.EnhancedPCCSFormatter() };
      _ctl = ctl; T("ready");
      try { File.WriteAllText(Path.Combine(Path.GetDirectoryName(data.TrimEnd('/')), "init-timings.txt"), log.ToString()); } catch { }
      return null;
    } catch (Exception ex) { return U8(ex.ToString()); }
  }

  static string Render(IActionResult r, out int status) {
    if (r is ContentResult cr) { status = cr.StatusCode ?? 200; return cr.Content ?? ""; }
    var o = r as ObjectResult; status = o?.StatusCode ?? (r as StatusCodeResult)?.StatusCode ?? 200; var v = o?.Value;
    if (v == null) return "null"; if (v is string s) return JsonSerializer.Serialize(s);
    var h = new DefaultHttpContext(); h.Request.Headers["Accept"]="application/json"; var ms = new MemoryStream(); h.Response.Body = ms;
    var wc = new OutputFormatterWriteContext(h, (st, en) => new StreamWriter(st, en), v.GetType(), v);
    var f = _fmts.FirstOrDefault(x => x.CanWriteResult(wc));
    if (f != null) { f.WriteAsync(wc).GetAwaiter().GetResult(); return System.Text.Encoding.UTF8.GetString(ms.ToArray()); }
    return Newtonsoft.Json.JsonConvert.SerializeObject(v);
  }
  static byte* Run(Func<IActionResult> f, int* st) {
    try { if (_ctl == null) { if (st != null) *st = 503; return U8("{\"error\":\"not initialized\"}"); }
      string body; int s; lock (Gate) body = Render(f(), out s); if (st != null) *st = s; return U8(body); }
    catch (Exception ex) { if (st != null) *st = 500; return U8(JsonSerializer.Serialize(new Dictionary<string,string>{["error"]=ex.Message})); }
  }
  [UnmanagedCallersOnly(EntryPoint = "digitva_icd11_codeinfo")] public static byte* CodeInfo(byte* code, int* st) { var c = S(code); return Run(() => _ctl.GetCodeInfo("mms", "2026-01", c), st); }
  [UnmanagedCallersOnly(EntryPoint = "digitva_icd11_search")] public static byte* Search(byte* q, int* st) { var s = S(q); return Run(() => _ctl.SearchLinearization("mms", "2026-01", s), st); }
  [UnmanagedCallersOnly(EntryPoint = "digitva_icd11_doris")] public static byte* Doris(byte* cert, int* st) { var j = S(cert); return Run(() => { using var d = JsonDocument.Parse(j); return _ctl.UnderlyingCauseOfDeathDetection("2026-01", d); }, st); }
  [UnmanagedCallersOnly(EntryPoint = "digitva_icd11_codedit")] public static byte* CodEdit(byte* cert, int* st) { var j = S(cert); return Run(() => { using var d = JsonDocument.Parse(j); return _ctl.CertificateCheck("2026-01", d); }, st); }
}
