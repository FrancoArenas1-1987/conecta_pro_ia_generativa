from datetime import datetime,timedelta,timezone
import hashlib,json
from pathlib import Path
import pytest
from conecta_video_ai.acquisition_trial import build_review,matched_rows,refresh_trial_report,trial_times
from conecta_video_ai.social_analytics import save_observations
from conecta_video_ai.acquisition_tracking import tracking_code_for

START=datetime(2026,11,14,17,tzinfo=timezone.utc)
END=START+timedelta(days=14)
CONFIG={"enabled":True,"trial_id":"test_trial","starts_at":START.isoformat(),"ends_at":END.isoformat(),
        "metric_age_hours":[48,96],"minimum_comparable_posts":6,"minimum_summed_post_reach":200,
        "minimum_tracking_coverage":.8,"minimum_trial_contacts":3}

def row(identifier,created,*,age=48,reach=100,fmt="feed",tracked=True):
    return {"platform":"instagram","format":fmt,"media_id":identifier,"timestamp":created.isoformat(),
        "collected_at":(created+timedelta(hours=age)).isoformat(),
        "tracking_code":tracking_code_for(identifier) if tracked else None,"metrics":{"reach":reach,"saved":0}}

def cohorts():
    return ([row("before"+str(i),START-timedelta(days=5)) for i in range(6)]
        +[row("after"+str(i),START+timedelta(days=3)) for i in range(6)])

def available(count):return {"status":"available","distinct_contacts":count,"per_reference":{}}

def test_observation_cannot_recommend_more_posts_before_the_review_date():
    report=build_review(CONFIG,cohorts(),now=END-timedelta(days=1),
        baseline_contacts=available(1),trial_contacts=available(100))
    assert report["phase"]=="en_observacion"
    assert report["recommendation"]=="mantener_frecuencia"
    assert report["automatic_frequency_changes"] is False

def test_finished_observation_can_only_recommend_a_limited_test_without_publishing():
    result=build_review(CONFIG,cohorts(),now=END,
        baseline_contacts=available(1),trial_contacts=available(4))
    assert result["recommendation"]=="considerar_prueba_limitada_dos_publicaciones_extra_por_semana"
    assert result["frequency_changed_by_report"] is False

def test_unavailable_attribution_does_not_become_zero_or_an_increase():
    result=build_review(CONFIG,cohorts(),now=END,
        baseline_contacts={"status":"database_not_configured","distinct_contacts":None},
        trial_contacts=available(4))
    assert result["baseline"]["whatsapp"]["distinct_contacts"] is None
    assert result["recommendation"]=="mantener_frecuencia"

def test_mature_samples_use_first_comparable_snapshot_not_lifetime_or_young_views():
    created=START+timedelta(days=1)
    records=[row("same",created,age=24,reach=999),row("same",created,age=48,reach=10),
        row("same",created,age=96,reach=90),row("same",created,age=120,reach=9999)]
    matched=matched_rows(records,START,END,END,[48,96])
    assert len(matched)==1 and matched[0]["metrics"]["reach"]==10

def test_stories_use_snapshots_before_expiry():
    created=START+timedelta(days=1)
    matched=matched_rows([row("story",created,age=18,reach=20,fmt="story")],START,END,END,[48,96])
    assert len(matched)==1

def test_missing_profile_metrics_remain_unknown():
    result=build_review(CONFIG,cohorts(),now=END,baseline_contacts=available(1),trial_contacts=available(4))
    stats=result["observation"]["matched_age_formats"]["instagram/feed"]["metrics"]
    assert stats["profile_visits"]=={"available_posts":0,"sum":None}
    assert stats["saved"]=={"available_posts":6,"sum":0}

def test_low_tracking_coverage_prevents_a_positive_recommendation():
    rows=cohorts()
    for item in rows[:6]:item["tracking_code"]=None
    report=build_review(CONFIG,rows,now=END,baseline_contacts=available(0),trial_contacts=available(20))
    assert report["recommendation"]=="mantener_frecuencia"

@pytest.mark.parametrize("change",[{"trial_id":"../outside"},{"starts_at":"2026-11-14T17:00:00"},{"ends_at":START.isoformat()}])
def test_trial_configuration_rejects_unsafe_or_ambiguous_values(change):
    with pytest.raises(ValueError):trial_times({**CONFIG,**change})

def test_report_updates_are_private_and_do_not_modify_the_observation_database(tmp_path):
    path=tmp_path/"config.json";path.write_text(json.dumps(CONFIG))
    record=row("ad",START+timedelta(days=1))
    save_observations(tmp_path,{"collected_at":record["collected_at"],"records":[record]})
    db=tmp_path/"observations.sqlite3";before=hashlib.sha256(db.read_bytes()).hexdigest()
    calls=[]
    def enquire(records,*,since,until):
        calls.append((since,until));return available(1)
    result=refresh_trial_report(tmp_path,path,now=END,enquire=enquire)
    assert hashlib.sha256(db.read_bytes()).hexdigest()==before
    assert (tmp_path/"trials/test_trial/latest.json").is_file()
    assert (tmp_path/"trials/test_trial/informe.md").is_file()
    assert result["frequency_changed_by_report"] is False
    assert calls==[(START-timedelta(days=14),START),(START,END)]
    assert not (tmp_path/"queue.sqlite3").exists()
