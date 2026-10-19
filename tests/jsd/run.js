const {JSDOM}=require("jsdom");const fs=require("fs");
let html=fs.readFileSync("/home/claude/mgp_editor/webui.html","utf8");
const calls=[];
const dom=new JSDOM(html,{runScripts:"dangerously",pretendToBeVisual:true,url:"http://127.0.0.1:8765/",beforeParse(w){
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
  w.TOKEN="t";
  w.fetch=async(path,opt)=>{calls.push(path);
    const j=(o)=>({ok:true,status:200,json:async()=>o});
    if(path.startsWith("/api/state"))return j({open:true,mod_folder:"x",paks_dir:"",include_patch:true,paks:true});
    if(path.startsWith("/api/choices"))return j({packages:["/Game/a/b/c1","/Game/a/b/c2"],riders:["MotoGP_X","Moto2_Y"],current:"/Game/assets/graphics/environments/Box/cat001/customization_data/DA_Box_810.DA_Box"});
    if(path.startsWith("/api/browse"))return j({dir:"Content",dirs:[{name:"assets",count:3}],items:[{name:"A",pkg:"/Game/x/A",asset:true,exts:[".uasset"],base:"Content/x/A"}],truncated:false,total_files:5});
    if(path.startsWith("/api/pick"))return j({path:"F:\\m\\Content\\a\\Z.uasset",pkg:"/Game/a/Z"});if(path.startsWith("/api/pilots"))return j({pilots:[]});
    return j({files:[],rows:[],items:[],tables:[],names:[],bindings:[]});
  };
  w.addEventListener("error",e=>console.log("PAGE ERROR:",e.message));
}});
const w=dom.window;
setTimeout(async()=>{
  try{
    w.bindings=[{rel:"R",table:"DT_BOX"}];w.cur="MotoGP_Joan-Mir";
    w.eval('bindings=[{rel:"R",table:"DT_BOX"}];cur="MotoGP_Joan-Mir";replaceDlg("R")');
    await new Promise(r=>setTimeout(r,300));
    console.log("TOAST:",w.document.querySelector("#toast").textContent);console.log(w.document.querySelector("#r_pick")&&w.document.querySelector("#r_pick").innerHTML.slice(0,400));
    const rbm=w.document.querySelector("#r_pick .rb[data-scope=mod]");rbm.click();await new Promise(r=>setTimeout(r,200));console.log("mod pick -> input:",w.document.querySelector("#r_in").value,"| pick called:",calls.includes("/api/pick"));w.document.querySelector("#r_in").value="";w.document.querySelector("#r_in").dispatchEvent(new w.Event("input"));await new Promise(r=>setTimeout(r,100));const rb=w.document.querySelector("#r_pick .rb[data-scope=pak]");rb&&rb.click();
    await new Promise(r=>setTimeout(r,300));
    console.log("--- browse view:",w.document.querySelector("#r_pick").innerHTML.slice(0,500));
  }catch(e){console.log("ERR",e)}
  const ra=w.document.querySelector("#r_pick .ra");ra&&ra.click();await new Promise(r=>setTimeout(r,200));
    console.log("after pick: input=",w.document.querySelector("#r_in").value,"| list has riders:",w.document.querySelector("#r_pick").innerHTML.includes("other riders"));
    const rb2=w.document.querySelector("#r_pick .rb");rb2&&rb2.click();await new Promise(r=>setTimeout(r,200));
    w.document.querySelector("#r_pick .rx").click();await new Promise(r=>setTimeout(r,200));
    console.log("after back: list restored:",w.document.querySelector("#r_pick").innerHTML.includes("browse everything else"));
    console.log(calls.filter(c=>c.includes("browse")));process.exit(0)},800);
