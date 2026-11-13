"""Read-only Meta performance collection and conservative, evidence-based rotation."""
from __future__ import annotations
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
import math
from pathlib import Path
import random
import re
import sqlite3
from statistics import median
from threading import Lock
import time
import unicodedata

from .campaign_queue import atomic_json, safe_error
from .service_images import canonical

ROOT=Path(__file__).resolve().parents[2]
INTENT_WEIGHTS={"saved":3.0,"shares":3.0,"replies":5.0,"profile_visits":4.0,"follows":6.0,"link_clicks":6.0}


def stamp():
    return datetime.now(timezone.utc)


def parse_time(value):
    if not value:return None
    try:
        if isinstance(value,(int,float)) or str(value).isdigit():
            return datetime.fromtimestamp(float(value),timezone.utc)
        dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except (ValueError,OverflowError,OSError):return None


def numeric(value):
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0 else None


def metric_values(payload):
    result={}
    for row in payload.get("data",[]):
        values=row.get("values") or []
        value=(row.get("total_value") or {}).get("value")
        if value is None and values:value=values[-1].get("value")
        if numeric(value) is not None:result[row["name"]]=value
        elif isinstance(value,dict):result[row["name"]]=value
    return result


def norm(value):
    return "".join(c for c in unicodedata.normalize("NFD",str(value).lower()) if unicodedata.category(c)!="Mn")


class ReadBudget:
    def __init__(self,maximum=120,seconds=480):
        self.maximum,self.used,self.deadline=maximum,0,time.monotonic()+seconds
        self.lock=Lock()
    def reserve(self):
        with self.lock:
            if self.used>=self.maximum or time.monotonic()>self.deadline:
                raise RuntimeError("read_budget_exhausted")
            self.used+=1


def publication_index(root):
    by_id,by_caption={},{}
    def add(platform,media_id,meta):
        if media_id:by_id[(platform,str(media_id))]=meta
    for path in sorted((root/"instagram/drafts").glob("*/draft.json")):
        try:d=json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError,ValueError):continue
        meta={k:d.get(k) for k in ["draft_id","campaign_id","objective","category_label","caption","tracking_code"]}
        meta["category_id"]=canonical(str(d.get("asset_category_id") or d.get("category_id") or ""))
        if d.get("caption"):by_caption[hashlib.sha256(d["caption"].strip().encode()).hexdigest()]=meta
        add("instagram",d.get("post_id"),meta);add("instagram",d.get("story_id"),meta)
        for field in ["facebook_publication","facebook_story"]:
            rec=d.get(field) or {}
            if isinstance(rec,dict):add("facebook",rec.get("post_id") or rec.get("story_id"),meta)
        for delivery in d.get("campaign_deliveries") or []:
            receipt=delivery.get("receipt") or {}
            add("instagram" if str(delivery.get("channel","")).startswith("instagram") else "facebook",
                receipt.get("post_id") or receipt.get("story_id"),meta)
    return by_id,by_caption


class MetaInsightsCollector:
    def __init__(self,publisher,output_root,*,max_calls=120,max_posts=60,now=None):
        self.publisher,self.root=publisher,Path(output_root)
        self.budget=ReadBudget(max_calls)
        self.max_posts=max(1,min(max_posts,150))
        self.now=now or stamp()
        self.warnings=[]
        self.by_id,self.by_caption=publication_index(self.root)
        self.page_token=None
        self.facebook_denial=None

    def read(self,path,params,token=None):
        self.budget.reserve()
        return self.publisher._http(method="GET",path=path,params=params,access_token=token)

    def page_rows(self,path,params,limit,token=None):
        rows=[];after=None;seen=set()
        while len(rows)<limit:
            args={**params,"limit":min(50,limit-len(rows))}
            if after:args["after"]=after
            data=self.read(path,args,token)
            rows.extend(data.get("data") or [])
            after=((data.get("paging") or {}).get("cursors") or {}).get("after")
            if not (data.get("paging") or {}).get("next") or not after or after in seen:break
            seen.add(after)
        return rows[:limit]

    def attach(self,row):
        meta=self.by_id.get((row["platform"],row["media_id"]))
        if not meta and row.get("caption"):
            meta=self.by_caption.get(hashlib.sha256(row["caption"].strip().encode()).hexdigest())
        row.update({k:v for k,v in (meta or {}).items() if k!="caption" and v})
        row.setdefault("category_id","sin_clasificar")
        return row

    def metrics(self,row):
        issues=[];metrics=dict(row.get("metrics") or {})
        try:
            if row["platform"]=="instagram":
                names=["views","reach","shares","total_interactions"]
                names+=["replies"] if row["format"]=="story" else ["saved","profile_visits","follows"]
                try:data=self.read("/"+row["media_id"]+"/insights",{"metric":",".join(names)})
                except Exception as exc:
                    # Reels sometimes omit profile metrics; retain the supported core.
                    if "profile_visits" not in names or not any(x in str(exc) for x in ["(#100)","code=100",'"code":100']):raise
                    names=[n for n in names if n not in {"profile_visits","follows"}]
                    data=self.read("/"+row["media_id"]+"/insights",{"metric":",".join(names)})
                metrics.update(metric_values(data))
            else:
                if self.facebook_denial:raise RuntimeError(self.facebook_denial)
                names="story_media_view,story_total_media_view_unique,story_interaction" if row["format"]=="story" else "post_media_view,post_total_media_view_unique,post_clicks_by_type,post_reactions_by_type_total"
                data=self.read("/"+row["media_id"]+"/insights",{"metric":names},self.page_token)
                raw=metric_values(data)
                if row["format"]=="story":
                    for source,target in [("story_media_view","views"),("story_total_media_view_unique","reach"),("story_interaction","total_interactions")]:
                        if numeric(raw.get(source)) is not None:metrics[target]=raw[source]
                if not raw:issues.append("facebook_insights_empty")
                for key,target in [("post_media_view","views"),("post_total_media_view_unique","reach")]:
                    if numeric(raw.get(key)) is not None:metrics[target]=raw[key]
                clicks=raw.get("post_clicks_by_type")
                if isinstance(clicks,dict) and numeric(clicks.get("link clicks")) is not None:
                    metrics["link_clicks"]=clicks["link clicks"]
                reactions=raw.get("post_reactions_by_type_total")
                if isinstance(reactions,dict):
                    metrics["reactions"]=sum(v for v in reactions.values() if numeric(v) is not None)
        except Exception as exc:
            issues.append(safe_error(exc))
            if row["platform"]=="facebook" and any(term in str(exc).lower() for term in ["permission","read_insights","(#10)"]):
                self.facebook_denial="facebook_insights_permission_unavailable"
        row.update(metrics=metrics,issues=issues,collected_at=self.now.isoformat())
        return row

    def collect(self):
        p=self.publisher
        records=[];accounts={}
        for platform,path,params in [
            ("instagram","/"+p.ig_user_id,{"fields":"id,username,followers_count,media_count"}),
            ("facebook","/"+p.page_id,{"fields":"id,name,fan_count,followers_count"})]:
            try:
                data=self.read(path,params)
                accounts[platform]={k:v for k,v in data.items() if k in {"username","name","followers_count","fan_count","media_count"}}
            except Exception as exc:self.warnings.append(platform+": "+safe_error(exc))
        try:
            rows=self.page_rows("/"+p.ig_user_id+"/media",
                {"fields":"id,caption,media_type,media_product_type,timestamp,permalink,like_count,comments_count"},self.max_posts)
            for r in rows:
                kind="reel" if r.get("media_product_type")=="REELS" else "carousel" if r.get("media_type")=="CAROUSEL_ALBUM" else "feed"
                metrics={target:r[key] for key,target in [("like_count","likes"),("comments_count","comments")] if numeric(r.get(key)) is not None}
                records.append(self.attach({"platform":"instagram","media_id":r["id"],"format":kind,"timestamp":r.get("timestamp"),
                    "permalink":r.get("permalink"),"caption":r.get("caption",""),"metrics":metrics}))
        except Exception as exc:self.warnings.append("instagram_media: "+safe_error(exc))
        try:
            rows=self.page_rows("/"+p.ig_user_id+"/stories",{"fields":"id,media_type,timestamp,permalink"},20)
            for r in rows:
                records.append(self.attach({"platform":"instagram","media_id":r["id"],"format":"story","timestamp":r.get("timestamp"),
                    "permalink":r.get("permalink"),"caption":"","metrics":{}}))
        except Exception as exc:self.warnings.append("instagram_stories: "+safe_error(exc))
        try:
            self.page_token=p.resolve_page_access_token()
            rows=self.page_rows("/"+p.page_id+"/posts",{"fields":"id,message,created_time,permalink_url"},min(25,self.max_posts),self.page_token)
            for r in rows:
                records.append(self.attach({"platform":"facebook","media_id":r["id"],
                    "format":"reel" if "/reel/" in (r.get("permalink_url") or "") else "post",
                    "timestamp":r.get("created_time"),"permalink":r.get("permalink_url"),"caption":r.get("message",""),"metrics":{}}))
            stories=self.read("/"+p.page_id+"/stories",{"limit":20},self.page_token)
            for r in stories.get("data") or []:
                if r.get("status")!="published":continue
                records.append(self.attach({"platform":"facebook","media_id":str(r.get("post_id") or r.get("id")),
                    "format":"story","timestamp":r.get("creation_time"),"permalink":r.get("url"),"caption":"","metrics":{}}))
        except Exception as exc:self.warnings.append("facebook_media: "+safe_error(exc))
        records=list({(r["platform"],r["media_id"]):r for r in records}.values())
        # Query Instagram first so limited Facebook access cannot consume its budget.
        with ThreadPoolExecutor(max_workers=3) as pool:
            records=list(pool.map(self.metrics,records))
        return {"collected_at":self.now.isoformat(),"accounts":accounts,"records":records,
                "warnings":self.warnings,"api_reads":self.budget.used}


def save_observations(folder,report):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(folder/"observations.sqlite3") as db:
        db.execute("CREATE TABLE IF NOT EXISTS observations(platform TEXT,media_id TEXT,at TEXT,record TEXT,PRIMARY KEY(platform,media_id,at))")
        for r in report["records"]:
            db.execute("INSERT OR REPLACE INTO observations VALUES (?,?,?,?)",
                       (r["platform"],r["media_id"],report["collected_at"],json.dumps(r,ensure_ascii=False)))
        cutoff=(parse_time(report["collected_at"])-timedelta(days=120)).isoformat()
        db.execute("DELETE FROM observations WHERE at<?",(cutoff,))
    atomic_json(folder/"latest.json",report)


def latest_observations(folder):
    path=Path(folder)/"observations.sqlite3"
    if not path.exists():return []
    with sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True) as db:
        rows=db.execute("SELECT o.record FROM observations o JOIN (SELECT platform,media_id,MAX(at) at FROM observations GROUP BY platform,media_id) last USING(platform,media_id,at)").fetchall()
    return [json.loads(row[0]) for row in rows]


def intent_points(metrics):
    return sum(float(metrics[k])*weight for k,weight in INTENT_WEIGHTS.items() if numeric(metrics.get(k)) is not None)


def analyze(records,*,now=None):
    now=now or stamp();groups=defaultdict(list);top=[]
    for r in records:
        metrics=r.get("metrics") or {};reach=numeric(metrics.get("reach"))
        created=parse_time(r.get("timestamp"))
        if reach is None or not created:continue
        age=(now-created).total_seconds()/3600
        if age<0:continue
        points=intent_points(metrics)
        top.append({**{k:r.get(k) for k in ["platform","format","media_id","timestamp","permalink","category_id","campaign_id","caption"]},
                    "metrics":dict(metrics),"age_hours":round(age,1),"reach":reach,"views":metrics.get("views"),
                    "interactions":metrics.get("total_interactions"),"intent_points":points,
                    "intent_rate":round(points/reach,4) if reach else None})
        observed=parse_time(r.get("collected_at")) or now
        fresh=0<=(now-observed).total_seconds()<=48*3600
        if fresh and 48<=age<=45*24 and reach>0 and r.get("objective")=="captar_clientes":
            key=(r["platform"],r["format"],r.get("category_id") or "sin_clasificar")
            groups[key].append(r)
    categories={};evidence=[]
    for (platform,fmt,category),rows in groups.items():
        reach=sum(r["metrics"]["reach"] for r in rows)
        points=sum(intent_points(r["metrics"]) for r in rows)
        eligible=platform=="instagram" and fmt in {"feed","carousel"} and category not in {"general","campaign","sin_clasificar"} and len(rows)>=3 and reach>=100 and points>=3
        evidence.append({"platform":platform,"format":fmt,"category_id":category,"posts":len(rows),
                         "summed_post_reach":reach,"intent_points":points,"eligible":eligible,
                         "smoothed_rate":(points+1)/(reach+100)})
    comparable=defaultdict(list)
    for e in evidence:
        if e["eligible"]:comparable[(e["platform"],e["format"])].append(e)
    for key,rows in comparable.items():
        # Need multiple eligible categories to compare rather than crown the only sample.
        if len(rows)<2:continue
        baseline=median(r["smoothed_rate"] for r in rows)
        for e in rows:
            weight=max(.85,min(1.30,e["smoothed_rate"]/max(baseline,.000001)))
            categories[e["category_id"]]=max(categories.get(e["category_id"],.85),round(weight,3))
    formats=[]
    by_format=defaultdict(list)
    for row in top:
        if row["age_hours"]>=48:by_format[(row["platform"],row["format"])].append(row)
    for (platform,fmt),rows in by_format.items():
        formats.append({"platform":platform,"format":fmt,"posts":len(rows),
                        "median_reach":median(r["reach"] for r in rows),
                        "intent_points":sum(r["intent_points"] for r in rows)})
    return {"generated_at":now.isoformat(),"formats":formats,
            "top_by_reach":sorted(top,key=lambda r:(-r["reach"],r["media_id"]))[:15],
            "top_by_intent":sorted([r for r in top if r["age_hours"]>=48],key=lambda r:(-r["intent_points"],-r["reach"]))[:15],
            "category_evidence":evidence,"policy":{"generated_at":now.isoformat(),"category_weights":categories,
            "campaign_weights":{},"exploration_every":3,"max_age_hours":48},
            "limitations":["Views are not clicks or customers.","Link clicks, saves, replies and profile activity are intent signals, not confirmed sales.",
                           "Missing metrics remain unavailable; they are not zero.","Cross-format lifetime reach is descriptive, not a causal test.",
                           "Stories expire; historical snapshots are kept privately."]}


def rotation_policy(output_root,*,now=None):
    try:
        data=json.loads((Path(output_root)/"instagram/analytics/policy.json").read_text())
        if not isinstance(data,dict) or not isinstance(data.get("category_weights",{}),dict):return {}
        created=parse_time(data.get("generated_at"))
        if not created or not 0<=(now or stamp()).timestamp()-created.timestamp()<=48*3600:return {}
        return data
    except (OSError,ValueError,TypeError):return {}


def category_weight(output_root,category,*,now=None):
    value=(rotation_policy(output_root,now=now).get("category_weights") or {}).get(canonical(category),1)
    return max(.85,min(1.30,float(value))) if numeric(value) is not None else 1.0


def adaptive_sequence_index(pool,default_index,state,catalog,key_of,output_root):
    policy=rotation_policy(output_root)
    weights=policy.get("category_weights") or {}
    counter=int(state.get("counter",0))
    if not weights or counter%3==0:return default_index
    recent=set((state.get("recent_assets") or [])[-max(1,min(18,len(pool)-1)):])
    candidates=[i for i,item in enumerate(pool) if key_of(item.path) not in recent]
    if not candidates:return default_index
    weighted=[]
    for i in candidates:
        code=canonical(str((catalog.get(key_of(pool[i].path)) or {}).get("category_id") or ""))
        value=weights.get(code,1)
        weighted.append(max(.85,min(1.30,float(value))) if numeric(value) is not None else 1)
    # A stable seed keeps category and asset selection aligned within one publishing attempt.
    rng=random.Random("acquisition:"+str(counter)+":"+str(default_index))
    return rng.choices(candidates,weights=weighted,k=1)[0]


def write_report_html(path,analysis,report):
    def table(rows,columns):
        out="<table><thead><tr>"+"".join("<th>"+html.escape(title)+"</th>" for key,title in columns)+"</tr></thead><tbody>"
        for row in rows:
            cells=[]
            for key,title in columns:
                value=row.get(key)
                label=html.escape(str(value)) if value is not None else "—"
                if key=="permalink" and isinstance(value,str) and value.startswith("https://"):
                    label='<a href="'+html.escape(value,quote=True)+'" rel="noreferrer">Ver publicación</a>'
                cells.append("<td>"+label+"</td>")
            out+="<tr>"+"".join(cells)+"</tr>"
        return out+"</tbody></table>"
    text='<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ConectaProIA · Rendimiento de publicaciones</title><style>body{font:16px system-ui;background:#f7f5ee;color:#163e35;padding:30px;max-width:1300px;margin:auto}table{border-collapse:collapse;width:100%;background:white;margin:20px 0}td,th{padding:12px;text-align:left;border-bottom:1px solid #ddd}small{color:#555}</style><h1>Rendimiento de publicaciones</h1>'
    text+="<p>Actualizado: "+html.escape(report["collected_at"])+". Informe privado; no contiene mensajes de clientes.</p>"
    text+="<p>Visualizaciones, interacciones e intención de contacto son medidas distintas. No hay atribución de clientes o ventas confirmadas.</p><h2>Comparación descriptiva por formato</h2>"
    text+=table(analysis["formats"],[("platform","Red"),("format","Formato"),("posts","Piezas de 48 h o más"),("median_reach","Mediana de alcance"),("intent_points","Señales ponderadas de intención")])
    rows=[{**r,**r.get("metrics",{}),"caption":(r.get("caption") or "")[:140]} for r in analysis["top_by_intent"]]
    text+="<h2>Piezas con más señales de intención</h2>"+table(rows,[("platform","Red"),("format","Formato"),("caption","Texto"),("reach","Alcance"),("profile_visits","Visitas al perfil"),("follows","Seguidores nuevos"),("saved","Guardados"),("shares","Compartidos"),("permalink","Enlace")])
    text+="<h2>Aprendizaje automático</h2><p>Se preserva exploración en uno de cada tres turnos. Los ajustes requieren al menos 3 publicaciones maduras y alcance acumulado de 100 por categoría, señales de intención y otra categoría comparable. El peso queda entre 0,85 y 1,30. Los datos caducan a las 48 horas.</p>"
    text+="<p>Pesos habilitados: "+html.escape(json.dumps(analysis["policy"]["category_weights"],ensure_ascii=False))+"</p>"
    attribution=report.get("whatsapp_attribution") or {}
    text+="<h2>Consultas atribuibles por WhatsApp</h2><p>Estado: "+html.escape(attribution.get("status","no_disponible"))+". Referencias compartidas entre canales; no equivalen a ventas o contratos.</p>"
    if attribution.get("per_reference"):
        text+=table([{"reference":k,"contacts":v} for k,v in attribution["per_reference"].items()],[("reference","Referencia"),("contacts","Contactos distintos con esa referencia")])
    text+="<h2>Cobertura</h2><p>"+str(len(report["records"]))+" piezas consultadas; "+str(sum(bool(r.get("issues")) for r in report["records"]))+" con alguna métrica no disponible.</p>"
    for warning in report.get("warnings",[]):text+="<p>"+html.escape(warning)+"</p>"
    Path(path).write_text(text,encoding="utf-8")
