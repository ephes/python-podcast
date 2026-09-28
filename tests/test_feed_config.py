from django.conf import settings


def test_podcast_feeds_omit_duplicated_itunes_summary():
    # <itunes:summary> repeated <description> and was 44% of the raw feed.
    assert settings.CAST_FEED_ITUNES_SUMMARY is False
