from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from conecta_video_ai.social_analytics import (metric_values,ReadBudget,analyze,rotation_policy,
    adaptive_sequence_index,save_observations,latest_observations,MetaInsightsCollector)

NOW=datetime(2026,11,13,22,tzinfo=timezone.utc)

def record(category="electricidad",*,identifier="1",reach=100,saved=2,age=120,objective="captar_clientes",fmt="feed",platform="instagram"):
    return {"platform":platform,"media_id":identifier,"format":fmt,"timestamp":(NOW-timedelta(hours=age)).isoformat(),
            "collected_at":NOW.isoformat(),"objective":objective,"category_id":category,
            "metrics":{"reach":reach,"views":reach*2,"saved":saved,"shares":0,"profile_visits":0,"follows":0},
            "issues":[]}

def test_metric_parser_preserves_zero_and_never_invents_missing_values():
    d=metric_values({"data":[{"name":"views","values":[{"value":0}]},{"name":"reach","values":[]},{"name":"saved","total_value":{"value":2}}]})
    assert d=={"views":0,"saved":2}
    assert "reach" not in d

def test_read_budget_blocks_before_an_additional_request():
    budget=ReadBudget(2)
    budget.reserve();budget.reserve()
    with pytest.raises(RuntimeError,match="budget"):budget.reserve()
    assert budget.used==2

def test_no_conversion_is_inferred_from_views():
    result=analyze([record(saved=0)],now=NOW)
    assert result["top_by_intent"][0]["intent_points"]==0
    assert "clicks" not in result["top_by_intent"][0]
    assert not result["policy"]["category_weights"]

def test_small_young_or_single_category_samples_do_not_change_rotation():
    assert not analyze([record(identifier=str(i),age=2,saved=50) for i in range(6)],now=NOW)["policy"]["category_weights"]
    assert not analyze([record(identifier=str(i),reach=10) for i in range(3)],now=NOW)["policy"]["category_weights"]
    assert not analyze([record(identifier=str(i)) for i in range(3)],now=NOW)["policy"]["category_weights"]

def test_adaptive_weights_need_comparable_mature_samples_and_are_bounded():
    rows=[record("electricidad",identifier="a"+str(i),saved=20) for i in range(3)]
    rows += [record("gasfiteria",identifier="b"+str(i),saved=1) for i in range(3)]
    weights=analyze(rows,now=NOW)["policy"]["category_weights"]
    assert weights=={"electricidad":1.3,"gasfiteria":.85}
    for r in rows:r["objective"]="captar_proveedores"
    assert not analyze(rows,now=NOW)["policy"]["category_weights"]

def test_stale_observations_do_not_drive_fresh_policy():
    rows=[record(c,identifier=c+str(i),saved=5) for c in ["electricidad","gasfiteria"] for i in range(3)]
    for r in rows:r["collected_at"]=(NOW-timedelta(days=3)).isoformat()
    assert not analyze(rows,now=NOW)["policy"]["category_weights"]

def test_missing_or_expired_policy_keeps_existing_sequence(tmp_path):
    assert rotation_policy(tmp_path,now=NOW)=={}
    folder=tmp_path/"instagram/analytics";folder.mkdir(parents=True)
    (folder/"policy.json").write_text(json.dumps({"generated_at":(NOW-timedelta(hours=49)).isoformat(),"category_weights":{"electricidad":1.3}}))
    assert rotation_policy(tmp_path,now=NOW)=={}

def test_adaptive_sequence_reserves_exploration_and_excludes_recent_assets(tmp_path,monkeypatch):
    monkeypatch.setattr("conecta_video_ai.social_analytics.stamp",lambda:NOW)
    folder=tmp_path/"instagram/analytics";folder.mkdir(parents=True)
    (folder/"policy.json").write_text(json.dumps({"generated_at":NOW.isoformat(),"category_weights":{"electricidad":1.3}}))
    pool=[SimpleNamespace(path=Path(str(i))) for i in range(3)]
    catalog={str(i):{"category_id":"electricidad"} for i in range(3)}
    state={"counter":3,"recent_assets":["0","1"]}
    assert adaptive_sequence_index(pool,0,state,catalog,str,tmp_path)==0
    state["counter"]=4
    assert adaptive_sequence_index(pool,0,state,catalog,str,tmp_path)==2

def test_snapshots_keep_story_history_and_platform_identity(tmp_path):
    first={"collected_at":NOW.isoformat(),"records":[record(fmt="story"),record(platform="facebook")]}
    save_observations(tmp_path,first)
    second={"collected_at":(NOW+timedelta(hours=6)).isoformat(),"records":[record(identifier="2")]}
    save_observations(tmp_path,second)
    assert len(latest_observations(tmp_path))==3

def test_collecting_metrics_cannot_publish_and_preserves_permission_failure(tmp_path):
    class Publisher:
        page_id="page";ig_user_id="ig"
        def resolve_page_access_token(self):return "test"
        def _http(self,*,method,path,params,access_token=None):
            assert method=="GET"
            if path in {"/ig","/page"}:return {"id":path}
            if path=="/ig/media":return {"data":[{"id":"1","media_type":"IMAGE","timestamp":NOW.isoformat(),"like_count":0}]}
            if path in {"/ig/stories","/page/posts","/page/stories"}:return {"data":[]}
            if path=="/1/insights":return {"data":[{"name":"reach","values":[{"value":12}]},{"name":"views","values":[{"value":30}]}]}
            raise AssertionError(path)
    result=MetaInsightsCollector(Publisher(),tmp_path,now=NOW).collect()
    assert len(result["records"])==1
    assert result["records"][0]["metrics"]=={"likes":0,"reach":12,"views":30}
    assert "link_clicks" not in result["records"][0]["metrics"]

def test_malformed_policy_does_not_interrupt_publication(tmp_path):
    folder=tmp_path/"instagram/analytics";folder.mkdir(parents=True)
    for value in [[],{"generated_at":NOW.isoformat(),"category_weights":[]}]:
        (folder/"policy.json").write_text(json.dumps(value))
        assert rotation_policy(tmp_path,now=NOW)=={}
