// Generates rd_gen.xml: the NativeAOT runtime directives for the generic instantiations that WHO's assemblies reach
// only by reflection (protobuf-net, Newtonsoft.Json, System.Text.Json), which the trimmer would otherwise drop.
//
// usage: dotnet run --file gen_rd.cs -- ICDAPI_DIR ASPNET_SHARED_DIR OUT.xml     (build.sh runs it; .NET 10 file-based app)
// The result goes to OUT.xml, not stdout: a first compile prints its warnings on stdout.
//
// Reads the metadata of the root assemblies below (no code is run) and writes
//   1. every root assembly with Dynamic="Required All";
//   2. every closed generic instantiation named in their signatures (type specs, fields, methods, locals, properties,
//      method specs), under the assembly that defines the generic type;
//   3. what the serializers build from what was found: JsonPropertyInfo<T> for every value type met as a field or property
//      type (and for the primitives), with Nullable<T>, JsonPropertyInfo<Nullable<T>> and NullableConverter<T> beside each;
//      EnumConverter<E> and JsonStringEnumConverter<E> for every enum the roots define; protobuf-net's
//      MapDecorator<Dictionary<K,V>,K,V> for every Dictionary<K,V>; List<T> for every T[] and every IEnumerable<T>,
//      ICollection<T>, IList<T>, IReadOnlyList<T> and IReadOnlyCollection<T> (the deserialisers fill a List<T>).
// An instantiation is left out when the runtime cannot load it (a constraint violation, a by-ref-like argument) or when the
// assembly that defines its generic type is in neither ICDAPI_DIR, the ASP.NET shared framework nor the runtime.
// Types from assemblies that are not roots (Hl7.Fhir, the ASP.NET host) are not scanned: the engine never runs that code.
// GEN_RD_DEBUG=1 lists on stderr what the runtime rejected.
using System.Reflection.Metadata;
using System.Reflection.Metadata.Ecma335;
using System.Reflection.PortableExecutable;
using System.Runtime.InteropServices;
using System.Text;

string[] roots = { "DorisRuleEngine", "OCT", "Expressions", "ICDTextAnalyzers", "ICD-API" };
const string CoreLib = "System.Private.CoreLib";
string icdDir = args[0], aspDir = args[1], runtimeDir = RuntimeEnvironment.GetRuntimeDirectory();

// Types are loaded below only to check that an instantiation is legal (constraints, by-ref-like arguments); WHO's assemblies resolve from here.
System.Runtime.Loader.AssemblyLoadContext.Default.Resolving += (_, name) =>
    new[] { icdDir, aspDir }.Select(d => Path.Combine(d, name.Name + ".dll")).Where(File.Exists).Select(System.Runtime.Loader.AssemblyLoadContext.Default.LoadFromAssemblyPath).FirstOrDefault();

bool Known(string asm) => asm == CoreLib || File.Exists(Path.Combine(icdDir, asm + ".dll")) || File.Exists(Path.Combine(aspDir, asm + ".dll")) || File.Exists(Path.Combine(runtimeDir, asm + ".dll"));

// Facade assemblies (System.Runtime, System.Collections, ...) forward to the implementation assembly. This process runs
// on the same runtime, so ask it where the type lives; types of WHO's own assemblies are not loadable here and keep their name.
var forwarded = new Dictionary<(string, string), string>();
string Home(string asm, string name)
{
    if (forwarded.TryGetValue((asm, name), out var cached)) return cached;
    string home = asm;
    try { var t = Type.GetType(name + ", " + asm); if (t != null) home = t.Assembly.GetName().Name!; } catch { }
    return forwarded[(asm, name)] = home;
}

var all = new Dictionary<string, T>();            // rd.xml name -> instantiation, in first-seen order via 'order'
var order = new List<string>();
var enums = new List<T>();
var propertyTypes = new Dictionary<string, T>();   // value types met as a field or property type
var arrays = new Dictionary<string, T>();

foreach (var root in roots)
{
    using var pe = new PEReader(File.OpenRead(Path.Combine(icdDir, root + ".dll")));
    var md = pe.GetMetadataReader();
    var provider = new Provider(root, Home);
    void Take(T t)
    {
        foreach (var a in t.Arrays()) if (a.Closed) arrays.TryAdd(a.Key, a);
        foreach (var inst in t.Instantiations()) if (inst.Closed && Known(inst.Home) && all.TryAdd(inst.Key, inst)) order.Add(inst.Key);
    }

    foreach (var h in Rows(md, TableIndex.TypeSpec, MetadataTokens.TypeSpecificationHandle))
    {
        var blob = md.GetTypeSpecification(h).Signature;
        try { var br = md.GetBlobReader(blob); Take(new SignatureDecoder<T, object?>(provider, md, null).DecodeType(ref br)); } catch (Exception e) when (e is BadImageFormatException or ArgumentException or InvalidOperationException) { }
    }
    foreach (var h in Rows(md, TableIndex.MethodSpec, MetadataTokens.MethodSpecificationHandle))
    {
        var blob = md.GetMethodSpecification(h).Signature;
        try { var br = md.GetBlobReader(blob); foreach (var t in new SignatureDecoder<T, object?>(provider, md, null).DecodeMethodSpecificationSignature(ref br)) Take(t); } catch (Exception e) when (e is BadImageFormatException or ArgumentException or InvalidOperationException) { }
    }
    foreach (var h in Rows(md, TableIndex.StandAloneSig, MetadataTokens.StandaloneSignatureHandle))
    {
        var s = md.GetStandaloneSignature(h);
        try
        {
            var lr = md.GetBlobReader(s.Signature);
            if (s.GetKind() == StandaloneSignatureKind.LocalVariables) foreach (var t in new SignatureDecoder<T, object?>(provider, md, null).DecodeLocalSignature(ref lr)) Take(t);
            else { var m = s.DecodeMethodSignature(provider, null); Take(m.ReturnType); foreach (var t in m.ParameterTypes) Take(t); }
        }
        catch (Exception e) when (e is BadImageFormatException or ArgumentException or InvalidOperationException) { }
    }
    foreach (var h in md.MemberReferences)
    {
        var m = md.GetMemberReference(h);
        try
        {
            if (m.GetKind() == MemberReferenceKind.Field) Take(m.DecodeFieldSignature(provider, null));
            else { var s = m.DecodeMethodSignature(provider, null); Take(s.ReturnType); foreach (var t in s.ParameterTypes) Take(t); }
        }
        catch (Exception e) when (e is BadImageFormatException or ArgumentException or InvalidOperationException) { }
    }
    foreach (var h in md.FieldDefinitions) try { var ft = md.GetFieldDefinition(h).DecodeSignature(provider, null); Take(ft); if (ft.Closed && ft.Value) propertyTypes.TryAdd(ft.Key, ft); } catch (Exception e) when (e is BadImageFormatException or ArgumentException or InvalidOperationException) { }
    foreach (var h in md.MethodDefinitions)
        try { var s = md.GetMethodDefinition(h).DecodeSignature(provider, null); Take(s.ReturnType); foreach (var t in s.ParameterTypes) Take(t); } catch (Exception e) when (e is BadImageFormatException or ArgumentException or InvalidOperationException) { }
    foreach (var h in md.PropertyDefinitions)
        try { var s = md.GetPropertyDefinition(h).DecodeSignature(provider, null); Take(s.ReturnType); if (s.ReturnType.Closed && s.ReturnType.Value) propertyTypes.TryAdd(s.ReturnType.Key, s.ReturnType); } catch (Exception e) when (e is BadImageFormatException or ArgumentException or InvalidOperationException) { }
    foreach (var h in md.TypeDefinitions)
    {
        var td = md.GetTypeDefinition(h);
        if (td.BaseType.Kind != HandleKind.TypeReference || td.GetGenericParameters().Count > 0) continue; // an enum is never generic
        var b = md.GetTypeReference((TypeReferenceHandle)td.BaseType);
        if (md.GetString(b.Namespace) != "System") continue;
        if (md.GetString(b.Name) == "Enum") enums.Add(provider.GetTypeFromDefinition(md, h, 0x11));
    }
}

// Second pass: what the serializers build from what was found.
T Gen(string asm, string name, params T[] a) => new T(asm, name, a, a.Any(x => !x.Closed), null);
// The primitives a serializer always meets, whether or not a scanned property has them.
foreach (var n in new[] { "Boolean", "Byte", "SByte", "Int16", "UInt16", "Int32", "UInt32", "Int64", "UInt64", "Single", "Double", "Decimal", "Char", "DateTime", "DateTimeOffset", "TimeSpan", "Guid" })
    propertyTypes.TryAdd("System." + n, new T(CoreLib, "System." + n, [], false, null, true));
foreach (var t in propertyTypes.Values.ToList())
{
    Add(Gen("System.Text.Json", "System.Text.Json.Serialization.Metadata.JsonPropertyInfo`1", t));
    if (t.Value && t.Name != "System.Nullable`1")
    {
        var n = Gen(CoreLib, "System.Nullable`1", t);
        Add(n);
        Add(Gen("System.Text.Json", "System.Text.Json.Serialization.Metadata.JsonPropertyInfo`1", n));
    }
}
foreach (var a in arrays.Values.ToList()) Add(Gen(CoreLib, "System.Collections.Generic.List`1", a.Inner!)); // Newtonsoft builds an array through a List<T>
foreach (var t in all.Values.Concat(propertyTypes.Values).ToList())
{
    if (t.Name == "System.Nullable`1") Add(Gen("System.Text.Json", "System.Text.Json.Serialization.Converters.NullableConverter`1", t.Args[0]));
    // Deserialisers build a List<T> for a property typed as one of these interfaces.
    if (t.Args.Length == 1 && t.Name is "System.Collections.Generic.IEnumerable`1" or "System.Collections.Generic.ICollection`1" or "System.Collections.Generic.IList`1" or "System.Collections.Generic.IReadOnlyList`1" or "System.Collections.Generic.IReadOnlyCollection`1")
        Add(Gen(CoreLib, "System.Collections.Generic.List`1", t.Args[0]));
    if (t.Name == "System.Collections.Generic.Dictionary`2") Add(Gen("protobuf-net", "ProtoBuf.Serializers.MapDecorator`3", t, t.Args[0], t.Args[1]));
}
foreach (var e in enums)
{
    Add(Gen("System.Text.Json", "System.Text.Json.Serialization.Converters.EnumConverter`1", e));
    Add(Gen("System.Text.Json", "System.Text.Json.Serialization.JsonStringEnumConverter`1", e));
}
void Add(T t) { if (t.Closed && Known(t.Home) && all.TryAdd(t.Key, t)) order.Add(t.Key); }
// The runtime is the judge of a legal instantiation: Nullable<char[]>, JsonPropertyInfo<Span<char>>, a constraint violation all fail to load.
bool Loads(T t) { try { return Type.GetType(t.Key + ", " + t.Asm) != null; } catch (Exception e) when (e is ArgumentException or TypeLoadException or FileNotFoundException or FileLoadException or BadImageFormatException or NotSupportedException) { return false; } }
order.RemoveAll(k => { bool ok = Loads(all[k]); if (!ok && Environment.GetEnvironmentVariable("GEN_RD_DEBUG") != null) Console.Error.WriteLine("rejected: " + all[k].Asm + " " + k); return !ok; });

string X(string s) => s.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;").Replace("\"", "&quot;");
var o = new StringBuilder();
o.Append("<Directives xmlns=\"http://schemas.microsoft.com/netfx/2013/01/metadata\"><Application>\n");
foreach (var root in roots) o.Append($"<Assembly Name=\"{root}\" Dynamic=\"Required All\" />\n");
foreach (var group in order.Select(k => all[k]).GroupBy(t => t.Home))
{
    o.Append($"<Assembly Name=\"{X(group.Key)}\">\n");
    foreach (var t in group) o.Append($"  <Type Name=\"{X(t.Key)}\" Dynamic=\"Required All\" />\n");
    o.Append("</Assembly>\n");
}
o.Append("</Application></Directives>\n");
File.WriteAllText(args[2], o.ToString());

static IEnumerable<H> Rows<H>(MetadataReader md, TableIndex table, Func<int, H> make) { for (int i = 1; i <= md.GetTableRowCount(table); i++) yield return make(i); }

// A type as rd.xml spells it: Name is the metadata name (generic arity and '+' for nesting), Args the instantiation.
// Asm is the assembly that defines it (facades resolved); a type parameter or pointer makes it not Closed.
sealed record T(string Asm, string Name, T[] Args, bool Open, string? Elem, bool Value = false, T? Inner = null)
{
    public bool Closed => !Open;
    public string Home => Asm;
    public string Key => Elem != null ? Elem + "[]" : Args.Length == 0 ? Name : Name + "[" + string.Join(",", Args.Select(a => "[" + a.Key + "," + a.Asm + "]")) + "]";
    public IEnumerable<T> Arrays()
    {
        if (Inner != null) { yield return this; foreach (var i in Inner.Arrays()) yield return i; }
        foreach (var a in Args) foreach (var i in a.Arrays()) yield return i;
    }
    public IEnumerable<T> Instantiations()
    {
        if (Inner != null) foreach (var i in Inner.Instantiations()) yield return i;
        foreach (var a in Args) foreach (var i in a.Instantiations()) yield return i;
        if (Args.Length > 0 && Elem == null) yield return this;
    }
}

sealed class Provider(string self, Func<string, string, string> home) : ISignatureTypeProvider<T, object?>
{
    static readonly T Open = new("?", "?", [], true, null);
    T Prim(string n) => new(CoreLibName, "System." + n, [], false, null, n is not ("Object" or "String"));
    const string CoreLibName = "System.Private.CoreLib";
    public T GetPrimitiveType(PrimitiveTypeCode c) => c switch
    {
        PrimitiveTypeCode.Boolean => Prim("Boolean"), PrimitiveTypeCode.Byte => Prim("Byte"), PrimitiveTypeCode.Char => Prim("Char"),
        PrimitiveTypeCode.Double => Prim("Double"), PrimitiveTypeCode.Int16 => Prim("Int16"), PrimitiveTypeCode.Int32 => Prim("Int32"),
        PrimitiveTypeCode.Int64 => Prim("Int64"), PrimitiveTypeCode.IntPtr => Prim("IntPtr"), PrimitiveTypeCode.Object => Prim("Object"),
        PrimitiveTypeCode.SByte => Prim("SByte"), PrimitiveTypeCode.Single => Prim("Single"), PrimitiveTypeCode.String => Prim("String"),
        PrimitiveTypeCode.TypedReference => Prim("TypedReference"), PrimitiveTypeCode.UInt16 => Prim("UInt16"), PrimitiveTypeCode.UInt32 => Prim("UInt32"),
        PrimitiveTypeCode.UInt64 => Prim("UInt64"), PrimitiveTypeCode.UIntPtr => Prim("UIntPtr"), PrimitiveTypeCode.Void => Prim("Void"),
        _ => Open,
    };
    public T GetTypeFromDefinition(MetadataReader reader, TypeDefinitionHandle h, byte raw)
    {
        var td = reader.GetTypeDefinition(h);
        string name = reader.GetString(td.Name);
        var parent = td.GetDeclaringType();
        string full = parent.IsNil ? Join(reader.GetString(td.Namespace), name) : GetTypeFromDefinition(reader, parent, 0).Name + "+" + name;
        return new T(self, full, [], false, null, raw == 0x11);
    }
    public T GetTypeFromReference(MetadataReader reader, TypeReferenceHandle h, byte raw)
    {
        var tr = reader.GetTypeReference(h);
        string name = reader.GetString(tr.Name);
        if (tr.ResolutionScope.Kind == HandleKind.TypeReference)
        {
            var p = GetTypeFromReference(reader, (TypeReferenceHandle)tr.ResolutionScope, 0);
            return new T(p.Asm, p.Name + "+" + name, [], false, null, raw == 0x11);
        }
        string full = Join(reader.GetString(tr.Namespace), name);
        string asm = tr.ResolutionScope.Kind == HandleKind.AssemblyReference ? reader.GetString(reader.GetAssemblyReference((AssemblyReferenceHandle)tr.ResolutionScope).Name) : self;
        return new T(home(asm, full), full, [], false, null, raw == 0x11);
    }
    public T GetTypeFromSpecification(MetadataReader reader, object? ctx, TypeSpecificationHandle h, byte raw) =>
        Decode(reader, ctx, reader.GetTypeSpecification(h).Signature);
    T Decode(MetadataReader reader, object? ctx, BlobHandle blob) { var br = reader.GetBlobReader(blob); return new SignatureDecoder<T, object?>(this, reader, ctx).DecodeType(ref br); }
    public T GetGenericInstantiation(T generic, System.Collections.Immutable.ImmutableArray<T> args) => generic with { Args = args.ToArray(), Open = generic.Open || args.Any(a => a.Open) };
    public T GetSZArrayType(T e) => e with { Elem = e.Key, Args = [], Open = e.Open, Value = false, Inner = e };
    public T GetArrayType(T e, ArrayShape s) => Open;
    public T GetByReferenceType(T e) => Open;
    public T GetPointerType(T e) => Open;
    public T GetFunctionPointerType(MethodSignature<T> s) => Open;
    public T GetGenericMethodParameter(object? ctx, int i) => Open;
    public T GetGenericTypeParameter(object? ctx, int i) => Open;
    public T GetModifiedType(T m, T u, bool required) => u;
    public T GetPinnedType(T e) => e;
    static string Join(string ns, string n) => ns.Length == 0 ? n : ns + "." + n;
}
