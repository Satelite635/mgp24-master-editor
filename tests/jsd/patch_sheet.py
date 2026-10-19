h=open("/home/claude/mgp_editor/webui.html").read()
h=h.replace('''$("#sh_sum").textContent=rows.length+" of "+all.length+" - "+all.filter(r=>r.with).length+" filled";''','''$("#sh_sum").textContent=rows.length+" of "+all.length+" - "+all.filter(r=>r.with).length+" filled - names found for "+all.filter(r=>r.loc).length+" ("+shData.files+" file"+(shData.files===1?"":"s")+")"+(shData.suggestions?" - "+shData.suggestions+" changed in your mod's localization":"");
  $("#sh_fill").style.display=shData.suggestions?"":"none";''',1)
h=h.replace('''data-f="with" value="${esc(r.with)}" style="width:100%;box-sizing:border-box">''','''data-f="with" value="${esc(r.with)}" placeholder="${esc(r.suggest?"mod: "+r.suggest:"")}" style="width:100%;box-sizing:border-box">''',1)
h=h.replace('<button class="b" id="sh_imp">Import CSV / save</button>','<button class="b" id="sh_imp">Import CSV / save</button><button class="b p" id="sh_fill" style="display:none" title="Fill every empty Replaced-with cell from your mod localization">Fill from mod</button>',1)
h=h.replace('$("#sh_imp").onclick=()=>$("#sh_file").click();','''$("#sh_imp").onclick=()=>$("#sh_file").click();
$("#sh_fill").onclick=guard(async()=>{const data={};let n=0;
  for(const k in shData.sections)for(const r of shData.sections[k])if(r.suggest&&!r.with){(data[k]=data[k]||{})[r.key]={with:r.suggest};n++}
  if(!n){toast("Nothing to fill","bad");return}
  await api("/api/sheet/import",{data});toast("Filled "+n+" entries from your mod","ok");await shLoad()});''',1)
open("/home/claude/mgp_editor/webui.html","w").write(h)
