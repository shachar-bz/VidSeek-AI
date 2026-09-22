"""Unknown provider schemas must resolve only to observed URLs, text and valid timing."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.schemas.video_jobs import CreateVideoJobRequest
from backend.services.video_download.web.structured import (
    CaptionMapping, EvidenceMapping, ResourceMapping, mapped_cues, parse_json_captions,
    resolve_evidence,
)


def mapping(**changes):
    return CaptionMapping(**dict(table=0, text_key="words", start_key="offset", end_key="finish", duration_key=None, unit="milliseconds") | changes)


def test_edx_milliseconds_are_explicit_even_for_short_values():
    cues = parse_json_captions(json.dumps({"text": ["hello", "world"], "start": [0, 500], "end": [400, 900]}), allow_llm=False)
    assert [(c.start_seconds, c.end_seconds) for c in cues] == [(0, .4), (.5, .9)]


@pytest.mark.parametrize("row", [
    {"words":"hi", "offset":2000, "finish":1000},
    {"words":"hi", "offset":0, "finish":float('nan')},
    {"words":"hi", "offset":0},
    {"words":"hi", "offset":False, "finish":1000},
])
def test_invalid_or_invented_end_fields_are_rejected(row):
    assert mapped_cues([row], mapping(), 10) == []


def test_unknown_schema_maps_only_observed_values_and_hides_credentials():
    client=Mock()
    client.responses.parse.return_value=SimpleNamespace(output_parsed=EvidenceMapping(
        media=[ResourceMapping(index=0,kind="direct"),ResourceMapping(index=999,kind="hls")],
        captions=[mapping()],
    ))
    media,cues=resolve_evidence([json.dumps({
        "video_url":"https://cdn.example/video.mp4?signature=PRIVATE",
        "authorization":"Bearer PRIVATE", "cookie":"PRIVATE",
        "transcript_a":[{"words":"exact original speech", "offset":500,"finish":1500}],
    })],10,client=client)
    assert len(media)==1 and media[0].url.endswith('signature=PRIVATE')
    assert cues[0].text=='exact original speech'
    assert (cues[0].start_seconds,cues[0].end_seconds)==(.5,1.5)
    payload=client.responses.parse.call_args.kwargs['input']
    assert 'PRIVATE' not in payload and 'exact original speech' not in payload


def test_missing_ends_remain_missing_in_source_cues():
    cues=parse_json_captions('{"unit":"seconds","cues":[{"text":"hello","start":1}]}',allow_llm=False)
    assert cues[0].end_seconds is None


def test_two_videos_on_one_page_do_not_share_a_deduplication_key():
    a=CreateVideoJobRequest(page_url='https://example.com/feed',selected_media_id='one')
    b=a.model_copy(update={'selected_media_id':'two'})
    assert a.source_identity_url!=b.source_identity_url
    assert a.page_url==b.page_url


def test_resolver_failure_abstains():
    client=Mock()
    client.responses.parse.side_effect=TimeoutError()
    assert resolve_evidence(['{"video":"https://cdn.example/full.mp4"}'],client=client)==([],[])


def test_canonical_mixed_end_times_preserve_every_explicit_end():
    cues=parse_json_captions('{"unit":"seconds","cues":[{"text":"a","start":1,"end":2},{"text":"b","start":3}]}',allow_llm=False)
    assert [(c.start_seconds,c.end_seconds) for c in cues]==[(1,2),(3,None)]
