import sys
LIGHT=dict(canvas="#e8edf0",card="#ffffff",text="#1b232a",muted="#5c6872",sep="#e3e8eb",pri="#1f4d60",onpri="#ffffff",link="#1f4d60",tint="#d2e5ec",acc="#d6a24a",onacc="#1b232a",acctint="#fbe7c6",err="#b3261e",errtint="#fbe9e7",ok="#1f7a4d",oktint="#dcefe2",bar="rgba(232,237,240,.92)",shadow="0 1px 2px rgba(16,40,52,.10)",ctl="#c9d1d6",knob="#ffffff",logo="#ffffff")
DARK=dict(canvas="#0f1418",card="#1a2127",text="#e8edf0",muted="#9aa6af",sep="#2a333a",pri="#6fb6d6",onpri="#0f1418",link="#6fb6d6",tint="#1f3a47",acc="#d6a24a",onacc="#1b232a",acctint="#3a2f1c",err="#f08a80",errtint="#3a1f1d",ok="#6cc796",oktint="#1b3326",bar="rgba(15,20,24,.92)",shadow="none",ctl="#3a444c",knob="#e8edf0",logo="#ffffff")
MONO="ui-monospace,'SF Mono',Menlo,monospace"
def nav(T,title,right="",back=True):
    b=f'<span style="color:{T["link"]};font-size:30px;line-height:20px;margin:-4px 4px 0 0">‹</span>' if back else ""
    return f'<div class="nb" style="background:{T["bar"]}">{b}<span style="flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{title}</span>{right}</div>'
def grp(T,rows,mt=0):
    out=[]
    for i,r in enumerate(rows):
        sep="" if i==len(rows)-1 else f'<i style="position:absolute;left:16px;right:0;bottom:0;height:0.5px;background:{T["sep"]}"></i>'
        out.append(r.replace("<!--sep-->",sep))
    return f'<div class="grp" style="background:{T["card"]};box-shadow:{T["shadow"]};margin-top:{mt}px">'+"".join(out)+'</div>'
def row(T,inner,extra="",h=48):
    return f'<div class="row" style="min-height:{h}px;{extra}">{inner}<!--sep--></div>'
hd=lambda T,t: f'<div class="hd" style="color:{T["muted"]}">{t}</div>'
btn=lambda T,t,kind="pri": f'<div class="btn" style="{"background:"+T["pri"]+";color:"+T["onpri"] if kind=="pri" else "background:"+T["tint"]+";color:"+T["link"]}">{t}</div>'
chip=lambda T,c: f'<span style="font:600 13px {MONO};background:{T["tint"]};color:{T["link"]};padding:3px 7px;border-radius:6px">{c}</span>'
chev=lambda T: f'<span style="color:{T["muted"]};font-size:20px;margin-left:8px">›</span>'
def radio(T,sel): return f'<span style="flex:none;width:22px;height:22px;border-radius:50%;{"background:"+T["pri"] if sel else "box-shadow:inset 0 0 0 2px "+T["ctl"]};display:flex;align-items:center;justify-content:center;margin-right:12px">{f"<i style=width:8px;height:8px;border-radius:50%;background:{T[chr(111)+chr(110)+chr(112)+chr(114)+chr(105)]};display:block></i>" if sel else ""}</span>'
def check(T,sel): return f'<span style="flex:none;width:22px;height:22px;border-radius:6px;{"background:"+T["pri"] if sel else "box-shadow:inset 0 0 0 2px "+T["ctl"]};display:flex;align-items:center;justify-content:center;margin-right:12px;color:{T["onpri"]};font:700 14px system-ui">{"✓" if sel else ""}</span>'
def opt(T,label,sel,mark=radio,sub=""):
    s=f'<br><span style="font-size:13px;color:{T["muted"]};font-weight:400">{sub}</span>' if sub else ""
    return row(T,f'{mark(T,sel)}<span style="flex:1;{"font-weight:600" if sel else ""}">{label}{s}</span>',("background:"+T["tint"]) if sel else "",56 if sub else 48)
def foot(T,inner): return f'<div class="ft" style="background:{T["bar"]}">{inner}</div>'
def pair(T,a,b): return f'<div style="display:flex;gap:10px">{btn(T,a,"sec").replace("class=\"btn\"","class=\"btn\" style2")}{btn(T,b)}</div>'.replace(' style2','')
# ---------- screens
def home(T):
    badge=f'<span class="num" style="background:{T["acc"]};color:{T["onacc"]}">2</span>'
    plain=f'<span class="num" style="color:{T["text"]}">5</span>'
    logo=f'<img src="icon.png" style="width:28px;height:28px;border-radius:7px;background:{T["logo"]}">'
    av=f'<span style="width:32px;height:32px;border-radius:50%;background:{T["tint"]};color:{T["link"]};font:600 13px system-ui;display:flex;align-items:center;justify-content:center">TM</span>'
    return f'''<div class="nb" style="background:{T["bar"]}">{logo}<span style="margin-left:8px;flex:1">DigitVA</span>{av}</div>
<div style="padding:14px 30px 0"><div style="font:700 28px system-ui">Today</div><div style="color:{T["muted"]};font-size:14px">GUJ026 · PHC Bavla</div></div>
{grp(T,[row(T,f'<span style="flex:1">Unsent interviews</span>{badge}',"background:"+T["acctint"]),row(T,f'<span style="flex:1">Cases to visit</span>{plain}'),row(T,f'<span style="flex:1">Drafts</span><span class="num" style="color:{T["text"]}">1</span>')],12)}
<div style="margin:12px 14px 0">{btn(T,"Send now")}</div>
{hd(T,"Recent")}{grp(T,[row(T,f'<span style="flex:1">Kamla Devi, 62 F<br><span style="color:{T["muted"]};font-size:13px">Visit due today</span></span>{chev(T)}',h=56),row(T,f'<span style="flex:1">Ramesh Patel, 48 M<br><span style="color:{T["muted"]};font-size:13px">Unsent · saved 10:20</span></span>{chev(T)}',h=56)])}'''
def register(T):
    seg=f'<div style="display:flex;background:{T["canvas"]};border-radius:9px;padding:2px;flex:1">'+"".join(f'<div style="flex:1;text-align:center;padding:7px 0;border-radius:7px;font-size:15px;{"background:"+T["card"]+";font-weight:600;box-shadow:0 1px 3px rgba(0,0,0,.18)" if x=="Female" else ""}">{x}</div>' for x in ["Male","Female","Other"])+'</div>'
    f=lambda l,v,ph=False,c=False: row(T,f'<span style="width:92px;color:{T["muted"]};font-size:15px">{l}</span><span style="flex:1;{"color:"+T["muted"] if ph else ""}">{v}</span>{chev(T) if c else ""}')
    return f'''{nav(T,"Report a death")}<div class="sc">
{hd(T,"Deceased")}{grp(T,[f("Name","Kamla Devi"),f("Age","62 years"),row(T,f'<span style="width:92px;color:{T["muted"]};font-size:15px">Sex</span>{seg}'),f("Died on","3 Nov 2026",c=True)])}
{hd(T,"Place")}{grp(T,[f("Site / unit","PHC Bavla",c=True),f("Village","Village or ward",ph=True)])}
{hd(T,"Informant")}{grp(T,[f("Phone","98xxxxxx12"),f("Relation","Son",c=True)])}</div>
{foot(T,btn(T,"Save and schedule visit"))}'''
def form(T):
    return f'''{nav(T,"Signs and symptoms",f'<span style="color:{T["muted"]};font-size:14px;margin-left:6px;white-space:nowrap">6 of 12</span>')}
<div style="height:4px;background:{T["sep"]}"><div style="width:48%;height:4px;background:{T["pri"]}"></div></div><div class="sc">
<div class="q">Did (s)he have a fever?</div><div class="qh">क्या उसे बुखार था?</div>
{grp(T,[opt(T,"Yes",True),opt(T,"No",False),opt(T,"Doesn't know",False),opt(T,"Refused to answer",False)])}
<div class="q">How many days did the fever last?</div><div class="qh">बुखार कितने दिन रहा?</div>
{grp(T,[row(T,f'<span style="color:{T["muted"]}">Days</span><span style="margin-left:auto;font-size:13px;color:{T["muted"]}">123</span>',"background:"+T["errtint"])])}
<div style="margin:6px 30px 0;font-size:14px;color:{T["err"]};font-weight:500">Enter the number of days.</div>
<div class="q">Did (s)he have a cough? <span style="font:400 13px system-ui;color:{T["muted"]}">Required</span></div><div class="qh">क्या उसे खांसी थी?</div></div>
{foot(T,pair(T,"Previous","Next"))}'''
def nqa(T):
    q=lambda t,opts,sel: f'<div class="q" style="font-size:16px;margin-top:14px">{t}</div>'+grp(T,[opt(T,o,i==sel) for i,o in enumerate(opts)])
    score=f'<span style="font:700 15px system-ui;color:{T["onacc"]};background:{T["acc"]};padding:4px 10px;border-radius:12px;white-space:nowrap">7 / 10</span>'
    return f'''{nav(T,"Narrative QA",score)}<div class="sc">
{q("1. Length of narrative",["Fewer than 3 sentences","3 to 5 sentences","More than 5 sentences"],2)}
{q("2. Positive symptoms",["Fewer than 3","3 to 5","More than 5"],1)}
{q("3. Negative symptoms",["Absent","Present"],1)}
{q("4. Chronology",["Cannot be established","Can be established"],1)}</div>
{foot(T,btn(T,"Save assessment"))}'''
def social(T):
    g=lambda t,o: hd(T,t)+grp(T,[opt(T,a,s,check,d) for a,d,s in o])
    return f'''{nav(T,"Social Autopsy")}<div class="sc">
{g("Delay 1 · Deciding to seek care",[("Recognition","Illness or danger signs not recognised",True),("Traditions","Home remedies or beliefs delayed care",False),("Financial barrier","Could not arrange money",True)])}
{g("Delay 2 · Reaching a facility",[("Transport and logistics","No vehicle, long distance",True),("Emergencies","Condition progressed too fast",False)])}
{g("Delay 3 · Receiving care",[("Lack of services","First facility could not treat",False)])}</div>
{foot(T,btn(T,"Save analysis"))}'''
def cod(T):
    ln=lambda k,t,c,iv: row(T,f'<span style="color:{T["muted"]};width:20px;align-self:flex-start">{k}</span><span style="flex:1">{t}<div style="margin-top:4px">{chip(T,c)}</div></span><span style="color:{T["muted"]};font-size:14px;white-space:nowrap">{iv}</span>{chev(T)}',h=64)
    add=lambda k: row(T,f'<span style="color:{T["muted"]};width:20px">{k}</span><span style="flex:1;color:{T["link"]};font-weight:500">Add a cause</span>')
    return f'''{nav(T,"PHC01-000020")}<div class="sc">
{hd(T,"Narrative")}{grp(T,[row(T,'<span style="font-size:15px;line-height:21px;padding:2px 0">Chest pain for 2 hours, sweating, collapsed at home. Known diabetic for 10 years.</span>')])}
{hd(T,"SmartVA reference")}{grp(T,[row(T,f'<span style="flex:1">Acute myocardial infarction</span><span style="color:{T["muted"]};font-size:14px;white-space:nowrap">ICD-10 I21</span>')])}
{hd(T,"Part 1 · Chain of events")}{grp(T,[ln("a","Acute myocardial infarction","BA41.Z","2 hours"),ln("b","Type 2 diabetes mellitus","5A11","10 years"),add("c")])}
{hd(T,"Part 2 · Other conditions")}{grp(T,[add("")])}</div>
{foot(T,btn(T,"Run DORIS"))}'''
def doris(T):
    res=lambda c,t: row(T,f'<span style="font:600 14px {MONO};color:{T["link"]};width:64px;flex:none">{c}</span><span style="font-size:15px">{t}</span>')
    return f'''{nav(T,"DORIS result")}<div class="sc">
<div class="grp" style="background:{T["card"]};box-shadow:{T["shadow"]};margin-top:14px;padding:16px">
<div style="font-size:12px;letter-spacing:.3px;text-transform:uppercase;color:{T["muted"]}">Underlying cause of death</div>
<div style="font:700 21px system-ui;margin-top:6px">Acute myocardial infarction</div>
<div style="margin-top:10px;display:flex;gap:8px;align-items:center"><span style="font:700 15px {MONO};background:{T["pri"]};color:{T["onpri"]};padding:4px 9px;border-radius:7px">BA41.Z</span><span style="font-size:14px;color:{T["muted"]}">from line a</span></div>
<div style="margin-top:10px;font-size:14px;color:{T["muted"]}">Rule: General Principle · direct sequence</div></div>
{hd(T,"Search ICD-11")}{grp(T,[row(T,f'<span style="color:{T["muted"]}">⌕&nbsp; <span style="color:{T["text"]}">myocardial</span></span>',"background:"+T["canvas"]+";margin:8px;border-radius:10px;min-height:36px;padding:0 10px"),res("BA41.Z","Acute <b>myocardial</b> infarction, unspecified"),res("BA41.0","Acute ST elevation <b>myocardial</b> infarction"),res("BA42","Subsequent <b>myocardial</b> infarction")])}</div>
{foot(T,pair(T,"Edit chain","Accept"))}'''
def widgets(T):
    tog=lambda on: f'<span style="margin-left:auto;width:51px;height:31px;border-radius:16px;background:{T["pri"] if on else T["ctl"]};position:relative;flex:none"><i style="position:absolute;top:2px;{"right" if on else "left"}:2px;width:27px;height:27px;border-radius:50%;background:{T["knob"]};box-shadow:0 1px 3px #0003"></i></span>'
    pill=lambda t,bg,fg: f'<span style="font:600 13px system-ui;background:{bg};color:{fg};padding:4px 10px;border-radius:11px;white-space:nowrap">{t}</span>'
    return f'''{nav(T,"Components")}<div class="sc">
{hd(T,"Status")}{grp(T,[row(T,f'<span style="display:flex;gap:6px;flex-wrap:wrap;padding:6px 0">{pill("Draft",T["canvas"],T["text"])}{pill("Unsent",T["acc"],T["onacc"])}{pill("Sent",T["oktint"],T["ok"])}{pill("Error",T["errtint"],T["err"])}{pill("Coded",T["tint"],T["link"])}</span>')])}
{hd(T,"Controls")}{grp(T,[row(T,f'Use Face ID{tog(True)}'),row(T,f'Large text{tog(False)}'),row(T,f'<span style="flex:1;height:4px;border-radius:2px;background:{T["ctl"]};position:relative"><i style="position:absolute;left:0;top:0;height:4px;width:60%;background:{T["pri"]};border-radius:2px"></i><i style="position:absolute;left:56%;top:-12px;width:28px;height:28px;border-radius:50%;background:{T["knob"]};box-shadow:0 1px 4px #0005"></i></span>')])}
{hd(T,"Messages")}
<div class="grp" style="background:{T["errtint"]};color:{T["err"]};padding:12px 14px;font-size:15px;font-weight:500">Could not send. Check the connection and try again.</div>
<div class="grp" style="background:{T["tint"]};padding:12px 14px;font-size:15px;margin-top:8px">Starting DORIS. The first start takes about 20 seconds.</div>
<div style="margin:14px 14px 0">{pair(T,"Secondary","Primary")}</div>
<div style="text-align:center;margin-top:14px;color:{T["err"]};font:600 16px system-ui">Delete draft</div></div>'''

def lab(T,t,hint=""): return f'<div class="q" style="font-size:16px;margin-top:14px">{t} <span style="font:400 13px system-ui;color:{T["muted"]}">{hint}</span></div>'
def field(T,val,ph=False,unit="",bg=None,focus=False):
    ring=f";box-shadow:inset 0 0 0 2px {T['pri']}" if focus else ""
    caret=f'<i style="display:inline-block;width:2px;height:20px;background:{T["pri"]};vertical-align:-4px;margin-left:1px"></i>' if focus else ""
    return f'<div class="grp" style="background:{bg or T["card"]};box-shadow:{T["shadow"]}{ring}"><div class="row" style="min-height:48px"><span style="flex:1;font-variant-numeric:tabular-nums;{"color:"+T["muted"] if ph else ""}">{val}{caret}</span><span style="color:{T["muted"]};font-size:15px">{unit}</span></div></div>'
def fields1(T):
    step=lambda: f'<span style="display:flex;background:{T["canvas"]};border-radius:9px;margin-left:auto">'+"".join(f'<span style="width:44px;height:32px;display:flex;align-items:center;justify-content:center;font:500 20px system-ui;color:{T["link"]}">{x}</span>' for x in ["−","+"])+'</span>'
    yn=f'<div style="display:flex;gap:8px;margin:0 14px">'+"".join(f'<div style="flex:1;height:48px;border-radius:12px;display:flex;align-items:center;justify-content:center;font:{"600" if x=="Yes" else "400"} 16px system-ui;background:{T["pri"] if x=="Yes" else T["card"]};color:{T["onpri"] if x=="Yes" else T["text"]};box-shadow:{T["shadow"]}">{x}</div>' for x in ["Yes","No","DK","Ref"])+'</div>'
    return f'''{nav(T,"Fields: single answer")}<div class="sc">
{lab(T,"Single choice, short list")}{yn}
{lab(T,"Single choice, long list")}{grp(T,[opt(T,"Hospital",False),opt(T,"Other health facility",True),opt(T,"On route to facility",False)])}
{lab(T,"Number with unit","0 to 120")}{field(T,"62",unit="years",focus=True)}
{lab(T,"Number with stepper")}{grp(T,[row(T,f'<span style="font-variant-numeric:tabular-nums;font-weight:600;width:40px">3</span><span style="color:{T["muted"]}">times</span>{step()}')])}
{lab(T,"Number, out of range")}{field(T,"140",unit="years",bg=T["errtint"])}<div style="margin:6px 30px 0;font-size:14px;color:{T["err"]};font-weight:500">Age must be 120 or less.</div></div>'''
def fields2(T):
    return f'''{nav(T,"Fields: other types")}<div class="sc">
{lab(T,"Multiple choice","Select all that apply")}{grp(T,[opt(T,"Fever",True,check),opt(T,"Cough",True,check),opt(T,"Breathlessness",False,check)])}
{lab(T,"Date")}{grp(T,[row(T,f'<span style="flex:1">3 Nov 2026</span><span style="background:{T["tint"]};color:{T["link"]};padding:4px 10px;border-radius:8px;font-size:15px">Change</span>')])}
{lab(T,"Pick from list")}{grp(T,[row(T,f'<span style="flex:1">Son</span>{chev(T)}')])}
{lab(T,"Text")}{field(T,"Village or ward",ph=True)}
{lab(T,"Long text","Narrative")}<div class="grp" style="background:{T["card"]};box-shadow:{T["shadow"]};padding:12px 16px;font-size:16px;line-height:22px;min-height:66px">Chest pain for 2 hours, sweating, collapsed at home.<div style="text-align:right;font-size:12px;color:{T["muted"]}">54 / 2000</div></div></div>'''

def bopt(T,en,hi,sel,mark=radio):
    return row(T,f'{mark(T,sel)}<span style="flex:1;line-height:21px;padding:4px 0"><span style="{"font-weight:600" if sel else ""}">{en}</span><br><span style="font-size:16px">{hi}</span></span>',("background:"+T["tint"]) if sel else "",60)
bq=lambda T,en,hi,hint="": f'<div class="q">{en}</div><div class="qh" style="font-weight:500;margin-bottom:{2 if hint else 8}px">{hi}</div>'+(f'<div style="font-size:13px;color:{T["muted"]};margin:0 22px 8px">{hint}</div>' if hint else "")
def bil1(T):
    return f'''{nav(T,"Signs and symptoms",f'<span style="color:{T["muted"]};font-size:14px;margin-left:6px;white-space:nowrap">6 of 12</span>')}
<div style="height:4px;background:{T["sep"]}"><div style="width:48%;height:4px;background:{T["pri"]}"></div></div><div class="sc">
{bq(T,"Did (s)he have a fever?","क्या उसे बुखार था?")}
{grp(T,[bopt(T,"Yes","हाँ",True),bopt(T,"No","नहीं",False),bopt(T,"Doesn't know","पता नहीं",False),bopt(T,"Refused to answer","जवाब देने से इनकार",False)])}
{bq(T,"How many days did the fever last?","बुखार कितने दिन रहा?","0 to 365")}
{field(T,"4",unit="days · दिन",focus=True)}</div>
{foot(T,pair(T,"Previous · पिछला","Next · अगला"))}'''
def bil2(T):
    return f'''{nav(T,"Place of death")}<div class="sc">
{bq(T,"Where did the deceased die?","मृत्यु कहाँ हुई?")}
{grp(T,[bopt(T,"Hospital","अस्पताल",False),bopt(T,"Other health facility","अन्य स्वास्थ्य केंद्र",False),bopt(T,"Home","घर",True),bopt(T,"On route to hospital or facility","अस्पताल या केंद्र के रास्ते में",False)])}
{bq(T,"Which of these did (s)he have?","इनमें से क्या-क्या था?","Select all")}
{grp(T,[bopt(T,"Chest pain","सीने में दर्द",True,check),bopt(T,"Breathlessness","सांस फूलना",True,check),bopt(T,"Swelling of the legs","पैरों में सूजन",False,check)])}</div>
{foot(T,pair(T,"Previous · पिछला","Next · अगला"))}'''

def sheet(T,title,body,h=470):
    return f'<div style="position:absolute;inset:0;background:rgba(0,0,0,.35)"></div><div style="position:absolute;left:0;right:0;bottom:0;height:{h}px;background:{T["card"]};border-radius:16px 16px 0 0;padding:8px 0 0;color:{T["text"]}"><div style="width:36px;height:5px;border-radius:3px;background:{T["ctl"]};margin:0 auto 8px"></div><div style="display:flex;align-items:center;padding:0 16px 8px"><span style="color:{T["link"]};font-size:17px">Cancel</span><span style="flex:1;text-align:center;font:600 17px system-ui">{title}</span><span style="color:{T["link"]};font:600 17px system-ui">Done</span></div>{body}</div>'
def under(T,txt): return f'{nav(T,"Information on the deceased")}<div class="sc" style="opacity:.9">{bq(T,txt,"")}</div>'
def calendar(T):
    days=[""]*6+list(range(1,31))
    cells="".join(f'<div style="height:40px;display:flex;align-items:center;justify-content:center;font-size:17px;font-variant-numeric:tabular-nums">'+(f'<span style="width:38px;height:38px;border-radius:50%;background:{T["pri"]};color:{T["onpri"]};display:flex;align-items:center;justify-content:center;font-weight:600">{d}</span>' if d==3 else (f'<span style="color:{T["link"]};font-weight:600">{d}</span>' if d==5 else (f'<span style="color:{T["muted"]}">{d}</span>' if isinstance(d,int) and d>5 else str(d))))+'</div>' for d in days)
    body=f'''<div style="display:flex;align-items:center;padding:6px 20px"><span style="font:600 17px system-ui">November 2026 <span style="color:{T["link"]}">›</span></span><span style="margin-left:auto;color:{T["link"]};font-size:24px;letter-spacing:22px">‹›</span></div>
<div style="display:grid;grid-template-columns:repeat(7,1fr);padding:0 10px;font-size:12px;color:{T["muted"]};text-align:center;font-weight:600">{"".join(f"<div>{d}</div>" for d in ["SUN","MON","TUE","WED","THU","FRI","SAT"])}</div>
<div style="display:grid;grid-template-columns:repeat(7,1fr);padding:4px 10px">{cells}</div>
<div style="margin:6px 16px 0;font-size:13px;color:{T["muted"]}">Dates after today cannot be chosen.</div>'''
    return under(T,"Date of death")+sheet(T,"Date of death",body,480)
def monthyear(T):
    wheel=lambda items,sel: '<div style="flex:1;text-align:center">'+"".join(f'<div style="height:36px;line-height:36px;font-size:{21 if i==sel else 18}px;{"font-weight:600" if i==sel else "color:"+T["muted"]+";opacity:"+str(1-abs(i-sel)*0.28)}">{x}</div>' for i,x in enumerate(items))+'</div>'
    body=f'''<div style="position:relative;display:flex;padding:20px 30px 0">
<div style="position:absolute;left:16px;right:16px;top:92px;height:36px;border-radius:9px;background:{T["canvas"]}"></div>
<div style="position:relative;display:flex;flex:1">{wheel(["Jul","Aug","Sep","Oct","Nov"],2)}{wheel(["2022","2023","2024","2025","2026"],2)}</div></div>
<div style="margin:16px;display:flex;gap:8px"><span style="background:{T["tint"]};color:{T["link"]};padding:8px 12px;border-radius:10px;font-size:15px">Month not known</span><span style="background:{T["canvas"]};padding:8px 12px;border-radius:10px;font-size:15px">Year not known</span></div>'''
    return under(T,"Month and year of birth")+sheet(T,"Month and year",body,360)
def recording(T):
    bars="".join(f'<i style="width:3px;border-radius:2px;background:{T["pri"] if i<34 else T["ctl"]};height:{6+int(abs(((i*37)%23)-11)*2.6)}px"></i>' for i in range(52))
    return f'''{nav(T,"Record the narrative")}<div class="sc">
<div class="q">Tell me in your own words what happened</div><div class="qh" style="font-weight:500">अपने शब्दों में बताइए कि क्या हुआ</div>
<div class="grp" style="background:{T["card"]};box-shadow:{T["shadow"]};padding:24px 16px;text-align:center;margin-top:10px">
<div style="font:600 40px system-ui;font-variant-numeric:tabular-nums">02:14</div>
<div style="display:flex;gap:3px;align-items:center;justify-content:center;height:70px;margin:14px 0">{bars}</div>
<div style="display:flex;align-items:center;justify-content:center;gap:28px;margin-top:8px">
<span style="width:48px;height:48px;border-radius:50%;background:{T["tint"]};color:{T["link"]};display:flex;align-items:center;justify-content:center;font-size:18px">❚❚</span>
<span style="width:72px;height:72px;border-radius:50%;box-shadow:inset 0 0 0 4px {T["ctl"]};display:flex;align-items:center;justify-content:center"><i style="width:28px;height:28px;border-radius:6px;background:{T["err"]}"></i></span>
<span style="width:48px;height:48px"></span></div>
<div style="color:{T["muted"]};font-size:14px;margin-top:12px">Recording · stays on this phone until sent</div></div>
{hd(T,"Saved recordings")}{grp(T,[row(T,f'<span style="width:32px;height:32px;border-radius:50%;background:{T["tint"]};color:{T["link"]};display:flex;align-items:center;justify-content:center;margin-right:12px;font-size:13px">▶</span><span style="flex:1">Narrative part 1<br><span style="color:{T["muted"]};font-size:13px">05:32 · 4.1 MB</span></span>',h=60)])}</div>'''
def camera(T):
    return f'''<div style="flex:1;background:#111;color:#fff;display:flex;flex-direction:column;position:relative">
<div style="display:flex;align-items:center;padding:10px 16px;font-size:17px"><span>Cancel</span><span style="flex:1;text-align:center;font-weight:600">Death certificate</span><span style="width:56px"></span></div>
<div style="flex:1;margin:10px 18px;border-radius:14px;background:linear-gradient(160deg,#5b6770,#2a3036);position:relative;overflow:hidden">
<div style="position:absolute;left:30px;right:30px;top:60px;bottom:90px;background:#e9e5dc;border-radius:4px;transform:rotate(-3deg);box-shadow:0 8px 20px #0008"><div style="margin:18px;height:8px;background:#b9b3a6;border-radius:2px"></div>{"".join(f'<div style="margin:10px 18px;height:5px;width:{w}%;background:#cfc9bd;border-radius:2px"></div>' for w in [80,70,85,60,75,50,80,65])}</div>
{"".join(f'<i style="position:absolute;{p};width:28px;height:28px;border:{"3px solid "+T["acc"]};{b}"></i>' for p,b in [("left:20px;top:48px","border-right:0;border-bottom:0;border-radius:6px 0 0 0"),("right:20px;top:48px","border-left:0;border-bottom:0;border-radius:0 6px 0 0"),("left:20px;bottom:78px","border-right:0;border-top:0;border-radius:0 0 0 6px"),("right:20px;bottom:78px","border-left:0;border-top:0;border-radius:0 0 6px 0")])}
<div style="position:absolute;bottom:20px;left:0;right:0;text-align:center"><span style="background:rgba(0,0,0,.55);padding:6px 12px;border-radius:14px;font-size:14px">Hold steady · page found</span></div></div>
<div style="display:flex;align-items:center;justify-content:space-around;padding:14px 20px 26px">
<span style="width:44px;height:44px;border-radius:8px;background:#555 linear-gradient(160deg,#e9e5dc,#bbb)"></span>
<span style="width:72px;height:72px;border-radius:50%;box-shadow:inset 0 0 0 4px #fff;display:flex;align-items:center;justify-content:center"><i style="width:58px;height:58px;border-radius:50%;background:#fff"></i></span>
<span style="width:44px;height:44px;border-radius:50%;background:#333;display:flex;align-items:center;justify-content:center;font-size:20px">⚡</span></div></div>'''
def viewer(T):
    return f'''<div style="flex:1;background:#000;color:#fff;display:flex;flex-direction:column">
<div style="display:flex;align-items:center;padding:10px 16px;font-size:17px"><span style="color:{T["pri"] if T is DARK else "#8fc9e3"};font-size:30px;line-height:20px;margin:-4px 6px 0 0">‹</span><span style="flex:1;font-weight:600">Death certificate<br><span style="font:400 13px system-ui;opacity:.7">2 of 3 · 3 Nov 2026</span></span></div>
<div style="flex:1;display:flex;align-items:center;justify-content:center"><div style="width:250px;height:340px;background:#ece8df;border-radius:3px;padding:16px;box-sizing:border-box"><div style="height:10px;width:60%;background:#a9a395;margin:0 auto 18px;border-radius:2px"></div>{"".join(f'<div style="margin:9px 0;height:5px;width:{w}%;background:#c9c3b6;border-radius:2px"></div>' for w in [90,70,85,60,75,50,80,65,88,55,72,40])}</div></div>
<div style="display:flex;justify-content:center;gap:6px;padding:8px">{"".join(f'<span style="width:44px;height:44px;border-radius:6px;background:#ece8df;opacity:{1 if i==1 else .45};box-shadow:{"0 0 0 2px #fff" if i==1 else "none"}"></span>' for i in range(3))}</div>
<div style="display:flex;justify-content:space-around;padding:12px 20px 26px;font-size:14px;opacity:.9"><span>Retake</span><span>Rotate</span><span style="color:#f08a80">Remove</span></div></div>'''
def location(T):
    return f'''{nav(T,"Location of the household")}<div class="sc">
<div class="q">Record the GPS location</div><div class="qh" style="font-weight:500">जीपीएस स्थान दर्ज करें</div>
<div class="grp" style="background:{T["card"]};box-shadow:{T["shadow"]};margin-top:10px">
<div style="height:190px;position:relative;background:{"#dfe8e3" if T is LIGHT else "#1d2a2a"};overflow:hidden">
<i style="position:absolute;left:-20px;top:90px;width:400px;height:14px;background:{T["card"]};transform:rotate(-12deg)"></i><i style="position:absolute;left:150px;top:-20px;width:12px;height:260px;background:{T["card"]};transform:rotate(18deg)"></i>
<span style="position:absolute;left:115px;top:55px;width:90px;height:90px;border-radius:50%;background:rgba(111,182,214,.25)"></span><span style="position:absolute;left:150px;top:90px;width:20px;height:20px;border-radius:50%;background:{T["pri"]};box-shadow:0 0 0 4px #fff"></span>
<span style="position:absolute;left:8px;bottom:8px;font-size:11px;color:{T["muted"]}">Offline map tile</span></div>
{row(T,f'<span style="flex:1;font:500 15px {MONO};font-variant-numeric:tabular-nums">23.0225° N, 72.5714° E</span>')}
{row(T,f'<span style="flex:1;color:{T["muted"]};font-size:15px">Accuracy</span><span style="background:{T["oktint"]};color:{T["ok"]};padding:3px 9px;border-radius:10px;font:600 13px system-ui">± 6 m · good</span>')}
{row(T,f'<span style="flex:1;color:{T["muted"]};font-size:15px">Captured</span><span style="font-size:15px">10:42 · 8 satellites</span>')}</div>
<div style="margin:14px 14px 0">{pair(T,"Try again","Use this location")}</div>
<div style="margin:10px 22px 0;font-size:13px;color:{T["muted"]}">Works without internet. Wait for ±10 m or better before saving.</div></div>'''
def qr(T):
    return f'''<div style="flex:1;background:#111;color:#fff;display:flex;flex-direction:column;position:relative">
<div style="display:flex;align-items:center;padding:10px 16px;font-size:17px"><span>Cancel</span><span style="flex:1;text-align:center;font-weight:600">Scan enrolment code</span><span style="width:56px"></span></div>
<div style="flex:1;overflow:hidden;display:flex;flex-direction:column;align-items:center;justify-content:center;background:radial-gradient(circle at 50% 45%,#4a5258,#1a1d20)">
<div style="width:220px;height:220px;position:relative;border-radius:22px;box-shadow:0 0 0 999px rgba(0,0,0,.45)">
{"".join(f'<i style="position:absolute;{p};width:40px;height:40px;border:4px solid #fff;{b}"></i>' for p,b in [("left:0;top:0","border-right:0;border-bottom:0;border-radius:22px 0 0 0"),("right:0;top:0","border-left:0;border-bottom:0;border-radius:0 22px 0 0"),("left:0;bottom:0","border-right:0;border-top:0;border-radius:0 0 0 22px"),("right:0;bottom:0","border-left:0;border-top:0;border-radius:0 0 22px 0")])}
<div style="position:absolute;left:40px;top:40px;width:140px;height:140px;background:repeating-conic-gradient(#fff 0 25%,#ccc 0 50%) 0 0/20px 20px;opacity:.85;border-radius:4px"></div>
<i style="position:absolute;left:16px;right:16px;top:112px;height:2px;background:{T["acc"]};box-shadow:0 0 10px {T["acc"]}"></i></div>
<div style="margin-top:28px;font-size:16px;text-align:center;padding:0 30px">Point the camera at the QR code<br><span style="opacity:.7;font-size:14px">क्यूआर कोड पर कैमरा रखें</span></div></div>
<div style="display:flex;justify-content:space-around;padding:16px 20px 28px;font-size:15px"><span style="display:flex;flex-direction:column;align-items:center;gap:6px"><span style="width:52px;height:52px;border-radius:50%;background:#333;display:flex;align-items:center;justify-content:center;font-size:22px">⚡</span>Torch</span><span style="display:flex;flex-direction:column;align-items:center;gap:6px"><span style="width:52px;height:52px;border-radius:50%;background:#333;display:flex;align-items:center;justify-content:center;font-size:20px">⌨</span>Type code</span></div></div>'''

def tool(icon,label,on=False,acc="#e0a94e"):
    return f'<span style="display:flex;flex-direction:column;align-items:center;gap:5px;font-size:12px;color:{acc if on else "#fff"}"><span style="width:46px;height:46px;border-radius:50%;background:{"rgba(214,162,74,.22)" if on else "#2a2e32"};display:flex;align-items:center;justify-content:center;font-size:20px">{icon}</span>{label}</span>'
def dochead(T,left,title,right):
    return f'<div style="display:flex;align-items:center;padding:10px 16px;font-size:17px"><span style="width:64px">{left}</span><span style="flex:1;text-align:center;font-weight:600">{title}</span><span style="width:64px;text-align:right;color:#8fc9e3;font-weight:600">{right}</span></div>'
LINES="".join(f'<div style="margin:9px 0;height:5px;width:{w}%;background:#c9c3b6;border-radius:2px"></div>' for w in [90,70,85,60,75,50,80,65,88,55])
def crop(T):
    pts=[(62,70),(258,92),(270,402),(44,384)]
    poly=" ".join(f"{x},{y}" for x,y in pts)
    handles="".join(f'<circle cx="{x}" cy="{y}" r="11" fill="#fff" stroke="#d6a24a" stroke-width="3"/>' for x,y in pts)
    mids="".join(f'<rect x="{(a[0]+b[0])/2-9}" y="{(a[1]+b[1])/2-4}" width="18" height="8" rx="4" fill="#fff"/>' for a,b in zip(pts,pts[1:]+pts[:1]))
    return f'''<div style="flex:1;background:#111;color:#fff;display:flex;flex-direction:column">{dochead(T,"Cancel","Adjust corners","Next")}
<div style="flex:1;position:relative;margin:6px 0;background:linear-gradient(160deg,#6b5a48,#3b322a)">
<div style="position:absolute;left:44px;top:70px;width:226px;height:330px;background:#e9e5dc;clip-path:polygon(8% 0,100% 7%,100% 100%,0 95%);padding:22px 30px;box-sizing:border-box">{LINES}</div>
<svg width="312" height="470" style="position:absolute;left:0;top:0"><path d="M0,0H312V470H0Z M{poly.replace(" "," L")}Z" fill="rgba(0,0,0,.45)" fill-rule="evenodd"/><polygon points="{poly}" fill="none" stroke="#d6a24a" stroke-width="2.5"/>{mids}{handles}</svg>
<div style="position:absolute;right:14px;top:14px;width:84px;height:84px;border-radius:50%;overflow:hidden;box-shadow:0 0 0 3px #fff;background:#e9e5dc"><i style="position:absolute;left:41px;top:20px;width:2px;height:44px;background:#d6a24a"></i><i style="position:absolute;top:41px;left:20px;height:2px;width:44px;background:#d6a24a"></i></div>
<div style="position:absolute;bottom:12px;left:0;right:0;text-align:center"><span style="background:rgba(0,0,0,.6);padding:6px 12px;border-radius:14px;font-size:14px">Drag the corners to the page edges</span></div></div>
<div style="display:flex;justify-content:space-around;padding:10px 8px 22px">{tool("⤢","Auto",True)}{tool("▭","Whole photo")}{tool("↺","Rotate")}{tool("⇋","Flip")}</div></div>'''
def straight(T):
    return f'''<div style="flex:1;background:#111;color:#fff;display:flex;flex-direction:column">{dochead(T,"‹ Back","Straightened","Save")}
<div style="flex:1;display:flex;align-items:center;justify-content:center"><div style="width:236px;height:334px;background:#f1eee8;border-radius:2px;padding:22px 24px;box-sizing:border-box;box-shadow:0 6px 24px #000a"><div style="height:10px;width:60%;background:#a9a395;margin:0 auto 18px;border-radius:2px"></div>{LINES}</div></div>
<div style="display:flex;justify-content:center;gap:8px;padding:6px 0 10px">{"".join(f'<span style="font-size:14px;padding:7px 12px;border-radius:15px;background:{"#d6a24a" if x=="Document" else "#2a2e32"};color:{"#1b232a" if x=="Document" else "#fff"};font-weight:{600 if x=="Document" else 400}">{x}</span>' for x in ["Original","Document","Black & white"])}</div>
<div style="display:flex;justify-content:space-around;padding:6px 8px 22px">{tool("⌗","Crop")}{tool("↺","Rotate")}{tool("⇋","Flip")}{tool("↶","Undo")}</div></div>'''
def viewer2(T):
    return f'''<div style="flex:1;background:#000;color:#fff;display:flex;flex-direction:column">
<div style="display:flex;align-items:center;padding:10px 16px;font-size:17px"><span style="color:#8fc9e3;font-size:30px;line-height:20px;margin:-4px 6px 0 0">‹</span><span style="flex:1;font-weight:600">Death certificate<br><span style="font:400 13px system-ui;opacity:.7">2 of 3 · rotated 90°</span></span><span style="color:#8fc9e3;font-weight:600">Done</span></div>
<div style="flex:1;display:flex;align-items:center;justify-content:center"><div style="width:300px;height:212px;background:#ece8df;border-radius:3px;padding:14px 18px;box-sizing:border-box;position:relative"><div style="height:9px;width:50%;background:#a9a395;margin:0 auto 12px;border-radius:2px"></div>{"".join(f'<div style="margin:7px 0;height:4px;width:{w}%;background:#c9c3b6;border-radius:2px"></div>' for w in [90,70,85,60,75,50,80])}
<span style="position:absolute;right:8px;bottom:8px;background:rgba(0,0,0,.6);font-size:12px;padding:3px 8px;border-radius:10px">Pinch to zoom</span></div></div>
<div style="display:flex;justify-content:center;gap:6px;padding:8px">{"".join(f'<span style="width:44px;height:44px;border-radius:6px;background:#ece8df;opacity:{1 if i==1 else .45};box-shadow:{"0 0 0 2px #fff" if i==1 else "none"}"></span>' for i in range(3))}</div>
<div style="display:flex;justify-content:space-around;padding:8px 8px 22px">{tool("↺","Rotate",True)}{tool("⇋","Flip")}{tool("⌗","Crop")}{tool("⟲","Retake")}<span style="display:flex;flex-direction:column;align-items:center;gap:5px;font-size:12px;color:#f08a80"><span style="width:46px;height:46px;border-radius:50%;background:#2a2e32;display:flex;align-items:center;justify-content:center;font-size:20px">🗑</span>Remove</span></div></div>'''

def crumbs(T,items):
    return '<div style="display:flex;gap:4px;align-items:center;flex-wrap:wrap;margin:10px 22px 0;font-size:14px">'+f'<span style="color:{T["muted"]}"> › </span>'.join(f'<span style="{"color:"+T["link"]+";font-weight:500" if i<len(items)-1 else "font-weight:600"}">{x}</span>' for i,x in enumerate(items))+'</div>'
def searchbar(T,txt="",ph="Search"):
    return f'<div style="margin:10px 14px 0;height:38px;border-radius:10px;background:{T["ctl"]}55;display:flex;align-items:center;padding:0 10px;font-size:16px;color:{T["muted"]}">⌕&nbsp; <span style="{"color:"+T["text"] if txt else ""}">{txt or ph}</span></div>'
def site1(T):
    lvl=lambda name,sub,count: row(T,f'<span style="flex:1">{name}<br><span style="color:{T["muted"]};font-size:13px">{sub}</span></span><span style="color:{T["muted"]};font-size:15px;font-variant-numeric:tabular-nums">{count}</span>{chev(T)}',h=58)
    leaf=lambda name,sub,sel=False: row(T,f'<span style="flex:1;{"font-weight:600" if sel else ""}">{name}<br><span style="color:{T["muted"]};font-size:13px;font-weight:400">{sub}</span></span>'+(f'<span style="color:{T["link"]};font:600 20px system-ui">✓</span>' if sel else ""),("background:"+T["tint"]) if sel else "",58)
    return f'''{nav(T,"Choose site")}{searchbar(T,ph="Search state, district or facility")}
{crumbs(T,["India","Gujarat","Ahmedabad"])}<div class="sc">
{hd(T,"Blocks in Ahmedabad")}{grp(T,[lvl("Bavla","Block","4 units"),lvl("Dholka","Block","6 units"),lvl("Sanand","Block","3 units")])}
{hd(T,"Recent")}{grp(T,[leaf("PHC Bavla","Gujarat › Ahmedabad › Bavla",True),leaf("CHC Dholka","Gujarat › Ahmedabad › Dholka")])}</div>
{foot(T,btn(T,"Use PHC Bavla"))}'''
def site2(T):
    hl=lambda t: t.replace("Bav",f"<b>Bav</b>")
    res=lambda name,path,kind: row(T,f'<span style="flex:1">{hl(name)}<br><span style="color:{T["muted"]};font-size:13px">{path}</span></span><span style="font:600 12px system-ui;background:{T["canvas"]};color:{T["muted"]};padding:3px 8px;border-radius:8px">{kind}</span>',h=58)
    return f'''{nav(T,"Choose site")}{searchbar(T,"bav")}<div class="sc">
{hd(T,"3 matches")}{grp(T,[res("PHC Bavla","Gujarat › Ahmedabad › Bavla","Facility"),res("Bavla","Gujarat › Ahmedabad","Block"),res("SC Bavla Gam","Gujarat › Ahmedabad › Bavla","Sub-centre")])}
<div style="margin:12px 30px 0;font-size:13px;color:{T["muted"]}">Only units you are assigned to are shown.</div></div>'''
def listrows(T):
    r=lambda n,sub,pill: row(T,f'<span style="flex:1">{n}<br><span style="color:{T["muted"]};font-size:13px">{sub}</span></span>{pill}',h=58)
    p=lambda t,bg,fg: f'<span style="font:600 12px system-ui;background:{bg};color:{fg};padding:3px 9px;border-radius:10px">{t}</span>'
    return grp(T,[r("Kamla Devi, 62 F","PHC Bavla · 3 Nov",p("Unsent",T["acc"],T["onacc"])),r("Ramesh Patel, 48 M","PHC Bavla · 1 Nov",p("Draft",T["canvas"],T["text"])),r("Savita Ben, 71 F","CHC Dholka · 28 Oct",p("Sent",T["oktint"],T["ok"])),r("Mohan Lal, 55 M","CHC Dholka · 25 Oct",p("Sent",T["oktint"],T["ok"]))])
def filterbtn(T,active=True): return f'<span style="margin-left:auto;width:34px;height:34px;border-radius:50%;background:{T["tint"] if active else "transparent"};color:{T["link"]};display:flex;align-items:center;justify-content:center;font-size:18px">⚲</span>'
def menu(T):
    item=lambda t,chk=False,sub="",icon="",red=False: f'<div style="display:flex;align-items:center;padding:11px 16px;font-size:16px;position:relative;{"color:"+T["err"] if red else ""}"><span style="width:22px;color:{T["link"]};font-weight:600">{"✓" if chk else ""}</span><span style="flex:1">{t}</span><span style="color:{T["muted"]};font-size:14px">{sub}</span><span style="width:22px;text-align:right;color:{T["muted"]}">{icon}</span></div>'
    gap=f'<div style="height:8px;background:{T["sep"]}"></div>'
    m=f'''<div style="position:absolute;right:12px;top:92px;width:250px;border-radius:14px;overflow:hidden;background:{"rgba(250,251,252,.94)" if T is LIGHT else "rgba(38,46,52,.96)"};box-shadow:0 12px 40px rgba(0,0,0,.28)">
<div style="padding:8px 16px 2px;font-size:13px;color:{T["muted"]}">Show</div>{item("All interviews")}{item("Unsent",True,"2")}{item("Drafts",False,"1")}{item("Sent",False,"14")}{gap}
<div style="padding:8px 16px 2px;font-size:13px;color:{T["muted"]}">Sort by</div>{item("Newest first",True)}{item("Name")}{gap}
{item("Site",False,"PHC Bavla","›")}{item("Date range",False,"Any","›")}{gap}{item("Clear filters",red=True)}</div>'''
    return f'''<div class="nb" style="background:{T["bar"]}"><span style="flex:1;font:700 22px system-ui">Interviews</span>{filterbtn(T)}</div>{searchbar(T)}<div class="sc" style="opacity:.55">{hd(T,"November")}{listrows(T)}</div>
<div style="position:absolute;inset:0;background:rgba(0,0,0,.12)"></div>{m}'''
def filtered(T):
    chip=lambda t,on=True: f'<span style="flex:none;font-size:14px;padding:7px 12px;border-radius:16px;background:{T["tint"] if on else T["card"]};color:{T["link"] if on else T["text"]};font-weight:{600 if on else 400};box-shadow:{"none" if on else T["shadow"]};white-space:nowrap">{t}{" ✕" if on else " ▾"}</span>'
    return f'''<div class="nb" style="background:{T["bar"]}"><span style="flex:1;font:700 22px system-ui">Interviews</span>{filterbtn(T)}</div>{searchbar(T)}
<div style="display:flex;gap:8px;margin:10px 0 0;padding:0 14px;overflow:hidden">{chip("Unsent")}{chip("PHC Bavla")}{chip("Date",False)}</div><div class="sc">
{hd(T,"2 of 17 · filtered")}{grp(T,[row(T,f'<span style="flex:1">Kamla Devi, 62 F<br><span style="color:{T["muted"]};font-size:13px">PHC Bavla · 3 Nov</span></span><span style="font:600 12px system-ui;background:{T["acc"]};color:{T["onacc"]};padding:3px 9px;border-radius:10px">Unsent</span>',h=58),row(T,f'<span style="flex:1">Ramesh Patel, 48 M<br><span style="color:{T["muted"]};font-size:13px">PHC Bavla · 1 Nov</span></span><span style="font:600 12px system-ui;background:{T["acc"]};color:{T["onacc"]};padding:3px 9px;border-radius:10px">Unsent</span>',h=58)])}
<div style="text-align:center;margin-top:14px;color:{T["link"]};font-weight:500">Clear filters</div></div>'''

def iconbox(T,g,bg=None,fg=None):
    return f'<span style="flex:none;width:40px;height:40px;border-radius:10px;background:{bg or T["tint"]};color:{fg or T["link"]};display:flex;align-items:center;justify-content:center;font-size:20px;margin-right:14px">{g}</span>'
def optrow(T,g,title,sub,bg=None,fg=None):
    return row(T,f'{iconbox(T,g,bg,fg)}<span style="flex:1"><span style="font-weight:600">{title}</span><br><span style="color:{T["muted"]};font-size:14px">{sub}</span></span>{chev(T)}',h=72)
def welcome(T):
    return f'''<div class="sc" style="padding-bottom:0">
<div style="display:flex;flex-direction:column;align-items:center;padding:28px 24px 8px;text-align:center">
<img src="icon.png" style="width:88px;height:88px;border-radius:22px;background:#fff;box-shadow:0 4px 16px rgba(16,40,52,.15)">
<div style="font:700 26px system-ui;margin-top:14px">DigitVA Collect</div>
<div style="color:{T["muted"]};font-size:15px;margin-top:4px;line-height:20px">Verbal autopsy interviews and cause-of-death coding, on or off the network.</div></div>
{hd(T,"Get started")}{grp(T,[optrow(T,"⌗","Scan your enrolment QR","From your supervisor or the welcome email"),optrow(T,"@","Sign in with email or mobile","If your organisation gave you a password")])}
{hd(T,"Other ways")}{grp(T,[optrow(T,"▢","Use on this phone only","No server. Interviews stay on this phone",T["canvas"],T["text"]),optrow(T,"▶","Try the demo","Practice with test data",T["acctint"],"#7e541b")])}
<div style="text-align:center;margin:18px 0 0;font-size:14px;color:{T["link"]};font-weight:500">Help · हिंदी</div></div>'''
def confirmsrv(T):
    return f'''{nav(T,"Enrol this phone")}<div class="sc">
<div style="display:flex;flex-direction:column;align-items:center;padding:26px 24px 6px;text-align:center">
<span style="width:64px;height:64px;border-radius:50%;background:{T["tint"]};color:{T["link"]};display:flex;align-items:center;justify-content:center;font-size:30px">✓</span>
<div style="font:700 22px system-ui;margin-top:12px">Code accepted</div>
<div style="color:{T["muted"]};font-size:15px;margin-top:4px">Check the server before you enrol.</div></div>
{grp(T,[row(T,f'<span style="width:90px;color:{T["muted"]};font-size:15px">Server</span><span style="flex:1;font-weight:600;word-break:break-all">digitva.causeofdeathindia.com</span>'),row(T,f'<span style="width:90px;color:{T["muted"]};font-size:15px">Project</span><span style="flex:1">GUJ026 · Gujarat Health System</span>')],14)}
<div class="grp" style="background:{T["acctint"]};padding:12px 14px;margin-top:12px;font-size:14px;line-height:20px">Enrol only if this is your organisation's DigitVA server.</div></div>
{foot(T,btn(T,"Enrol on this server")+'<div style="text-align:center;margin-top:12px;color:'+T["link"]+';font-weight:500">Cancel</div>')}'''
def signin(T):
    seg=f'<div style="display:flex;background:{T["ctl"]}66;border-radius:9px;padding:2px;margin:0 14px">'+"".join(f'<div style="flex:1;text-align:center;padding:7px 0;border-radius:7px;font-size:15px;{"background:"+T["card"]+";font-weight:600;box-shadow:0 1px 3px rgba(0,0,0,.18)" if x=="Email" else ""}">{x}</div>' for x in ["Email","Mobile"])+'</div>'
    f=lambda l,v,ph=True,trail="": row(T,f'<span style="width:92px;color:{T["muted"]};font-size:15px">{l}</span><span style="flex:1;{"color:"+T["muted"] if ph else ""}">{v}</span>{trail}')
    return f'''{nav(T,"Sign in")}<div class="sc">
<div style="padding:16px 30px 12px;color:{T["muted"]};font-size:15px">GUJ026 · Gujarat Health System</div>{seg}
{grp(T,[f("Email","name@example.org"),f("Password","Required",trail=f'<span style="color:{T["link"]};font-size:20px">◉</span>')],14)}
<div class="grp" style="background:{T["errtint"]};color:{T["err"]};padding:12px 14px;margin-top:12px;font-size:15px;font-weight:500">The email or password is incorrect.</div>
<div style="margin:14px 14px 0">{btn(T,"Sign in")}</div>
<div style="display:flex;justify-content:space-between;gap:12px;margin:16px 24px 0;font-size:15px;color:{T["link"]};font-weight:500"><span>Use a sign-in code</span><span>Forgot password?</span></div></div>'''
def pin(T):
    boxes=lambda n,eye: '<div style="display:flex;gap:8px;align-items:center;margin:0 14px">'+"".join(f'<span style="flex:1;height:52px;border-radius:12px;background:{T["card"]};box-shadow:{T["shadow"]}{";box-shadow:inset 0 0 0 2px "+T["pri"] if i==n else ""};display:flex;align-items:center;justify-content:center;font:700 22px system-ui">{"•" if i<n else ""}</span>' for i in range(6))+f'<span style="flex:none;width:44px;height:52px;display:flex;align-items:center;justify-content:center;color:{T["link"]};font-size:22px">{eye}</span></div>'
    return f'''{nav(T,"Set a PIN")}<div class="sc">
<div style="display:flex;flex-direction:column;align-items:center;padding:22px 24px 10px;text-align:center"><span style="width:56px;height:56px;border-radius:50%;background:{T["tint"]};color:{T["link"]};display:flex;align-items:center;justify-content:center;font-size:24px">⚿</span>
<div style="font:700 20px system-ui;margin-top:10px">Test MO PHC01</div><div style="color:{T["muted"]};font-size:15px;margin-top:2px">This PIN unlocks the app on this phone.</div></div>
<div class="q" style="font-size:15px;margin:10px 22px 8px">PIN</div>{boxes(6,"◉")}
<div class="q" style="font-size:15px;margin:16px 22px 8px">Confirm PIN</div>{boxes(3,"◉")}
<div class="grp" style="background:{T["acctint"]};padding:12px 14px;margin-top:16px;font-size:14px;line-height:20px">At least 6 digits. A forgotten PIN cannot be recovered: you sign in again and unsent interviews are lost.</div></div>
{foot(T,btn(T,"Set PIN"))}'''
def datef(T):
    cal=f'<span style="color:{T["link"]};font-size:18px">▦</span>'
    fld=lambda v,ph=False,err=False: f'<div class="grp" style="background:{T["errtint"] if err else T["card"]};box-shadow:{T["shadow"]}"><div class="row" style="min-height:50px"><span style="flex:1;font-size:17px;{"color:"+T["muted"] if ph else ""}">{v}</span>{cal}</div></div>'
    return f'''{nav(T,"Report a death")}<div class="sc">
<div class="q" style="font-size:16px">Date of death</div>{fld("Select date",ph=True)}
<div class="q" style="font-size:16px">Date of birth</div>
{grp(T,[opt(T,"Exact date",True),opt(T,"Month and year",False),opt(T,"Year only",False),opt(T,"Not known",False)])}
<div style="height:8px"></div>{fld("12 Mar 1964")}
<div class="q" style="font-size:16px">Sex</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:0 14px">{"".join(f'<div style="height:46px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:16px;{"background:"+T["pri"]+";color:"+T["onpri"]+";font-weight:600" if x=="Female" else "background:"+T["card"]+";box-shadow:"+T["shadow"]}">{x}</div>' for x in ["Male","Female","Undetermined","Unknown"])}</div></div>
{foot(T,btn(T,"Save"))}'''
def tabs(T,act):
    return f'<div class="tabs" style="background:{T["bar"]}">'+"".join(f'<div style="color:{T["link"] if l==act else T["muted"]};{"font-weight:600" if l==act else ""}"><b>{i}</b>{l}</div>' for i,l in [("⌂","Home"),("☰","Interviews"),("+","Report"),("↻","Sync")])+'</div>'
SCR=[("home","Home",home,"Home"),("register","Report a death",register,None),("form","WHO VA form",form,None),("nqa","Narrative QA",nqa,None),("social","Social Autopsy",social,None),("cod","Coding",cod,None),("doris","DORIS",doris,None),("widgets","Components",widgets,"Home"),("fields1","Fields: single, number",fields1,None),("bil1","Bilingual: single + number",bil1,None),("bil2","Bilingual: single + multiple",bil2,None),("calendar","Calendar",calendar,None),("monthyear","Month and year",monthyear,None),("recording","Recording",recording,None),("camera","Camera",camera,None),("viewer","Image viewer",viewer,None),("location","Location",location,None),("qr","QR scanner",qr,None),("crop","Crop and straighten",crop,None),("straight","After straightening",straight,None),("viewer2","Viewer: rotate and flip",viewer2,None),("site1","Site: drill down",site1,None),("site2","Site: search",site2,None),("menu","Filter menu",menu,"Interviews"),("filtered","Filters applied",filtered,"Interviews"),("welcome","Welcome / enrol",welcome,None),("confirmsrv","Confirm server",confirmsrv,None),("signin","Sign in",signin,None),("pin","Set PIN",pin,None),("datef","Date fields and 4-option choices",datef,None),("fields2","Fields: multi, date, text",fields2,None)]
def phone(T,f,act,cap):
    t=tabs(T,act) if act else ""
    return f'<div><div class="ph" style="background:{T["canvas"]};color:{T["text"]}"><div class="st" style="{'background:#111;color:#fff' if f.__name__ in ('camera','viewer','qr','crop','straight','viewer2') else ''}"><span>9:41</span><span>●●● 5G</span></div>{f(T)}{t}</div><p class="cap">{cap}</p></div>'
mode,which=sys.argv[1],sys.argv[2].split(",")
T=LIGHT if mode=="light" else DARK
cells="".join(phone(T,f,a,c) for k,c,f,a in SCR if k in which)
css='''body{margin:0;background:#dfe3e6;font-family:system-ui,-apple-system,sans-serif;padding:28px;width:1500px}
.g{display:flex;gap:24px;flex-wrap:wrap}.ph{width:330px;height:680px;border:9px solid #111;border-radius:46px;overflow:hidden;display:flex;flex-direction:column;position:relative}
.st{height:40px;display:flex;justify-content:space-between;align-items:flex-end;padding:0 26px 4px;font:600 14px system-ui}
.nb{height:48px;display:flex;align-items:center;padding:0 12px;font:600 17px system-ui;flex:none}
.sc{flex:1;overflow:hidden;padding-bottom:12px}
.hd{font-size:13px;margin:18px 30px 6px;letter-spacing:.2px;text-transform:uppercase}
.q{font:600 17px system-ui;margin:18px 22px 2px}.qh{font-size:16px;margin:2px 22px 8px}
.grp{margin:0 14px;border-radius:12px;overflow:hidden}
.row{display:flex;align-items:center;padding:6px 16px;font-size:17px;position:relative;box-sizing:border-box}
.btn{flex:1;height:50px;border-radius:14px;display:flex;align-items:center;justify-content:center;font:600 17px system-ui}
.ft{padding:10px 14px 12px;flex:none}
.num{min-width:36px;height:30px;padding:0 10px;border-radius:15px;font:700 18px system-ui;font-variant-numeric:tabular-nums;display:flex;align-items:center;justify-content:center;box-sizing:border-box}
.tabs{height:70px;display:flex;justify-content:space-around;padding-top:8px;font-size:12px;flex:none;margin-top:auto}
.tabs div{display:flex;flex-direction:column;align-items:center;gap:3px}.tabs b{font-size:21px;line-height:23px}
.cap{text-align:center;font-size:16px;color:#333;margin:10px 0 18px;font-weight:600}'''
open(f"p-{mode}-{sys.argv[3]}.html","w").write(f'<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head><body><div class="g">{cells}</div></body></html>')
