const {JSDOM}=require("jsdom");const fs=require("fs");
const html=fs.readFileSync("/home/claude/mgp_editor/webui.html","utf8");const calls=[];
const dom=new JSDOM(html,{runScripts:"dangerously",pretendToBeVisual:true,url:"http://127.0.0.1:8765/",beforeParse(w){
 w.TOKEN="t";
 w.fetch=async(p,o)=>{calls.push(p+(o&&o.body?" "+o.body:""));const j=x=>({ok:true,status:200,json:async()=>x});
  if(p.startsWith("/api/state"))return j({open:true,mod_folder:"x",paks_dir:"",include_patch:true,paks:true});
  if(p.startsWith("/api/hud/targets"))return j({files:["Content/a/W.uasset"]});
  if(p.startsWith("/api/hud/compare"))return j({common:2,hidden:3,only_source:["X"],only_target:[],rows:[{widget:"A",cls:"Image",path:"ColorAndOpacity",group:"color",status:"patch",target:"[1]",source:"[2]"},{widget:"A",cls:"Image",path:"Font.FontObject",group:"font",status:"needs-import",target:"/a/b",source:"/a/c"},{widget:"A",cls:"Image",path:"Margin.Top",group:"layout",status:"patch",target:"1",source:"2"}]});
  if(p.startsWith("/api/hud/apply"))return j({applied:1,skipped:[]});
  return j({files:[],rows:[],items:[],tables:[],changes:[]})};
 w.addEventListener("error",e=>console.log("PAGE ERROR:",e.message));}});
const w=dom.window;
setTimeout(async()=>{const d=w.document,s=ms=>new Promise(r=>setTimeout(r,ms));
 w.eval('ST.open=true;tab("hud")');await s(200);d.querySelector("#hu_src").value="C:/x";
 d.querySelector("#hu_go").click();await s(200);
 console.log(d.querySelector("#hu_sum").textContent);
 console.log("checked:",[...d.querySelectorAll("#hu_out input[data-i]")].map(i=>i.checked+"/"+i.disabled));
 d.querySelector("#hu_apply").click();await s(200);
 console.log(calls.filter(c=>c.includes("hud/apply")).map(c=>c.slice(0,160)));process.exit(0)},500);
