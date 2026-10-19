const {JSDOM}=require("jsdom");const fs=require("fs");
const html=fs.readFileSync("/home/claude/mgp_editor/webui.html","utf8");const calls=[];
const dom=new JSDOM(html,{runScripts:"dangerously",pretendToBeVisual:true,url:"http://127.0.0.1:8765/",beforeParse(w){
 w.TOKEN="t";w.URL.createObjectURL=()=>"blob:x";
 w.fetch=async(p,o)=>{calls.push(p+(o&&o.body?" "+o.body:""));const j=x=>({ok:true,status:200,json:async()=>x});
  if(p.startsWith("/api/state"))return j({open:true,mod_folder:"x",paks_dir:"",include_patch:true,paks:true});
  if(p.startsWith("/api/sheet/set"))return j({ok:true});
  if(p.startsWith("/api/sheet"))return j({has_base:true,locs:["a.locres"],loc:"__all__",files:1,suggestions:1,matched:1,sections:{riders:[{key:"MotoGP_A-B",name:"A B",loc:"Alpha Bravo",suggest:"Zed Y",group:"MotoGP",info:"t #1",changed:"PilotNumber: 1 -> 2",with:"",notes:""},{key:"Moto2_C-D",name:"C D",group:"Moto2",info:"",changed:"",with:"",notes:""}],teams:[],bikes:[],tracks:[]}});
  return j({files:[],rows:[],items:[],tables:[],names:[],bindings:[]})};
 w.addEventListener("error",e=>console.log("PAGE ERROR:",e.message));}});
const w=dom.window;
setTimeout(async()=>{const d=w.document,s=ms=>new Promise(r=>setTimeout(r,ms));
 w.eval('ST.open=true;tab("sheet")');await s(200);
 console.log("rows:",d.querySelectorAll("#sh_out input[data-f=with]").length,d.querySelector("#sh_sum").textContent);
 const i=d.querySelector("#sh_out input[data-f=with]");i.value="X Y";i.dispatchEvent(new w.Event("change"));await s(100);
 console.log(calls.filter(c=>c.includes("sheet/set")));
 d.querySelector("#sh_only").checked=true;d.querySelector("#sh_only").dispatchEvent(new w.Event("change"));console.log("only:",d.querySelectorAll("#sh_out input[data-f=with]").length);
 process.exit(0)},500);
