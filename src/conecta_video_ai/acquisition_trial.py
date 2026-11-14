"""Private observational review of a fixed-frequency acquisition period. Never publishes."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime,timedelta,timezone
import json,re,sqlite3
from pathlib import Path
from statistics import median
from .acquisition_tracking import REFERENCE,whatsapp_enquiries_window
from .campaign_queue import atomic_json
from .social_analytics import numeric,parse_time

METRICS=("reach","views","profile_visits","saved","shares","link_clicks")

def trial_times(config):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,90}",str(config.get("trial_id",""))):
        raise ValueError("Invalid trial id")
    values=[]
    for key in ("starts_at","ends_at"):
        value=datetime.fromisoformat(str(config[key]).replace("Z","+00:00"))
        if value.tzinfo is None:raise ValueError("Trial dates need an explicit timezone")
        values.append(value.astimezone(timezone.utc))
    if values[1]<=values[0]:raise ValueError("Trial duration must be positive")
    return values

def observations(folder):
    path=Path(folder)/"observations.sqlite3"
    if not path.exists():return []
    with sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True) as db:
        rows=db.execute("SELECT at,record FROM observations ORDER BY at").fetchall()
    result=[]
    for at,payload in rows:
        row=json.loads(payload);row.setdefault("collected_at",at);result.append(row)
    return result

def latest_rows(records,now):
    chosen={}
    for row in records:
        observed=parse_time(row.get("collected_at"));created=parse_time(row.get("timestamp"))
        if not observed or not created or observed>now or created>now:continue
        key=(row.get("platform"),row.get("media_id"))
        if key not in chosen or observed>parse_time(chosen[key]["collected_at"]):chosen[key]=row
    return list(chosen.values())

def matched_rows(records,start,end,now,age_hours,story_age_hours=(12,24)):
    chosen={}
    for row in records:
        created=parse_time(row.get("timestamp"));observed=parse_time(row.get("collected_at"))
        if not created or not observed or not start<=created<end or observed>now:continue
        age=(observed-created).total_seconds()/3600
        ages=story_age_hours if row.get("format")=="story" else age_hours
        if not ages[0]<=age<=ages[1] or numeric(row.get("metrics",{}).get("reach")) is None:continue
        key=(row.get("platform"),row.get("media_id"))
        if key not in chosen or observed<parse_time(chosen[key]["collected_at"]):chosen[key]=row
    return list(chosen.values())

def format_summary(rows):
    groups=defaultdict(list)
    for row in rows:groups[row.get("platform","unknown")+"/"+row.get("format","unknown")].append(row)
    result={}
    for key,items in groups.items():
        summary={"posts":len(items),"metrics":{}}
        for metric in METRICS:
            values=[r.get("metrics",{}).get(metric) for r in items if numeric(r.get("metrics",{}).get(metric)) is not None]
            summary["metrics"][metric]={"available_posts":len(values),"sum":sum(values) if values else None}
        reach=[r["metrics"]["reach"] for r in items]
        summary["median_reach"]=median(reach);summary["summed_post_reach"]=sum(reach)
        result[key]=summary
    return result

def coverage(rows):
    tracked=sum(bool(REFERENCE.fullmatch(str(r.get("tracking_code","")))) for r in rows)
    return {"posts":len(rows),"tracked_posts":tracked,"fraction":tracked/len(rows) if rows else None}

def build_review(config,records,*,now,baseline_contacts,trial_contacts):
    start,end=trial_times(config);duration=end-start;age_hours=config.get("metric_age_hours",[48,96])
    latest=latest_rows(records,now)
    baseline_posts=[r for r in latest if start-duration<=parse_time(r["timestamp"])<start]
    trial_posts=[r for r in latest if start<=parse_time(r["timestamp"])<min(end,now)]
    baseline=format_summary(matched_rows(records,start-duration,start,now,age_hours,config.get("story_metric_age_hours",[12,24])))
    trial=format_summary(matched_rows(records,start,end,now,age_hours,config.get("story_metric_age_hours",[12,24])))
    baseline_coverage=coverage(baseline_posts);trial_coverage=coverage(trial_posts)
    pairs=[key for key in baseline.keys()&trial.keys()
           if key.startswith("instagram/") and not key.endswith("/story")
           and min(baseline[key]["posts"],trial[key]["posts"])>=config.get("minimum_comparable_posts",6)
           and min(baseline[key]["summed_post_reach"],trial[key]["summed_post_reach"])>=config.get("minimum_summed_post_reach",200)]
    reasons=[]
    if now<end:reasons.append("El período de observación todavía no termina.")
    if not pairs:reasons.append("Faltan muestras comparables con alcance suficiente y antigüedad de 48 a 96 horas.")
    if baseline_contacts.get("status")!="available" or trial_contacts.get("status")!="available":
        reasons.append("La atribución de consultas no está disponible para ambos períodos.")
    if min(baseline_coverage["fraction"] or 0,trial_coverage["fraction"] or 0)<config.get("minimum_tracking_coverage",.8):
        reasons.append("La cobertura de referencias es insuficiente para comparar consultas.")
    recommendation="mantener_frecuencia"
    if now>=end and not reasons:
        before=baseline_contacts.get("distinct_contacts");after=trial_contacts.get("distinct_contacts")
        reach_ok=any(trial[key]["median_reach"]>=baseline[key]["median_reach"]*.8 for key in pairs)
        if before is not None and after is not None and after>=config.get("minimum_trial_contacts",3) and after>before and reach_ok:
            recommendation="considerar_prueba_limitada_dos_publicaciones_extra_por_semana"
        else:reasons.append("Las señales disponibles no justifican ampliar la frecuencia.")
    phase="pendiente" if now<start else "en_observacion" if now<end else "periodo_cerrado"
    return {"trial_id":config["trial_id"],"generated_at":now.isoformat(),"starts_at":start.isoformat(),"ends_at":end.isoformat(),
        "latest_observation_at":max((r["collected_at"] for r in latest),default=None),
        "phase":phase,"elapsed_days":round(max(0,min((now-start).total_seconds(),duration.total_seconds()))/86400,2),
        "frequency_changed_by_report":False,"automatic_frequency_changes":False,
        "recommendation":recommendation,"reasons":reasons,"comparable_formats":pairs,
        "baseline":{"starts_at":(start-duration).isoformat(),"ends_at":start.isoformat(),"tracking_coverage":baseline_coverage,
                    "matched_age_formats":baseline,"whatsapp":baseline_contacts},
        "observation":{"starts_at":start.isoformat(),"ends_at":min(end,max(start,now)).isoformat(),"tracking_coverage":trial_coverage,
                       "matched_age_formats":trial,"whatsapp":trial_contacts},
        "limitations":["Es una observación con mezcla creativa cambiante, no una prueba aleatoria de frecuencia.",
            "El alcance sumado entre publicaciones no representa personas únicas.",
            "Las consultas con referencia no demuestran ventas ni capturan todos los contactos.",
            "Cada contacto se cuenta una sola vez en el total del período aunque mencione varias referencias.",
            "Las métricas ausentes permanecen desconocidas y las publicaciones recientes esperan madurar.",
            "La recomendación no cambia horarios ni publica contenido."]}

def refresh_trial_report(folder,config_path,*,now=None,enquire=whatsapp_enquiries_window):
    config_path=Path(config_path)
    if not config_path.exists():return None
    config=json.loads(config_path.read_text(encoding="utf-8"))
    if not config.get("enabled"):return None
    now=now or datetime.now(timezone.utc);start,end=trial_times(config)
    rows=observations(folder);latest=latest_rows(rows,now)
    def contacts(since,until):
        if until<=since:return {"status":"period_not_started","distinct_contacts":None,"per_reference":None}
        published=[r for r in latest if parse_time(r["timestamp"])<until]
        return enquire(published,since=since,until=until)
    baseline_contacts=contacts(start-(end-start),min(start,now))
    trial_contacts=contacts(start,min(end,now))
    result=build_review(config,rows,now=now,baseline_contacts=baseline_contacts,trial_contacts=trial_contacts)
    destination=Path(folder)/"trials"/config["trial_id"];destination.mkdir(parents=True,exist_ok=True)
    atomic_json(destination/"latest.json",result)
    def value(v):return "No disponible" if v is None else str(v)
    text="# Seguimiento de captación durante 14 días\n\n"
    text+="Estado: "+result["phase"]+".\n\nInicio: "+result["starts_at"]+". Fin: "+result["ends_at"]+".\n\n"
    text+="Recomendación: "+result["recommendation"]+". Los horarios no se modifican automáticamente.\n\n"
    text+="Consultas distintas con referencia durante la observación: "+value(trial_contacts.get("distinct_contacts"))+".\n\n"
    text+="Consultas distintas con referencia en el período anterior: "+value(baseline_contacts.get("distinct_contacts"))+".\n\n"
    for reason in result["reasons"]:text+="- "+reason+"\n"
    text+="\nLas métricas se comparan por red y formato con observaciones de 48 a 96 horas; para Stories se usan observaciones de 12 a 24 horas. Una referencia se comparte entre redes; no prueba una venta.\n"
    (destination/"informe.md").write_text(text,encoding="utf-8")
    return result
