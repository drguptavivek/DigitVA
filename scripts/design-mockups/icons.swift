import AppKit
let groups:[(String,[(String,String)])]=[
("Navigation",[("chevron.left","Back"),("house","Home"),("list.bullet.rectangle","Interviews"),("plus.circle","Report"),("arrow.triangle.2.circlepath","Sync"),("person.crop.circle","Account"),("gearshape","Settings"),("questionmark.circle","Help"),("globe","Language"),("magnifyingglass","Search")]),
("Interview",[("person.text.rectangle","Deceased"),("calendar","Date"),("clock","Time"),("mappin.and.ellipse","Location"),("phone","Phone"),("mic","Record"),("camera","Camera"),("doc.text.viewfinder","Scan doc"),("qrcode.viewfinder","QR code"),("paperclip","Attach")]),
("Status",[("checkmark.circle.fill","Sent"),("arrow.up.circle","Unsent"),("pencil.circle","Draft"),("exclamationmark.triangle.fill","Error"),("icloud.slash","Offline"),("wifi","Online"),("lock.fill","Locked"),("faceid","Face ID"),("bell","Alerts"),("info.circle","Info")]),
("Photo and coding",[("rotate.left","Rotate"),("arrow.left.and.right.righttriangle.left.righttriangle.right","Flip"),("crop","Crop"),("perspective","Straighten"),("arrow.uturn.backward","Undo"),("trash","Remove"),("stethoscope","Coding"),("list.number","Chain"),("text.badge.checkmark","Accept"),("square.and.arrow.up","Share")]),
]
let pri=NSColor(srgbRed:0x1f/255,green:0x4d/255,blue:0x60/255,alpha:1)
let ink=NSColor(srgbRed:0x1b/255,green:0x23/255,blue:0x2a/255,alpha:1)
let muted=NSColor(srgbRed:0x5c/255,green:0x68/255,blue:0x72/255,alpha:1)
let canvas=NSColor(srgbRed:0xe8/255,green:0xed/255,blue:0xf0/255,alpha:1)
let ok=NSColor(srgbRed:0x1f/255,green:0x7a/255,blue:0x4d/255,alpha:1)
let err=NSColor(srgbRed:0xb3/255,green:0x26/255,blue:0x1e/255,alpha:1)
let acc=NSColor(srgbRed:0xd6/255,green:0xa2/255,blue:0x4a/255,alpha:1)
let cols=10, cw:CGFloat=118, ch:CGFloat=104, pad:CGFloat=30, gh:CGFloat=40
let W=pad*2+CGFloat(cols)*cw, H=pad*2+CGFloat(groups.count)*(gh+ch+28)
let scale:CGFloat=2
let rep=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:Int(W*scale),pixelsHigh:Int(H*scale),bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
rep.size=NSSize(width:W,height:H)
NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:rep)
canvas.setFill(); NSRect(x:0,y:0,width:W,height:H).fill()
var y=H-pad
for (title,items) in groups {
  y-=gh
  (title.uppercased() as NSString).draw(at:NSPoint(x:pad+6,y:y+10),withAttributes:[.font:NSFont.systemFont(ofSize:13,weight:.semibold),.foregroundColor:muted,.kern:0.4])
  y-=ch
  let card=NSBezierPath(roundedRect:NSRect(x:pad,y:y-8,width:CGFloat(cols)*cw,height:ch+8),xRadius:14,yRadius:14); NSColor.white.setFill(); card.fill()
  for (i,(name,label)) in items.enumerated() {
    let x=pad+CGFloat(i)*cw
    var color=pri
    if name.hasPrefix("checkmark") {color=ok}; if name.hasPrefix("exclamation"){color=err}; if name=="arrow.up.circle"{color=acc}; if name=="trash"{color=err}
    let cfg=NSImage.SymbolConfiguration(pointSize:28,weight:.regular).applying(NSImage.SymbolConfiguration(hierarchicalColor:color))
    if let img=NSImage(systemSymbolName:name,accessibilityDescription:nil)?.withSymbolConfiguration(cfg) {
      let s=img.size; img.draw(in:NSRect(x:x+(cw-s.width)/2,y:y+46+(36-s.height)/2,width:s.width,height:s.height))
    } else { ("?" as NSString).draw(at:NSPoint(x:x+50,y:y+50),withAttributes:[.font:NSFont.systemFont(ofSize:24),.foregroundColor:err]) }
    let p=NSMutableParagraphStyle(); p.alignment = .center
    (label as NSString).draw(in:NSRect(x:x,y:y+12,width:cw,height:18),withAttributes:[.font:NSFont.systemFont(ofSize:13),.foregroundColor:ink,.paragraphStyle:p])
  }
  y-=28
}
NSGraphicsContext.restoreGraphicsState()
try! rep.representation(using:.png,properties:[:])!.write(to:URL(fileURLWithPath:CommandLine.arguments[1]))
