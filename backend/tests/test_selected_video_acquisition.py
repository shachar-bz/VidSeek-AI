"""Selected media and course-supplied captions must survive acquisition dispatch."""

import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.schemas.browser import BrowserContext, CaptionCandidate, MediaCandidate
from backend.schemas.video_jobs import CreateVideoJobRequest
from backend.services.video_download import youtube_job
from backend.services.video_download.web import downloader
from backend.services.video_download.youtube import pipeline
from backend.services.video_download.youtube.downloader import DownloadedVideo


def test_selected_source_failure_never_downloads_another_video_from_the_page(tmp_path):
    with patch.object(downloader, '_download_one', side_effect=RuntimeError('expired')) as attempt:
        with pytest.raises(RuntimeError):
            downloader.download_video(
                page_url='https://example.com/feed',page_title='chosen',
                candidates=[MediaCandidate(kind='direct',url='https://cdn.example/chosen.mp4')],
                context=BrowserContext(),preferred_language=None,download_root=tmp_path,
                cancel_event=threading.Event(),
            )
    assert [c.args[0] for c in attempt.call_args_list]==['https://cdn.example/chosen.mp4']


def test_campus_captions_prevent_youtube_or_paid_transcription_lookup(tmp_path: Path):
    media=tmp_path/'clip.mp4'
    media.write_bytes(b'video')
    request=CreateVideoJobRequest(
        page_url='https://www.youtube.com/watch?v=yiioO9wYbTs',preferred_language='he',
        caption_candidates=[CaptionCandidate(format='json',language='he',text=json.dumps({
            'text':['שלום עולם'],'start':[10440],'end':[13760],
        }))],
    )
    with (
        patch.object(pipeline,'download_video',return_value=DownloadedVideo(video_id='clip',title='course',video_path=str(media))),
        patch.object(pipeline,'_build_transcript',side_effect=AssertionError('unnecessary transcription')),
        patch.object(pipeline,'_write_comments',return_value=([],None)),
        patch('backend.services.video_download.web.transcript.transcript_store.save'),
    ):
        result=youtube_job.run_youtube_job(request=request,download_root=tmp_path,cancel_event=threading.Event(),progress_callback=lambda *_:None)
    assert result.transcript_error is None
    assert result.transcript_source=='captions'
    payload=json.loads(result.transcript_json_path.read_text(encoding='utf-8'))
    assert payload['language']=='he'
    assert payload['source_segments'][0]['start_seconds']==10.44
