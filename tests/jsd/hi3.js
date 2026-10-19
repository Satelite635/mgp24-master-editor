const {JSDOM}=require("jsdom");const fs=require("fs");
const html=fs.readFileSync("/home/claude/mgp_editor/webui.html","utf8");const calls=[];let imp=0;
const items=[
 {key:"f/A",name:"HUDLeaderboardWidgetBP",files:["a.uasset","a.uexp"],dest:"Content/x/A",replaces:"game original",warn:false,note:"",ok:true,crash:[],missing_deps:["/Game/a/Foo"]},
 {key:"f/P",name:"PenaltyTime",files:["p.uasset"],dest:"Content/x/P",replaces:"game original",warn:true,note:"",ok:true,crash:["InvalidLapWidget"],missing_deps:[]},
 {key:"f/U",name:"Unknown",files:["u.uasset"],dest:"",replaces:"new",warn:false,note:"no place",ok:false,crash:[],missing_deps:[]}];
const dom=new JSDOM(html,{runScripts:"dangerously",pretendToBeVisual:true,url:"http://127.0.0.1:8765/",beforeParse(w){
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
 w.TOKEN="t";
 w.fetch=async(p,o)=>{calls.push(p+(o&&o.body?" "+o.body:""));const j=x=>({ok:true,status:200,json:async()=>x});
  if(p.startsWith("/api/state"))return j({open:true,mod_folder:"x",paks_dir:"",include_patch:true,paks:true});
  if(p.startsWith("/api/hud/scan"))return j({started:true});
  if(p.startsWith("/api/hud/import")){imp=1;return j({started:true})}
  if(p.startsWith("/api/pak/status"))return j(imp?{running:false,lines:["Done"],next:1,title:"Importing",error:null,result:{summary:"2 items"}}:{running:false,lines:["Done"],next:1,title:"Scanning",error:null,result:{summary:"x",items}});
  return j({files:[],changes:[]})};
 w.addEventListener("error",e=>console.log("PAGE ERROR:",e.message));}});
const w=dom.window;
setTimeout(async()=>{const d=w.document,s=ms=>new Promise(r=>setTimeout(r,ms));
 w.eval('ST.open=true;tab("hud")');await s(100);d.querySelector("#hu_src").value="C:/sbk";
 w.eval("window.__dbg=1");d.querySelector("#hi_scan").click();await s(700);console.log("hiItems:",JSON.stringify(w.eval("hiItems")).slice(0,200));console.log(d.querySelector("#hi_sum").textContent);
 console.log("checked:",[...d.querySelectorAll("#hi_out input[data-i]")].map(i=>i.checked+"/"+i.disabled).join(" "));
 console.log("row text:",d.querySelector("#hi_out").textContent.includes("will crash on load")||d.querySelector("#hi_out").textContent.includes("crash"));
 d.querySelectorAll("#hi_out input[data-i]")[1].checked=true;d.querySelector("#hi_go").click();await s(200);
 const dl=d.querySelector("dialog");console.log("dialog:",dl.open,"|",dl.textContent.slice(0,80));
 [...dl.querySelectorAll("button")].find(b=>b.textContent==="Import anyway").click();await s(400);
 console.log("import calls:",calls.filter(c=>c.startsWith("/api/hud/import")));process.exit(0)},300);
