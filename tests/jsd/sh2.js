const {JSDOM}=require("jsdom");const fs=require("fs");
const html=fs.readFileSync("/home/claude/mgp_editor/webui.html","utf8");const calls=[];
const dom=new JSDOM(html,{runScripts:"dangerously",pretendToBeVisual:true,url:"http://127.0.0.1:8765/",beforeParse(w){
 w.TOKEN="t";
 w.fetch=async(p,o)=>{calls.push(p+(o&&o.body?" "+o.body:""));const j=x=>({ok:true,status:200,json:async()=>x});
  if(p.startsWith("/api/state"))return j({open:true,mod_folder:"x",paks_dir:"",include_patch:true,paks:true});
  if(p.startsWith("/api/sheet/import"))return j({ok:true,imported:1});
  if(p.startsWith("/api/sheet"))return j({has_base:true,locs:["a.locres"],loc:"a.locres",sections:{riders:[{key:"MotoGP_A-B",name:"A B",group:"g",info:"",changed:"",with:"",notes:""}],teams:[],bikes:[],tracks:[]}});
  return j({files:[],rows:[],items:[],tables:[]})};
 w.addEventListener("error",e=>console.log("PAGE ERROR:",e.message));}});
const w=dom.window;w.File.prototype.text=function(){return new Promise(r=>{const fr=new w.FileReader();fr.onload=()=>r(fr.result);fr.readAsText(this)})};
setTimeout(async()=>{const s=ms=>new Promise(r=>setTimeout(r,ms));
 w.eval('ST.open=true;tab("sheet")');await s(200);
 const csv='﻿Base game,Key,Info,Replaced with,Notes,DB changes\r\n"A B","MotoGP_A-B","g ","Some, One ""Q""","line1\nline2",""\r\n';
 const f=new w.File([csv],"replacement_sheet_riders.csv");
 Object.defineProperty(w.document.querySelector("#sh_file"),"files",{value:[f],configurable:true});
 w.document.querySelector("#sh_file").dispatchEvent(new w.Event("change"));await s(300);
 console.log(calls.filter(c=>c.includes("import")));process.exit(0)},500);
