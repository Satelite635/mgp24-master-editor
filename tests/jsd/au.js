const {JSDOM}=require("jsdom");const fs=require("fs");
const html=fs.readFileSync("/home/claude/mgp_editor/webui.html","utf8");const calls=[];
const dom=new JSDOM(html,{runScripts:"dangerously",pretendToBeVisual:true,url:"http://127.0.0.1:8765/",beforeParse(w){
 w.TOKEN="t";w.fetch=async(p,o)=>{calls.push(p+(o&&o.body?" "+o.body:""));const j=x=>({ok:true,status:200,json:async()=>x});
  if(p.startsWith("/api/state"))return j({open:true,mod_folder:"x",paks_dir:"",include_patch:true,paks:true});
  if(p.startsWith("/api/pick"))return j({path:"D:\\sbk\\Audio"});return j({files:[],changes:[]})};
 w.addEventListener("error",e=>console.log("PAGE ERROR:",e.message));}});
const w=dom.window;
setTimeout(async()=>{const d=w.document,s=ms=>new Promise(r=>setTimeout(r,ms));
 w.eval('ST.open=true;tab("audio")');d.querySelector('[data-pick="au_root"]').click();await s(200);
 console.log("input:",d.querySelector("#au_root").value);process.exit(0)},300);
