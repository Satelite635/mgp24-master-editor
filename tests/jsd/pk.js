const {JSDOM}=require("jsdom");const fs=require("fs");
const html=fs.readFileSync("/home/claude/mgp_editor/webui.html","utf8");let polls=0;
const dom=new JSDOM(html,{runScripts:"dangerously",pretendToBeVisual:true,url:"http://127.0.0.1:8765/",beforeParse(w){
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
 w.TOKEN="t";
 w.fetch=async(p,o)=>{const j=x=>({ok:true,status:200,json:async()=>x});
  if(p.startsWith("/api/state"))return j({open:true,mod_folder:"x",paks_dir:"",include_patch:true,paks:true});
  if(p.startsWith("/api/pak/status")){polls++;const L=["Packing 2 files","[1/2] a.uasset","[2/2] b.uexp","Done"];
    return j(polls<3?{running:true,lines:L.slice(0,polls+1).slice(polls>1?2:0),next:polls+1,result:null,error:null}:{running:false,lines:L.slice(3),next:4,result:{path:"X_P.pak",files:2,bytes:2097152},error:null})}
  if(p.startsWith("/api/pak"))return j({started:true});
  if(p.startsWith("/api/changes"))return j({files:["a"],count:1});return j({files:[],rows:[],items:[],changes:[]})};
 w.addEventListener("error",e=>console.log("PAGE ERROR:",e.message));}});
const w=dom.window;
setTimeout(async()=>{const d=w.document,s=ms=>new Promise(r=>setTimeout(r,ms));
 await w.eval("refreshChanges()");console.log("before:",d.querySelector("#b_save").disabled);w.eval("packTrack()");await s(450);console.log("during save disabled:",d.querySelector("#b_save").disabled);
 console.log("running:",d.querySelector("#toast .task").textContent);
 d.querySelector("#toast .task a").click();await s(400);console.log("log dialog:",JSON.stringify(d.querySelector("#pk_log").textContent));
 await s(900);console.log("finished:",d.querySelector("#toast .task").className,"|",d.querySelector("#toast .task").textContent);
 console.log("after save disabled:",d.querySelector("#b_save").disabled);console.log("log now:",JSON.stringify(d.querySelector("#pk_log")&&d.querySelector("#pk_log").textContent));process.exit(0)},300);
