from django.conf import settings


def test_public_transcript_artifacts_use_dedicated_public_storage_alias():
    assert settings.STORAGES["cast_public_transcripts"]["BACKEND"] == "config.settings.local.CustomS3Boto3Storage"
    assert "cast_private_media" not in settings.STORAGES


def test_known_speaker_sidecars_use_private_filesystem_storage():
    assert settings.STORAGES["cast_voice_references"]["BACKEND"] == "django.core.files.storage.FileSystemStorage"
    assert str(settings.STORAGES["cast_voice_references"]["OPTIONS"]["location"]).endswith(
        "private_media/cast_voice_references"
    )
